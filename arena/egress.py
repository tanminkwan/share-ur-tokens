"""Egress: the one way out of a peer (dev/phase10/out-gateway.md 3.4). Every HTTP call a peer makes of its own (A2A, broker,
recorder, api connections, app downloads, webhooks, LLM) is made with a client from its Egress, so how calls leave is
decided in one place. `via` None is httpx's usual way (proxy environment included); the transport adapter
(arena/peer/relay_link.py) sets another transport while the peer sits behind a relay. Nothing above knows."""
from __future__ import annotations

from typing import Callable

import httpx


class Egress:
    def __init__(self):
        self.via: httpx.AsyncBaseTransport | None = None

    def client(self, **kw) -> httpx.AsyncClient:
        """a new client whose calls leave by the way set now"""
        return httpx.AsyncClient(transport=self.via, **kw)


class EgressTransport(httpx.AsyncBaseTransport):
    """for a client that lives long (a webhook sender, an SDK client): each request leaves by the way set when it is sent.
    egress: a function giving the Egress (its owner may be handed the peer's own one later)"""

    def __init__(self, egress: Callable[[], Egress]):
        self.egress = egress
        self._plain: httpx.AsyncClient | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        via = self.egress().via
        if via is not None:
            return await via.handle_async_request(request)
        if self._plain is None:
            self._plain = httpx.AsyncClient()  # httpx's usual way, proxy environment included
        return await self._plain.send(request, stream=True)

    async def aclose(self) -> None:
        if self._plain is not None:
            await self._plain.aclose()


def share(egress: Egress, *parts) -> None:
    """hand one Egress to every part that makes calls (a part holding several clients, like a failover group, passes it on)"""
    for p in parts:
        if p is None:
            continue
        if hasattr(p, "egress"):
            p.egress = egress
        for inner in getattr(p, "clients", None) or []:
            share(egress, inner)
