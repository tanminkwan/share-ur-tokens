"""Peer: one member's agent. Assembled from platform parts (identity, public area, owner, LLM, transport, brokers)
and a list of apps. Platform ops: engage (role contract) and approve (event approval); apps add the rest."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from ..a2a import Transport, build_a2a_app
from ..config import Settings
from ..crypto import Identity, pen_name
from ..events import EventLog
from ..llm import LLM
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
        self._ops = {"engage": self._engage, "approve": self._approve}
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
        self.log.emit("profile", self.pen, f"프로필 게시(v{profile['ver']}): {profile['summary'][:100]}")
        return profile

    async def add_experience(self, note: str) -> None:
        self.area.add_note(note)
        await self.advertise()

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
