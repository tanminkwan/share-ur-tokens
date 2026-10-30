"""Peer: one member's agent. Assembled from platform parts (identity, public area, owner, LLM, transport, brokers)
and a list of apps. Platform ops: engage (role contract) and approve (event approval); apps add the rest."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from ..a2a import Transport, build_a2a_app
from ..config import Settings
from ..crypto import Identity, pen_name, verify
from ..events import EventLog
from ..llm import LLM
from ..recorder.client import RecorderAPI, RecorderClient
from .app import PeerApp
from .area import PublicArea
from .owner import Owner
from .profile import ProfileBuilder
from .receipts import Receipts


@dataclass
class PeerConfig:
    """what the person decided about their peer (identity set by the person, not by the agent)"""
    url: str
    offers: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


class Peer:
    def __init__(self, identity: Identity, settings: Settings, config: PeerConfig, area: PublicArea, owner: Owner, llm: LLM,
                 transport: Transport, log: EventLog, brokers: dict, apps: list[PeerApp], clock: Callable[[], float] = time.time):
        self.identity, self.settings, self.config, self.area, self.owner = identity, settings, config, area, owner
        self.llm, self.transport, self.log, self.brokers, self.apps, self.clock = llm, transport, log, brokers, list(apps), clock
        self.pen = pen_name(identity.pub, settings.pen_name_prefix, settings.pen_name_len)
        self.receipts, self.profiles = Receipts(), ProfileBuilder()
        self.recorder_factory: Callable[[str], RecorderAPI] = lambda url: RecorderClient(url, settings)
        self.known_recorders: list[str] = list(settings.peer_track_recorders)
        self.inbox: deque = deque(maxlen=settings.solicit_inbox_size)
        self.last_profile: dict | None = None
        self._group_ids: dict[str, str] = {}
        self._ops = {"engage": self._engage, "approve": self._approve, "solicit": self._solicit}
        for app in self.apps:
            for op, fn in app.ops().items():
                if op in self._ops:
                    raise ValueError(f"op {op!r} registered twice (app {app.name})")
                self._ops[op] = (lambda f: (lambda msg: f(self, msg)))(fn)

    # ---- identity, assembly ----
    def sign(self, payload) -> str:
        return self.identity.sign(payload)

    def offers(self) -> list[str]:
        out = list(self.config.offers)
        for app in self.apps:
            out += [o for o in app.offers() if o not in out]
        return out

    def skills(self) -> list[str]:
        return list(self._ops)

    def app(self, cls):
        return next((a for a in self.apps if isinstance(a, cls)), None)

    def recorder(self, url: str) -> RecorderAPI:
        if url not in self.known_recorders:
            self.known_recorders.append(url)
        return self.recorder_factory(url)

    async def group_id(self, group: str) -> str:
        """the broker group identifier of one of my broker groups (asked once, then remembered)"""
        if group not in self._group_ids:
            gid = (await self.brokers[group].health()).get("group_id")
            if not gid:
                raise RuntimeError(f"broker group {group!r} has no group_id")
            self._group_ids[group] = gid
        return self._group_ids[group]

    def current_labels(self) -> list[str]:
        """labels on my posted profile (person-set + capability labels), or the person-set ones before the first post"""
        return list(self.last_profile["labels"]) if self.last_profile else list(self.config.labels)

    def a2a_app(self):
        return build_a2a_app(f"peer-{self.pen}", f"peer {self.pen}", self.config.url, self.skills(), self.handle)

    async def start(self) -> None:
        for app in self.apps:
            await app.start(self)

    # ---- messages ----
    async def handle(self, msg: dict) -> dict:
        fn = self._ops.get(msg.get("op"))
        if fn is None:
            return {"ok": False, "error": f"unknown op: {msg.get('op')}"}
        try:
            return await fn(msg)
        except Exception as e:
            self.log.emit("peer", self.pen, f"{msg.get('op')} 처리 실패: {type(e).__name__}: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def call(self, url: str, msg: dict, timeout: float | None = None) -> dict:
        return await self.transport.call(url, msg, timeout)

    # ---- profile ----
    async def advertise(self) -> dict:
        profile = await self.profiles.build(self)
        for group, broker in self.brokers.items():
            r = await broker.advertise(self.identity, profile)
            if not r.get("ok"):
                self.log.emit("profile", self.pen, f"{group} 게시 실패: {r.get('error')}")
        self.last_profile = profile
        caps = [c["label"] for c in profile.get("capabilities", [])]
        self.log.emit("profile", self.pen, f"프로필 게시(v{profile['ver']}): {profile['summary'][:100]}" + (f" | 역량 라벨: {', '.join(caps)}" if caps else ""))
        return profile

    async def add_experience(self, note: str) -> None:
        self.area.add_note(note)
        await self.advertise()

    # ---- direct requests without a notice board ----
    async def solicit(self, targets: list[str], request: dict) -> dict:
        """sign a request and send it to the chosen peers at once; returns each target's acknowledgement"""
        sig = self.sign(request)

        async def one(url):
            try:
                return await self.call(url, {"op": "solicit", "request": request, "sig": sig})
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        acks = await asyncio.gather(*(one(u) for u in targets))
        ok = sum(bool(a.get("ok")) for a in acks)
        self.log.emit("solicit", self.pen, f"직접 요청 {request.get('request_id')} → {len(targets)}명 중 {ok}명 수신")
        return dict(zip(targets, acks))

    async def _solicit(self, msg: dict) -> dict:
        r, sig = msg.get("request", {}), msg.get("sig", "")
        issuer = r.get("issuer_pub", "")
        if not verify(issuer, r, sig):
            return {"ok": False, "error": "bad signature"}
        if r.get("until", 0) <= self.clock():
            return {"ok": False, "error": "request expired"}
        labels = set(self.current_labels())
        if not all(f"{k}:{v}" in labels for k, v in r.get("audience", {}).items()):  # the broker's audience rule
            return {"ok": False, "error": "audience mismatch"}
        if any(x["request"].get("request_id") == r.get("request_id") and x["sender"] == issuer for x in self.inbox):
            return {"ok": False, "error": "duplicate request"}
        self.inbox.append({"request": r, "sender": issuer, "ts": self.clock()})
        self.log.emit("solicit", self.pen, f"직접 요청 받음 {r.get('request_id')}: {str(r.get('title', ''))[:40]}")
        for app in self.apps:
            asyncio.create_task(app.on_request(self, r, issuer))
        return {"ok": True, "received": True}

    # ---- platform ops ----
    async def _engage(self, msg: dict) -> dict:
        role, contract = msg.get("role"), msg.get("contract", {})
        if role not in self.offers() or contract.get("role") != role:
            return {"ok": False, "error": f"role {role} not offered"}
        if contract.get("contractor") != self.identity.pub:
            return {"ok": False, "error": "the contract names another contractor"}
        for app in self.apps:
            d = await app.accept_role(self, role, msg.get("request", {}))
            if d is not None:
                self.log.emit("contract", self.pen, f"'{role}' 역할 계약 {'수락' if d.accept else '거절'}: {d.reason[:80]}")
                return {"ok": True, "sig": self.sign(contract), "reason": d.reason} if d.accept else {"ok": False, "error": d.reason}
        return {"ok": False, "error": f"no app decides about role {role}"}

    async def _approve(self, msg: dict) -> dict:
        event = msg.get("event", {})
        if self.identity.pub not in event.get("approvers", []):
            return {"ok": False, "error": "I am not an approver of this event"}
        for app in self.apps:
            d = await app.approve_event(self, event, msg.get("request", {}))
            if d is not None:
                self.log.emit("approve", self.pen, f"이벤트 {event.get('event_id')} 결재 {'승인' if d.accept else '반려'}: {d.reason[:80]}")
                return {"ok": True, "sig": self.sign(event), "reason": d.reason} if d.accept else {"ok": False, "error": d.reason}
        return {"ok": False, "error": "no app approves events here"}
