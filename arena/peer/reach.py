"""PeerReach: reaching another peer by the connection its posted profile lists that code may use (a2a first, else api;
P6-A8, P6-Q1). One responsibility: getting a message to a peer. The A2A call and the REST binding are injected."""
from __future__ import annotations

from typing import Awaitable, Callable

from ..connections import pick


class PeerReach:
    def __init__(self, identity, brokers: dict, a2a_call: Callable[..., Awaitable[dict]], rest_of: Callable,
                 human_wait: Callable[[], float | None] = lambda: None):
        """rest_of() gives the REST binding to use (read when calling, so it may be replaced); human_wait() how long to
        follow a slow answer of a human peer (a person answers at a person's pace)"""
        self.identity, self.brokers, self.a2a_call, self.rest_of, self.human_wait = identity, brokers, a2a_call, rest_of, human_wait

    async def profile_of(self, pub: str) -> dict | None:
        """the peer's posted profile on any of my brokers"""
        for broker in self.brokers.values():
            try:
                found = next((p for p in (await broker.list_profiles(identity=self.identity)).get("profiles", []) if p["pub"] == pub), None)
            except Exception:
                continue
            if found:
                return found
        return None

    async def call(self, pub: str, msg: dict, timeout: float | None = None, group: str | None = None, event: str | None = None,
                   url: str | None = None) -> dict:
        """without a profile on my brokers, the address the peer gave (`url`) is used as an A2A address"""
        prof = await self.profile_of(pub)
        if prof is None and url:
            return await self.a2a_call(url, msg, timeout, group=group, event=event)
        conns = (prof or {}).get("connections") or ([{"kind": "a2a", "url": prof["url"]}] if prof and prof.get("url") else [])
        c = pick(conns)
        if c is None:
            return {"ok": False, "error": "no connection method this peer can use (a2a or api)"}
        if c["kind"] == "a2a":
            wait = self.human_wait() if (prof or {}).get("operator") == "human" else None
            return await self.a2a_call(c["url"], msg, timeout, group=group, event=event, **({"wait": wait} if wait else {}))
        meta = {"group_id": group, "event_id": event} if (group or event) else None
        return await self.rest_of().call(c["url"], msg, timeout, meta)
