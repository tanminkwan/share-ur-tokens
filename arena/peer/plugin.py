"""How apps plug into a peer. An app is any object with a `name` and a `version` that implements one or more small
capability interfaces below. The peer connects only the capabilities an app has, and injects an AppContext (never
the peer itself). See dev/app-guide.md for the full convention."""
from __future__ import annotations

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


CAPABILITIES = (OpProvider, OfferProvider, RoleAcceptor, EventApprover, RequestReceiver, ProfileContributor, Lifecycle)


def capabilities_of(app) -> list[str]:
    return [c.__name__ for c in CAPABILITIES if isinstance(app, c)]


class BaseApp:
    """optional convenience base: only a name and a version. Implement the capability methods you need."""
    name = "app"
    version = "1.0"
