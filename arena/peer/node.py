"""Peer: one member's agent. It assembles platform parts (identity, public area, owner, LLM, transport, brokers) and
plugs in apps. It does three things only: check and route messages to the app that registered the op, give each app
its own AppContext, and keep what must survive a restart. Platform ops are built-in apps (builtin.py)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from ..a2a import Transport, build_a2a_app
from ..config import Settings
from ..crypto import Identity, pen_name
from ..events import EventLog
from ..llm import LLM
from ..recorder.client import RecorderAPI, RecorderClient
from .area import PublicArea
from .builtin import RESERVED_OPS, DirectRequests, EventApprovals, RoleContracts
from .context import AppContext, PlatformContext
from .owner import Owner
from .plugin import SDK_VERSION, App, Lifecycle, MessageHead, OfferProvider, OpProvider, capabilities_of
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
                 transport: Transport, log: EventLog, brokers: dict, apps: list, clock: Callable[[], float] = time.time,
                 home=None):
        self.identity, self.settings, self.config, self.area, self.owner = identity, settings, config, area, owner
        self.llm, self.transport, self.log, self.brokers, self.clock = llm, transport, log, brokers, clock
        self.pen = pen_name(identity.pub, settings.pen_name_prefix, settings.pen_name_len)
        self.home = home  # PeerHome: what must survive a restart
        saved = home.load_state() if home else {}
        self.receipts = Receipts(home.load_receipts() if home else [], on_keep=home.append_receipt if home else None)
        self.profiles = ProfileBuilder()
        self.profiles.version = saved.get("profile_ver", 0)
        self.recorder_factory: Callable[[str], RecorderAPI] = lambda url: RecorderClient(url, settings)
        self.known_recorders: list[str] = list(dict.fromkeys(list(settings.peer_track_recorders) + saved.get("known_recorders", [])))
        self.app_states: dict = saved.get("apps", {})
        if "inbox" in saved:  # older homes kept the inbox at the top level
            self.app_states.setdefault(DirectRequests.name, {"inbox": saved["inbox"]})
        self.last_profile: dict | None = None
        self._group_ids: dict[str, str] = {}
        self._requests = DirectRequests(settings)
        self.builtins = [RoleContracts(), EventApprovals(), self._requests]
        self.apps = list(apps)
        self._contexts: dict[int, AppContext] = {}
        self._ops: dict[str, tuple[object, Callable]] = {}
        self._register()

    # ---- assembly ----
    def _register(self) -> None:
        self._names: set[str] = set()
        for app in self.builtins:
            self._register_one(app, builtin=True)
        for app in self.apps:
            self._register_one(app, builtin=False)
        self._requests.load(self._contexts[id(self._requests)])

    def _register_one(self, app, builtin: bool) -> None:
        """the assembly rules every app passes (dev/app-guide.md): name+version, a capability, unique name and ops"""
        if not isinstance(app, App):
            raise ValueError(f"{app!r} is not an app: it needs a name and a version")
        if not capabilities_of(app):
            raise ValueError(f"app {app.name!r} has no capability (see dev/app-guide.md)")
        wanted = str(getattr(app, "sdk", SDK_VERSION)).split(".")[0]
        if wanted != SDK_VERSION.split(".")[0]:
            raise ValueError(f"app {app.name!r} was built for SDK {wanted}, this platform offers SDK {SDK_VERSION}")
        if app.name in self._names:
            raise ValueError(f"app name {app.name!r} registered twice")
        ops = app.ops() if isinstance(app, OpProvider) else {}
        for op in ops:
            if op in RESERVED_OPS and not builtin:
                raise ValueError(f"op {op!r} is reserved by the platform (app {app.name})")
            if op in self._ops:
                raise ValueError(f"op {op!r} registered twice (app {app.name})")
        self._names.add(app.name)
        self._contexts[id(app)] = (PlatformContext if builtin else AppContext)(self, app.name)
        for op, fn in ops.items():
            self._ops[op] = (app, fn)

    async def install(self, app) -> None:
        """plug an app into a running peer: same checks as at assembly, then start it"""
        self._register_one(app, builtin=False)
        self.apps.append(app)
        if isinstance(app, Lifecycle):
            await app.start(self.ctx(app))

    def ctx(self, app_or_cls) -> AppContext:
        """the context the platform injects into an app (tests and composition roots use this to drive an app)"""
        app = app_or_cls if not isinstance(app_or_cls, type) else self.app(app_or_cls)
        return self._contexts[id(app)]

    def sign(self, payload) -> str:
        return self.identity.sign(payload)

    def offers(self) -> list[str]:
        out = list(self.config.offers)
        for app in self.apps:
            if isinstance(app, OfferProvider):
                out += [o for o in app.offers() if o not in out]
        return out

    def skills(self) -> list[str]:
        return list(self._ops)

    def app(self, cls):
        return next((a for a in self.apps + self.builtins if isinstance(a, cls)), None)

    def recorder(self, url: str) -> RecorderAPI:
        if url not in self.known_recorders:
            self.known_recorders.append(url)
            self.persist()
        return self.recorder_factory(url)

    @property
    def inbox(self):
        return self._requests.inbox

    # ---- persistence across restarts ----
    def persist(self) -> None:
        if self.home:
            self.home.save_state({"profile_ver": self.profiles.version, "known_recorders": self.known_recorders, "apps": self.app_states})

    async def group_id(self, group: str) -> str:
        """the broker group identifier of one of my broker groups (asked once, then remembered)"""
        if group not in self._group_ids:
            gid = (await self.brokers[group].health()).get("group_id")
            if not gid:
                raise RuntimeError(f"broker group {group!r} has no group_id")
            self._group_ids[group] = gid
        return self._group_ids[group]

    async def my_group_ids(self) -> set[str]:
        out = set()
        for g in self.brokers:
            try:
                out.add(await self.group_id(g))
            except Exception:
                pass
        return out

    def current_labels(self) -> list[str]:
        """labels on my posted profile (person-set + capability labels), or the person-set ones before the first post"""
        return list(self.last_profile["labels"]) if self.last_profile else list(self.config.labels)

    def a2a_app(self):
        return build_a2a_app(f"peer-{self.pen}", f"peer {self.pen}", self.config.url, self.skills(), self.handle)

    async def start(self) -> None:
        for app in self.apps:
            if isinstance(app, Lifecycle):
                await app.start(self.ctx(app))

    # ---- messages ----
    async def _check_head(self, msg: dict, head: MessageHead) -> str | None:
        """the head (group, event) is read before the body: refuse groups I am not in and bodies that disagree"""
        if head.group_id and head.group_id not in await self.my_group_ids():
            return f"not a member of broker group {head.group_id}"
        if head.group_id and "group_id" in msg and msg["group_id"] != head.group_id:
            return "group_id in the body differs from the head"
        if head.event_id and "event_id" in msg and msg["event_id"] != head.event_id:
            return "event_id in the body differs from the head"
        return None

    async def handle(self, msg: dict, meta: dict | None = None) -> dict:
        entry = self._ops.get(msg.get("op"))
        if entry is None:
            return {"ok": False, "error": f"unknown op: {msg.get('op')}"}
        head = MessageHead.of(meta)
        bad = await self._check_head(msg, head)
        if bad:
            return {"ok": False, "error": bad}
        app, fn = entry
        try:
            return await fn(self.ctx(app), msg, head)
        except Exception as e:
            self.log.emit("peer", self.pen, f"{msg.get('op')} 처리 실패({app.name}): {type(e).__name__}: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def call(self, url: str, msg: dict, timeout: float | None = None, group: str | None = None, event: str | None = None) -> dict:
        """send to another peer; group/event (if this is about one) ride in the message head"""
        meta = {"group_id": group, "event_id": event} if (group or event) else None
        return await self.transport.call(url, msg, timeout, meta) if meta else await self.transport.call(url, msg, timeout)

    async def solicit(self, targets: list[str], request: dict) -> dict:
        """sign a request and send it to the chosen peers at once (the platform's direct-request app)"""
        return await self._requests.send(self.ctx(self._requests), targets, request)

    # ---- profile ----
    async def advertise(self) -> dict:
        profile = await self.profiles.build(self)
        for group, broker in self.brokers.items():
            r = await broker.advertise(self.identity, profile)
            if not r.get("ok"):
                self.log.emit("profile", self.pen, f"{group} 게시 실패: {r.get('error')}")
        self.last_profile = profile
        self.persist()
        caps = [c["label"] for c in profile.get("capabilities", [])]
        self.log.emit("profile", self.pen, f"프로필 게시(v{profile['ver']}): {profile['summary'][:100]}" + (f" | 역량 라벨: {', '.join(caps)}" if caps else ""))
        return profile

    async def add_experience(self, note: str) -> None:
        self.area.add_note(note)
        await self.advertise()
