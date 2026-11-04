"""Clients for the broker. Peers depend on BrokerAPI only; the HTTP and in-memory implementations are interchangeable.
Every method returns the same {"ok": bool, ...} shape as the HTTP API."""
from __future__ import annotations

from typing import Iterable, Protocol

import httpx

from ..config import Settings
from ..crypto import Identity
from ..signing import sign_request
from .api import GROUP_ONLY, NEED_PROFILE
from .neighbors import Caller
from .service import BrokerService


class ProfileBoard(Protocol):
    """profiles: post one, list them, search them"""
    async def advertise(self, identity: Identity, profile: dict) -> dict: ...
    async def list_profiles(self, identity: Identity | None = None) -> dict: ...
    async def find(self, q: str, role: str | None = None, labels: Iterable[str] = (), exclude: Iterable[str] = (),
                   k: int | None = None, identity: Identity | None = None) -> dict: ...


class NoticeBoard(Protocol):
    """notices: post, close, read what I may see, read changes, search"""
    async def post_notice(self, identity: Identity, notice: dict) -> dict: ...
    async def close_notice(self, identity: Identity, notice_id: str) -> dict: ...
    async def list_notices(self, identity: Identity) -> dict: ...
    async def changed_notices(self, identity: Identity, since: float) -> dict: ...
    async def search_notices(self, identity: Identity, q: str, k: int | None = None) -> dict: ...


class GroupAdmin(Protocol):
    """closed groups: the owner grants time-limited membership"""
    async def grant(self, owner: Identity, pub: str, until: float) -> dict: ...


class GroupBoard(Protocol):
    """the group's declaration (P6-N1): the founder posts it, anyone reads it"""
    async def declare_group(self, founder: Identity, decl: dict) -> dict: ...
    async def group(self) -> dict: ...


class Health(Protocol):
    async def health(self) -> dict: ...


class BrokerAPI(ProfileBoard, NoticeBoard, GroupAdmin, GroupBoard, Health, Protocol):
    """the whole broker; each user should depend on the smallest part it needs"""


def _ad(identity: Identity, profile: dict) -> dict:
    return {"pub": identity.pub, "profile": profile, "sig": identity.sign(profile)}


class BrokerClient:
    def __init__(self, base_url: str, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.base_url, self.settings, self._http = base_url.rstrip("/"), settings, http_client

    async def _call(self, method, path, identity=None, json=None, params=None) -> dict:
        headers = sign_request(identity, method, path) if identity else {}
        kw = dict(json=json, params=params, headers=headers)
        if self._http is not None:
            r = await self._http.request(method, self.base_url + path, **kw)
        else:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_sec) as hc:
                r = await hc.request(method, self.base_url + path, **kw)
        return r.json()

    async def advertise(self, identity, profile):
        return await self._call("POST", "/profiles", json=_ad(identity, profile))

    async def list_profiles(self, identity=None):
        return await self._call("GET", "/profiles", identity=identity)

    async def find(self, q, role=None, labels=(), exclude=(), k=None, identity=None):
        params = [("q", q)] + ([("role", role)] if role else []) + ([("k", str(k))] if k else [])
        params += [("label", x) for x in labels] + [("exclude", x) for x in exclude]
        return await self._call("GET", "/profiles/search", identity=identity, params=params)

    async def post_notice(self, identity, notice):
        return await self._call("POST", "/notices", json={"notice": notice, "sig": identity.sign(notice)})

    async def close_notice(self, identity, notice_id):
        return await self._call("POST", f"/notices/{notice_id}/close", json={"sig": identity.sign({"close": notice_id})})

    async def list_notices(self, identity):
        return await self._call("GET", "/notices", identity=identity)

    async def changed_notices(self, identity, since):
        return await self._call("GET", "/notices", identity=identity, params={"since": repr(float(since))})

    async def search_notices(self, identity, q, k=None):
        return await self._call("GET", "/notices/search", identity=identity, params={"q": q, **({"k": str(k)} if k else {})})

    async def grant(self, owner, pub, until):
        g = {"pub": pub, "until": until}
        return await self._call("POST", "/grants", json={"grant": g, "sig": owner.sign(g)})

    async def declare_group(self, founder, decl):
        return await self._call("POST", "/group", json={"declaration": decl, "sig": founder.sign(decl)})

    async def group(self):
        return await self._call("GET", "/group")

    async def health(self):
        return await self._call("GET", "/health")


class InMemoryBrokerClient:
    """same interface, calls the service object directly (the caller's identity is trusted in-process)"""

    def __init__(self, svc: BrokerService):
        self.svc = svc

    @staticmethod
    def _caller(identity):
        return Caller(identity.pub) if identity else Caller.anonymous()

    async def advertise(self, identity, profile):
        return await self.svc.advertise(_ad(identity, profile))

    async def list_profiles(self, identity=None):
        out = await self.svc.list_profiles(self._caller(identity))
        return {"ok": False, "error": GROUP_ONLY} if out is None else {"ok": True, "profiles": out}

    async def find(self, q, role=None, labels=(), exclude=(), k=None, identity=None):
        out = await self.svc.find(self._caller(identity), q, role=role, labels=labels, exclude=exclude, k=k)
        return {"ok": False, "error": GROUP_ONLY} if out is None else {"ok": True, "peers": out}

    async def post_notice(self, identity, notice):
        return await self.svc.post_notice(notice, identity.sign(notice))

    async def close_notice(self, identity, notice_id):
        return await self.svc.close_notice(notice_id, identity.sign({"close": notice_id}))

    async def list_notices(self, identity):
        out = await self.svc.visible_notices(identity.pub)
        return {"ok": False, "error": NEED_PROFILE} if out is None else {"ok": True, "notices": out}

    async def changed_notices(self, identity, since):
        out = await self.svc.changed_notices(identity.pub, since)
        return {"ok": False, "error": NEED_PROFILE} if out is None else {"ok": True, **out}

    async def search_notices(self, identity, q, k=None):
        out = await self.svc.search_notices(identity.pub, q, k=k)
        return {"ok": False, "error": NEED_PROFILE} if out is None else {"ok": True, "hits": out}

    async def grant(self, owner, pub, until):
        g = {"pub": pub, "until": until}
        return await self.svc.grant(g, owner.sign(g))

    async def declare_group(self, founder, decl):
        return await self.svc.declare(decl, founder.sign(decl))

    async def group(self):
        return self.svc.group()

    async def health(self):
        return self.svc.health()
