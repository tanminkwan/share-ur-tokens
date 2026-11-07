"""PeerReach: reaching another peer by the connection its posted profile lists that code may use (a2a first, else api;
P6-A8, P6-Q1). One responsibility: getting a message to a peer. The A2A call and the REST binding are injected."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from ..a2a import never_delivered
from ..connections import pick


class PeerReach:
    def __init__(self, identity, brokers: dict, a2a_call: Callable[..., Awaitable[dict]], rest_of: Callable,
                 human_wait: Callable[[], float | None] = lambda: None, settings=None, sleep=asyncio.sleep):
        """rest_of() gives the REST binding to use (read when calling, so it may be replaced); human_wait() how long to
        follow a slow answer of a human peer (a person answers at a person's pace); settings: how often to send again a call
        the peer surely never got (ARENA_PEER_CALL_RETRIES, ARENA_PEER_CALL_RETRY_SEC; none: never)"""
        self.identity, self.brokers, self.a2a_call, self.rest_of, self.human_wait = identity, brokers, a2a_call, rest_of, human_wait
        self.settings, self.sleep = settings, sleep

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

    async def a2a_url(self, pub: str) -> str | None:
        """where the peer takes A2A now, by its posted profile"""
        prof = await self.profile_of(pub)
        c = pick((prof or {}).get("connections") or ([{"kind": "a2a", "url": prof["url"]}] if prof and prof.get("url") else []), ("a2a",))
        return c["url"] if c else None

    async def call(self, pub: str, msg: dict, timeout: float | None = None, group: str | None = None, event: str | None = None,
                   url: str | None = None) -> dict:
        """without a profile on my brokers, the address the peer gave (`url`) is used as an A2A address.
        A call the peer surely never got (never_delivered) is sent again after a wait that doubles, each time to where the
        profile says the peer is then: it may be moving to another relay, or coming back to one (P10-C4)"""
        tries, nap = (self.settings.peer_call_retries, self.settings.peer_call_retry_sec) if self.settings else (0, 0.0)
        for n in range(tries + 1):
            try:
                r = await self._once(pub, msg, timeout, group, event, url)
            except Exception as e:  # noqa: BLE001  (sent again only when it surely never arrived)
                if n >= tries or not never_delivered(e):
                    raise
                await self.sleep(nap * 2 ** n)
                continue
            return dict(r, pub=pub) if isinstance(r, dict) and r.get("pending") else r  # who to look up when looking again
        raise AssertionError("unreachable")

    async def _once(self, pub, msg, timeout, group, event, url) -> dict:
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
