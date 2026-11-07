"""RelayLink: the one place in Arena that knows the connectivity server (P10-P3). The layers above (apps, assistant,
protocol messages, ledger, the meaning of a profile) never learn of it: they see one address, the peer's url.

What it does, again every ARENA_PEER_REACH_RECHECK_SEC (dev/phase10/design.md 6):
1. asks a connectivity server whether I can be reached from outside at my own port (it comes back and asks my key to sign);
2. reachable: no relay; I am announced at my own address (ARENA_PUBLIC_HOST if set, else the address the server saw);
3. not reachable: connectivity's TunnelClient attaches and I am announced at <server>/r/<my key>.
Only the A2A paths are put into my app through a relay (the agent card, JSON-RPC, my webhook)."""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from connectivity.client import TunnelClient
from starlette.routing import Route

from ..a2a import RPC_PATH
from ..a2a_push import NOTIFY_PATH

CARD_PATH = "/.well-known/agent-card.json"
A2A_PATHS = [CARD_PATH, RPC_PATH, NOTIFY_PATH]


class RelayLink:
    def __init__(self, peer, servers: list[str], sleep=asyncio.sleep):
        s = peer.settings
        self.peer, self.sleep = peer, sleep
        self.client = TunnelClient(servers, peer.identity.pub, peer.identity.sign_bytes, peer.a2a_app(), paths=A2A_PATHS,
                                   hold=s.peer_relay_hold_sec, concurrency=s.peer_relay_concurrency, retry_sec=s.broker_retry_sec,
                                   retry_max_sec=s.broker_retry_max_sec, on_base=self._on_base, sleep=sleep)
        path, endpoint = self.client.reach_route()  # my own port answers the inbound check
        peer.a2a_app().router.routes.append(Route(path, endpoint, methods=["POST"]))
        self.port = urlsplit(peer.config.url).port
        self.mode = "checking"  # direct | relay | checking
        self.last_check: dict = {}
        self._relay: asyncio.Task | None = None

    async def _on_base(self, base: str | None) -> None:
        if self.mode != "relay":
            return
        if base is None and self.client.last_error:
            self.peer.log.emit("peer", self.peer.pen, f"relay 연결 끊김, 다시 붙는 중: {self.client.last_error[:200]}")
        await self.peer.set_reach_url(base)

    async def decide(self) -> str:
        """check, then go direct or through the relay"""
        r = await self.client.check(self.port) if self.port else {"reachable": None, "error": "no port in my address"}
        self.last_check = r
        if r["reachable"]:
            await self._stop_relay()
            self.mode = "direct"
            host = r.get("source") or ""
            seen = f"http://{f'[{host}]' if ':' in host else host}:{self.port}"
            await self.peer.set_reach_url(None if self.peer.settings.public_host or not host else seen)
        elif r["reachable"] is False or self.mode == "checking":  # unknown (no server answered) keeps what was decided
            self.mode = "relay"
            if self._relay is None or self._relay.done():
                self._relay = asyncio.create_task(self.client.run())
        return self.mode

    async def _stop_relay(self) -> None:
        if self._relay and not self._relay.done():
            self._relay.cancel()
            try:
                await self._relay
            except asyncio.CancelledError:
                pass
        self._relay = None
        self.client.base = None

    async def _round(self) -> str:
        try:
            mode = await self.decide()
            self.peer.log.emit("peer", self.peer.pen, f"연결: {mode} ({self.last_check.get('why') or self.last_check.get('error') or ''})"[:200])
        except Exception as e:  # noqa: BLE001  (a check that fails is tried again later)
            self.last_check = {"reachable": None, "error": f"{type(e).__name__}: {e}"}
        return self.mode

    async def start(self) -> str:
        """the first decision, before the profile is first posted, so that the first address the broker lists is one others can
        open. Through a relay it waits (ARENA_PEER_RELAY_ATTACH_WAIT_SEC at most) for the relay address; later it is posted again"""
        mode = await self._round()
        if mode == "relay":
            loop = asyncio.get_running_loop()
            end = loop.time() + self.peer.settings.peer_relay_attach_wait_sec
            while self.client.base is None and self._relay and not self._relay.done() and loop.time() < end:
                await asyncio.sleep(0.02)
        return mode

    async def run(self, rounds: int | None = None, started: bool = False) -> None:
        """check again every ARENA_PEER_REACH_RECHECK_SEC (started: start() made the first decision already)"""
        n = 0
        while rounds is None or n < rounds:
            if started:
                await self.sleep(self.peer.settings.peer_reach_recheck_sec)
            await self._round()
            n += 1
            if not started and (rounds is None or n < rounds):
                await self.sleep(self.peer.settings.peer_reach_recheck_sec)

    async def close(self) -> None:
        await self._stop_relay()

    @property
    def state(self) -> dict:
        """for the owner's window: how I am reached (shown, never posted in the profile)"""
        return {"mode": self.mode, "relay": self.client.base, "server": self.client.server or self.last_check.get("server"),
                "source": self.last_check.get("source"), "error": self.client.last_error or self.last_check.get("error")}
