"""Brokers are distributed: a broker group can have several brokers sharing notices. A peer lists them in order
(primary first). FailoverBrokerClient is a BrokerAPI that moves to the next broker when one stops answering, re-posts
the peer's last profile there (profiles live on one broker only), restarts the change feed (broker clocks differ),
and goes back to the primary after ARENA_BROKER_FAILBACK_SEC. Callers do not notice."""
from __future__ import annotations

import time
from typing import Callable

import httpx

from ..config import Settings
from .client import BrokerAPI, BrokerClient

FAILURES = (ConnectionError, OSError, httpx.HTTPError, ValueError)  # unreachable, refused, timed out, not JSON


class BrokerUnavailable(Exception):
    pass


class FailoverBrokerClient:
    def __init__(self, clients: list[BrokerAPI], settings: Settings, clock: Callable[[], float] = time.time, on_switch=None):
        if not clients:
            raise ValueError("at least one broker")
        self.clients, self.settings, self.clock, self.on_switch = list(clients), settings, clock, on_switch
        self.current, self.switches, self.left_primary_at = 0, 0, None
        self._last_ad = None          # (identity, profile) of the last advertise, replayed on a new broker
        self._feed_from = None        # index of the broker that produced the last change-feed "now"

    @classmethod
    def from_urls(cls, urls: list[str], settings: Settings, **kw) -> "FailoverBrokerClient":
        return cls([BrokerClient(u, settings) for u in urls], settings, **kw)

    async def _switch_to(self, i: int) -> None:
        if self._last_ad is not None:
            await self.clients[i].advertise(*self._last_ad)
        if i != self.current:
            self.switches += 1
            self.left_primary_at = self.clock() if i != 0 else None
            if self.on_switch:
                self.on_switch(self.current, i)
        self.current = i

    async def _call(self, name: str, *a, **kw):
        order = list(range(self.current, len(self.clients))) + list(range(0, self.current))
        if self.current != 0 and self.left_primary_at is not None and self.clock() - self.left_primary_at >= self.settings.broker_failback_sec:
            order = [0] + [i for i in order if i != 0]  # time to try the primary again
        last = None
        for i in order:
            try:
                if i != self.current:
                    await self._switch_to(i)
                return await getattr(self.clients[i], name)(*a, **kw)
            except FAILURES as e:
                last = e
                if i == 0 and self.current == 0:
                    self.left_primary_at = self.clock()
        raise BrokerUnavailable(f"no broker in the group answers: {type(last).__name__}: {last}")

    # ---- BrokerAPI ----
    async def advertise(self, identity, profile):
        self._last_ad = (identity, profile)
        return await self._call("advertise", identity, profile)

    async def changed_notices(self, identity, since):
        start = self.current
        use_since = since if self._feed_from in (None, start) else 0.0  # a different broker: its clock differs, start over
        r = await self._call("changed_notices", identity, use_since)
        if self.current != start and use_since:  # switched during this call: read the new broker's feed from the start
            r = await self.clients[self.current].changed_notices(identity, 0.0)
        self._feed_from = self.current
        return r

    async def list_profiles(self, identity=None):
        return await self._call("list_profiles", identity)

    async def find(self, q, role=None, labels=(), exclude=(), k=None, identity=None):
        return await self._call("find", q, role=role, labels=labels, exclude=exclude, k=k, identity=identity)

    async def post_notice(self, identity, notice):
        return await self._call("post_notice", identity, notice)

    async def close_notice(self, identity, notice_id):
        return await self._call("close_notice", identity, notice_id)

    async def list_notices(self, identity):
        return await self._call("list_notices", identity)

    async def search_notices(self, identity, q, k=None):
        return await self._call("search_notices", identity, q, k=k)

    async def grant(self, owner, pub, until):
        return await self._call("grant", owner, pub, until)

    async def declare_group(self, founder, decl):
        return await self._call("declare_group", founder, decl)

    async def group(self):
        return await self._call("group")

    async def health(self):
        return await self._call("health")
