"""Presence (one job): keep this peer's profile posted on every broker group it belongs to (user 2026-11-03: a peer keeps
connecting to its broker until it connects). A broker that does not answer yet (not started, restarting, the network
is down) is tried again, waiting longer each time up to ARENA_BROKER_RETRY_MAX_SEC; once every group answers, the
profile is posted again before it expires (ARENA_PROFILE_TTL_SEC / 2). Nothing here stops the peer."""
from __future__ import annotations

import asyncio


class Presence:
    def __init__(self, peer, sleep=asyncio.sleep):
        self.peer, self.sleep = peer, sleep

    def next_wait(self, delay: float) -> tuple[float, float]:
        """(how long to wait now, the delay after that): back off while a group is unreached, refresh otherwise"""
        s = self.peer.settings
        if self.peer.unreached:
            return delay, min(delay * 2, s.broker_retry_max_sec)
        return max(1.0, s.profile_ttl_sec / 2), s.broker_retry_sec

    async def once(self) -> set:
        """post the profile on every group now; -> the groups that did not answer"""
        await self.peer.advertise()
        return set(self.peer.unreached)

    async def keep(self, rounds: int | None = None) -> None:
        """post, then keep posting (rounds: for tests; None = forever)"""
        delay = self.peer.settings.broker_retry_sec
        n = 0
        while rounds is None or n < rounds:
            await self.once()
            wait, delay = self.next_wait(delay)
            n += 1
            if rounds is None or n < rounds:
                await self.sleep(wait)
