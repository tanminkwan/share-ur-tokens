"""How a broker talks to its neighbor brokers. The service depends on NeighborGateway only (dependency inversion):
HttpNeighbors in production, InMemoryNeighbors in tests or when several brokers live in one process."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

log = logging.getLogger("arena.broker")


@dataclass(frozen=True)
class Caller:
    """who is asking: a verified public key (or None), plus the original signed headers to forward to neighbors"""
    pub: str | None
    headers: dict = field(default_factory=dict)

    @classmethod
    def anonymous(cls) -> "Caller":
        return cls(None)


class NeighborGateway(Protocol):
    async def share_notice(self, url: str, notice: dict, sig: str) -> None: ...
    async def share_close(self, url: str, notice_id: str, sig: str) -> None: ...
    async def share_group(self, url: str, decl: dict, sig: str) -> None: ...
    async def list_profiles(self, url: str, caller: Caller) -> list[dict]: ...
    async def find(self, url: str, caller: Caller, query: dict) -> list[dict]: ...


class NoNeighbors:
    async def share_notice(self, url, notice, sig):
        return None

    async def share_close(self, url, notice_id, sig):
        return None

    async def share_group(self, url, decl, sig):
        return None

    async def list_profiles(self, url, caller):
        return []

    async def find(self, url, caller, query):
        return []


class InMemoryNeighbors:
    """url -> BrokerService in the same process. `kill(url)` simulates a stopped broker."""

    def __init__(self):
        self.services, self.dead, self.calls = {}, set(), []

    def register(self, url, svc):
        self.services[url] = svc

    def kill(self, url):
        self.dead.add(url)

    def _get(self, op, url):
        self.calls.append((op, url))
        if url in self.dead or url not in self.services:
            raise ConnectionError(f"{url} unreachable")
        return self.services[url]

    async def share_notice(self, url, notice, sig):
        await self._get("share_notice", url).post_notice(notice, sig, shared=True)

    async def share_close(self, url, notice_id, sig):
        await self._get("share_close", url).close_notice(notice_id, sig, shared=True)

    async def share_group(self, url, decl, sig):
        await self._get("share_group", url).declare(decl, sig, shared=True)

    async def list_profiles(self, url, caller):
        return await self._get("list_profiles", url).list_profiles(caller, local=True) or []

    async def find(self, url, caller, query):
        return await self._get("find", url).find(caller, local=True, **query) or []


class HttpNeighbors:
    def __init__(self, timeout: float):
        self.timeout = timeout

    async def _req(self, method, url, path, **kw):
        async with httpx.AsyncClient(timeout=self.timeout) as hc:
            r = await hc.request(method, url.rstrip("/") + path, **kw)
            return r.json()

    async def share_notice(self, url, notice, sig):
        await self._req("POST", url, "/notices", json={"notice": notice, "sig": sig, "shared": True})

    async def share_close(self, url, notice_id, sig):
        await self._req("POST", url, f"/notices/{notice_id}/close", json={"sig": sig, "shared": True})

    async def share_group(self, url, decl, sig):
        await self._req("POST", url, "/group", json={"declaration": decl, "sig": sig, "shared": True})

    async def list_profiles(self, url, caller):
        return (await self._req("GET", url, "/profiles", params={"local": "1"}, headers=caller.headers)).get("profiles", [])

    async def find(self, url, caller, query):
        params = [("q", query["q"]), ("k", str(query["k"])), ("local", "1")]
        if query.get("role"):
            params.append(("role", query["role"]))
        params += [("label", x) for x in query.get("labels", [])] + [("exclude", x) for x in query.get("exclude", [])]
        return (await self._req("GET", url, "/profiles/search", params=params, headers=caller.headers)).get("peers", [])
