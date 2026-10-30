"""Apps plug into a peer. An app may add ops, publicly offered roles, profile fields, a role-acceptance judgement,
an event-approval judgement, and background work. Override only what you need; the peer never changes for a new app."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class Decision:
    accept: bool
    reason: str


OpHandler = Callable[["Peer", dict], Awaitable[dict]]  # noqa: F821


class PeerApp:
    name = "app"

    def offers(self) -> list[str]:
        return []

    def ops(self) -> dict[str, OpHandler]:
        return {}

    def profile_extra(self) -> dict:
        return {}

    async def accept_role(self, peer, role: str, request: dict) -> Decision | None:
        """None = this app has no opinion about that role"""
        return None

    async def approve_event(self, peer, event: dict, request: dict) -> Decision | None:
        return None

    async def on_request(self, peer, request: dict, sender: str) -> None:
        """a direct request (no notice board) arrived and was accepted into the inbox; runs in the background"""
        return None

    async def start(self, peer) -> None:
        pass
