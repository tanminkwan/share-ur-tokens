"""How apps plug into a peer. An app is any object with a `name` and a `version` that implements one or more small
capability interfaces below. The peer connects only the capabilities an app has, and injects an AppContext (never
the peer itself). See dev/app-guide.md for the full convention."""
from __future__ import annotations

import hashlib
import inspect
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, runtime_checkable

SDK_VERSION = "1.0"  # an app may declare `sdk = "1"`; a different major version is refused at assembly


@dataclass(frozen=True)
class Decision:
    accept: bool
    reason: str


@dataclass(frozen=True)
class MessageHead:
    """what rides in front of a message: which broker group and which event it is about (A2A context_id, metadata, headers)"""
    group_id: str | None = None
    event_id: str | None = None
    context_id: str | None = None

    @classmethod
    def of(cls, meta: dict | None) -> "MessageHead":
        meta = meta or {}
        return cls(meta.get("group_id"), meta.get("event_id"), meta.get("context_id"))


OpHandler = Callable[["AppContext", dict, MessageHead], Awaitable[dict]]  # noqa: F821


@runtime_checkable
class App(Protocol):
    name: str
    version: str
    app_id: str  # a UUID that identifies this app everywhere (events name the app they need by it)


@runtime_checkable
class OpProvider(Protocol):
    def ops(self) -> dict[str, OpHandler]: ...


@runtime_checkable
class OfferProvider(Protocol):
    def offers(self) -> list[str]: ...


@runtime_checkable
class RoleAcceptor(Protocol):
    async def accept_role(self, ctx, role: str, request: dict) -> Decision | None: ...


@runtime_checkable
class EventApprover(Protocol):
    async def approve_event(self, ctx, event: dict, request: dict) -> Decision | None: ...


@runtime_checkable
class RequestReceiver(Protocol):
    async def on_request(self, ctx, request: dict, sender: str) -> None: ...


@runtime_checkable
class ProfileContributor(Protocol):
    def profile_extra(self) -> dict: ...


@runtime_checkable
class Lifecycle(Protocol):
    async def start(self, ctx) -> None: ...


@runtime_checkable
class SubmissionSource(Protocol):
    """an app that keeps what was submitted to this peer for an event (the intake element's desk is one)"""
    def list(self, event_id: str) -> list: ...


@runtime_checkable
class TimerHandler(Protocol):
    """an app the peer's scheduler wakes at a time it (or the event's schedule) set: timer = {id, at, kind, data, event_id, late}"""
    async def on_timer(self, ctx, timer: dict) -> None: ...


@runtime_checkable
class EventHandler(Protocol):
    """an app that runs events: the platform's event router hands it the events that name its app_id (or the assistant mode)"""
    async def on_event(self, ctx, notice: dict, change: str) -> None: ...  # change: "new" | "updated" | "closed"


@runtime_checkable
class EvaluationProvider(Protocol):
    """an app that judges items handed over for evaluation (the evaluation element): [{content_hash, score, comment}]"""
    async def evaluate(self, ctx, items: list, request: dict) -> list: ...


CAPABILITIES = (OpProvider, OfferProvider, RoleAcceptor, EventApprover, RequestReceiver, ProfileContributor, Lifecycle, EventHandler,
                EvaluationProvider, TimerHandler, SubmissionSource)

# ---------------- which app runs an event, and how ----------------
from ..ledger.run import ASSISTANT_RUN, MODES, is_uuid, valid_app_ref, valid_run, version_ok  # noqa: E402,F401  (the ledger owns the run block)

ASSISTANT_APP_ID = "938604c1-2964-4bfc-96c4-91677f128508"  # the basic assistant: the primordial way


def app_fingerprint(app) -> str:
    """a hash of the app's code, so a peer can tell it runs the very app an event names"""
    try:
        src = inspect.getsource(type(app))
    except (OSError, TypeError):
        src = f"{getattr(app, 'app_id', '')}:{getattr(app, 'version', '')}:{type(app).__qualname__}"
    return hashlib.sha256(src.encode()).hexdigest()


def app_ref(app, pin_code: bool = False, required: bool = True) -> dict:
    """one entry of an event's app list block: which app, which version, optionally its exact code"""
    ref = {"id": app.app_id, "name": app.name, "version": app.version}
    if pin_code:
        ref["hash"] = app_fingerprint(app)
    if not required:
        ref["required"] = False
    return ref


def capabilities_of(app) -> list[str]:
    return [c.__name__ for c in CAPABILITIES if isinstance(app, c)]


class BaseApp:
    """optional convenience base: a name, a version and an app id. Implement the capability methods you need.
    The default app_id is derived from the class path, for development only: an app you ship states a fixed UUID."""
    name = "app"
    version = "1.0"

    @property
    def app_id(self) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"arena-app:{type(self).__module__}.{type(self).__qualname__}"))
