"""TunnelClient: the side that attaches (dev/phase10/design.md 7). It keeps polling a connectivity server, puts each
request it is given into the ASGI app it was handed (in this process: no port needs to be open) and posts the answer
back. It knows nothing of the app: a key, an app, and the servers to try. Several servers: the first that answers is
used; when it goes away the next is tried, waiting longer each time (retry_sec doubling up to retry_max_sec)."""
from __future__ import annotations

import asyncio
import base64
import inspect
from urllib.parse import urlsplit

import httpx

from .signing import sign_headers


class TunnelError(Exception):
    pass


class TunnelClient:
    def __init__(self, servers: list[str], key_hex: str, signer, app, *, paths: list[str] | None = None, hold: float = 25.0,
                 concurrency: int = 8, retry_sec: float = 2.0, retry_max_sec: float = 60.0, margin_sec: float = 10.0,
                 on_base=None, sleep=asyncio.sleep):
        if not servers:
            raise ValueError("no connectivity server")
        self.servers, self.key, self.signer, self.app = [u.rstrip("/") for u in servers], key_hex, signer, app
        self.paths, self.hold, self.margin = set(paths) if paths else None, hold, margin_sec
        self.retry, self.retry_max, self.sleep, self.on_base = retry_sec, retry_max_sec, sleep, on_base
        self.gate = asyncio.Semaphore(concurrency)
        self.base: str | None = None  # where callers reach me now (<server>/r/<key>), None while not attached
        self.server: str | None = None
        self.last_error: str | None = None
        self._tasks: set = set()

    async def _set_base(self, base: str | None) -> None:
        if base != self.base:
            self.base = base
            if self.on_base:
                r = self.on_base(base)
                if inspect.isawaitable(r):
                    await r

    def _signed(self, server: str, method: str, path: str) -> dict:
        return sign_headers(self.signer, self.key, method, urlsplit(server).path.rstrip("/") + path)

    async def run(self, rounds: int | None = None) -> None:
        """attach and serve forever (rounds: how many servers to try before returning, for tests)"""
        delay, i, n = self.retry, 0, 0
        while rounds is None or n < rounds:
            server = self.servers[i % len(self.servers)]
            try:
                async for _ in self.serve(server):
                    delay = self.retry  # attached: a later failure starts waiting from the beginning again
            except Exception as e:  # noqa: BLE001  (the server is not there, went away, or refused: try again later)
                self.last_error = f"{server}: {type(e).__name__}: {e}"
            await self._set_base(None)
            i, n = i + 1, n + 1
            if rounds is None or n < rounds:
                await self.sleep(delay)
                delay = min(delay * 2, self.retry_max)

    async def serve(self, server: str):
        """poll one server until it fails; yields after each poll (attached)"""
        local = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://local")
        async with httpx.AsyncClient(timeout=self.hold + self.margin) as hc, local:
            while True:
                r = await hc.get(f"{server}/poll", params={"hold": self.hold}, headers=self._signed(server, "GET", "/poll"))
                if r.status_code != 200:
                    raise TunnelError(f"poll answered {r.status_code}: {r.text[:200]}")
                d = r.json()
                self.server = server
                await self._set_base(d["base"])
                for req in d.get("requests", []):
                    t = asyncio.create_task(self._handle(hc, local, server, req))
                    self._tasks.add(t)
                    t.add_done_callback(self._tasks.discard)
                yield d

    async def _handle(self, hc, local, server: str, req: dict) -> None:
        """one request: into my app, the answer back. One failing never stops the others or the polling"""
        async with self.gate:
            try:
                if self.paths is not None and req["path"] not in self.paths:
                    status, headers, body = 404, {"content-type": "application/json"}, b'{"ok":false,"error":"not found"}'
                else:
                    url = req["path"] + (f"?{req['query']}" if req.get("query") else "")
                    out = await local.request(req["method"], url, headers=req.get("headers") or {},
                                              content=base64.b64decode(req.get("body") or ""))
                    status, headers, body = out.status_code, dict(out.headers), out.content
            except Exception as e:  # noqa: BLE001  (the app failed: the caller gets 502, not silence)
                status, headers, body = 502, {"content-type": "application/json"}, f'{{"ok":false,"error":"{type(e).__name__}"}}'.encode()
            path = f"/reply/{req['id']}"
            try:
                await hc.post(f"{server}{path}", headers=self._signed(server, "POST", path),
                              json={"status": status, "headers": headers, "body": base64.b64encode(body).decode("ascii")})
            except Exception as e:  # noqa: BLE001
                self.last_error = f"reply {req['id']}: {type(e).__name__}: {e}"
