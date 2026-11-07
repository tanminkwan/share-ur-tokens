"""RelayLink: the one place in Arena that knows the connectivity server (P10-P3). The layers above (apps, assistant,
protocol messages, ledger, the meaning of a profile) never learn of it: they see one address, the peer's url.

It hands my A2A app and my key's signature to connectivity's general-purpose TunnelClient. When the client is attached
it gives back the address callers reach me at (<server>/r/<my key>); I post that as my address. Only the A2A paths are
put into my app (the agent card, JSON-RPC, my webhook): nothing else of the peer is reachable through a relay."""
from __future__ import annotations

from connectivity.client import TunnelClient

from ..a2a import RPC_PATH
from ..a2a_push import NOTIFY_PATH

CARD_PATH = "/.well-known/agent-card.json"
A2A_PATHS = [CARD_PATH, RPC_PATH, NOTIFY_PATH]


class RelayLink:
    def __init__(self, peer, servers: list[str], sleep=None):
        s = peer.settings
        self.peer = peer
        kw = {"sleep": sleep} if sleep else {}
        self.client = TunnelClient(servers, peer.identity.pub, peer.identity.sign_bytes, peer.a2a_app(), paths=A2A_PATHS,
                                   hold=s.peer_relay_hold_sec, concurrency=s.peer_relay_concurrency, retry_sec=s.broker_retry_sec,
                                   retry_max_sec=s.broker_retry_max_sec, on_base=self._on_base, **kw)

    async def _on_base(self, base: str | None) -> None:
        if base is None and self.client.last_error:
            self.peer.log.emit("peer", self.peer.pen, f"relay 연결 끊김, 다시 붙는 중: {self.client.last_error[:200]}")
        await self.peer.set_relay_url(base)

    async def run(self, rounds: int | None = None) -> None:
        await self.client.run(rounds)

    @property
    def state(self) -> dict:
        """for the owner's window: where I am attached (shown, never posted in the profile)"""
        return {"relay": self.client.base, "server": self.client.server, "error": self.client.last_error}
