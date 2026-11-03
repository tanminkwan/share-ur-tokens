"""Clients for the recorder. Peers depend on RecorderAPI only; HTTP and in-memory implementations are interchangeable."""
from __future__ import annotations

from typing import Protocol

import httpx

from ..config import Settings
from ..crypto import Identity
from ..signing import sign_request
from .service import RecorderService


class RecorderAPI(Protocol):
    async def record(self, kind: str, payload: dict, sigs: dict, private: dict | None = None) -> dict: ...
    async def log(self, start: int = 0, limit: int | None = None) -> dict: ...
    async def verify(self, hash_: str) -> dict: ...
    async def audit(self) -> dict: ...
    async def health(self) -> dict: ...
    async def track(self, pub: str) -> dict: ...
    async def event_entries(self, event_id: str) -> dict: ...
    async def trust(self) -> dict: ...
    async def link(self, child_ledger_id: str) -> dict: ...
    async def key(self, pub: str) -> dict: ...
    async def codes(self) -> dict: ...
    async def codebooks(self) -> dict: ...
    async def read_chain(self, identity: Identity) -> dict: ...
    async def read_access_log(self, identity: Identity) -> dict: ...


class RecorderClient:
    def __init__(self, base_url: str, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.base_url, self.settings = base_url.rstrip("/"), settings
        self._http = http_client

    async def _call(self, method: str, path: str, identity: Identity | None = None, json: dict | None = None) -> dict:
        headers = sign_request(identity, method, path) if identity else {}
        if self._http is not None:
            r = await self._http.request(method, self.base_url + path, json=json, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_sec) as hc:
                r = await hc.request(method, self.base_url + path, json=json, headers=headers)
        return r.json()

    async def record(self, kind, payload, sigs, private=None):
        return await self._call("POST", "/entries", json={"type": kind, "payload": payload, "sigs": sigs, **({"private": private} if private else {})})

    async def log(self, start=0, limit=None):
        return await self._call("GET", f"/log?from={int(start)}" + (f"&limit={int(limit)}" if limit else ""))

    async def verify(self, hash_):
        return await self._call("GET", f"/entries/{hash_}")

    async def audit(self):
        return await self._call("GET", "/audit")

    async def health(self):
        return await self._call("GET", "/health")

    async def track(self, pub):
        return await self._call("GET", f"/track/{pub}")

    async def event_entries(self, event_id):
        return await self._call("GET", f"/events/{event_id}")

    async def trust(self):
        return await self._call("GET", "/trust")

    async def link(self, child_ledger_id):
        return await self._call("GET", f"/links/{child_ledger_id}")

    async def key(self, pub):
        return await self._call("GET", f"/key/{pub}")

    async def codes(self):
        return await self._call("GET", "/codes")

    async def codebooks(self):
        return await self._call("GET", "/codebooks")

    async def read_chain(self, identity):
        return await self._call("GET", "/chain", identity=identity)

    async def read_access_log(self, identity):
        return await self._call("GET", "/access-log", identity=identity)


class InMemoryRecorderClient:
    """same interface, calls the service object directly (tests, or a peer that hosts the recorder in-process)"""

    def __init__(self, svc: RecorderService):
        self.svc = svc

    async def record(self, kind, payload, sigs, private=None):
        return await self.svc.record(kind, payload, sigs, private)

    async def log(self, start=0, limit=None):
        return self.svc.log(start, limit)

    async def verify(self, hash_):
        return self.svc.verify(hash_)

    async def audit(self):
        return self.svc.audit()

    async def health(self):
        return self.svc.health()

    async def track(self, pub):
        return self.svc.track(pub)

    async def event_entries(self, event_id):
        return self.svc.event_entries(event_id)

    async def trust(self):
        return self.svc.trust()

    async def link(self, child_ledger_id):
        return self.svc.link(child_ledger_id)

    async def key(self, pub):
        return self.svc.key(pub)

    async def codes(self):
        return self.svc.codes()

    async def codebooks(self):
        return self.svc.codebooks()

    async def read_chain(self, identity):
        return self.svc.read_chain(identity.pub)

    async def read_access_log(self, identity):
        return self.svc.read_access_log(identity.pub)
