"""TunnelClient: the side that attaches (dev/phase10/design.md 7). It keeps polling a connectivity server, puts each
request it is given into the ASGI app it was handed (in this process: no port needs to be open) and posts the answer
back. It knows nothing of the app: a key, an app, and the servers to try. Several servers: the first that answers is
used; when it goes away the next is tried, waiting longer each time (retry_sec doubling up to retry_max_sec)."""
from __future__ import annotations

import asyncio
import base64
import inspect
import ipaddress
import json
import socket
import time
from urllib.parse import urlsplit

import httpx

from . import stun
from .reach import REACH_PATH, reach_endpoint
from .signing import sign_headers


class TunnelError(Exception):
    pass


class OutRefused(Exception):
    """the server refused or could not carry a call through its way out (status and why as the server named them)"""

    def __init__(self, status: int, why: str, message: str):
        super().__init__(f"{status} {why}: {message}")
        self.status, self.why, self.message = status, why, message


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
        self.out_ok = False  # does the server I am attached to offer its way out (GET /info)? learnt when I attach
        self.http = None  # a function giving the httpx client for /out (tests: a client reaching the server in process); None: a new one each time
        self._out_known: str | None = None
        self.last_error: str | None = None
        self._tasks: set = set()

    async def _set_base(self, base: str | None) -> None:
        if base != self.base:
            self.base = base
            if self.on_base:
                r = self.on_base(base)
                if inspect.isawaitable(r):
                    await r

    def _signed(self, server: str, method: str, path: str, body: bytes | None = None) -> dict:
        return sign_headers(self.signer, self.key, method, urlsplit(server).path.rstrip("/") + path, body=body)

    def is_server(self, url: str) -> bool:
        """is this URL one of my servers' own (same scheme, host and port)? Such a call needs no way out: the server is right there"""
        return any(origin(s) == origin(url) for s in self.servers)

    async def out(self, method: str, url: str, headers: dict, body: bytes, timeout: float = 60.0) -> tuple[int, dict, bytes]:
        """one call for me through the server's way out: (status, headers, body) of the answer, or OutRefused"""
        server = self.server or self.servers[0]
        payload = json.dumps({"url": url, "method": method, "headers": dict(headers), "body": base64.b64encode(body).decode("ascii")}).encode()
        hc = self.http() if self.http else httpx.AsyncClient(timeout=timeout)
        try:
            r = await hc.post(f"{server}/out", content=payload, headers=self._signed(server, "POST", "/out", payload))
        finally:
            if not self.http:
                await hc.aclose()
        try:
            d = r.json()
        except ValueError:
            raise OutRefused(r.status_code, "bad_answer", r.text[:100]) from None
        if r.status_code != 200 or not d.get("ok"):
            raise OutRefused(r.status_code, d.get("why") or "", d.get("error") or "")
        return int(d["status"]), d.get("headers") or {}, base64.b64decode(d.get("body") or "")

    async def _learn_out(self, hc: httpx.AsyncClient, server: str) -> None:
        """once per server I attach to: does it offer the way out?"""
        if self._out_known == server:
            return
        try:
            self.out_ok = bool((await hc.get(f"{server}/info")).json().get("out"))
        except Exception:  # noqa: BLE001  (an older server, or not there)
            self.out_ok = False
        self._out_known = server

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
            hold = 0.0  # the first poll answers at once: the caller-facing address is known before any long wait
            while True:
                r = await hc.get(f"{server}/poll", params={"hold": hold}, headers=self._signed(server, "GET", "/poll"))
                if r.status_code != 200:
                    raise TunnelError(f"poll answered {r.status_code}: {r.text[:200]}")
                d = r.json()
                self.server, hold = server, self.hold
                await self._learn_out(hc, server)
                await self._set_base(d.get("base") or f"{server}/r/{self.key}")  # the server names its outside address only when told to; else the one I connected to
                for req in d.get("requests", []):
                    t = asyncio.create_task(self._handle(hc, local, server, req))
                    self._tasks.add(t)
                    t.add_done_callback(self._tasks.discard)
                yield d

    def reach_route(self):
        """(path, endpoint) to serve on my own port so a server can check that I am reachable there"""
        return REACH_PATH, reach_endpoint(self.signer, self.key)

    async def check(self, port: int, timeout: float | None = None) -> dict:
        """ask the servers in turn whether I can be reached at my port; the first that answers decides.
        {reachable, source, server} or {reachable: None, error} when no server answered"""
        last = None
        for server in self.servers:
            try:
                async with httpx.AsyncClient(timeout=timeout or self.margin * 2) as hc:
                    r = await hc.post(f"{server}/reach", json={"port": port}, headers=self._signed(server, "POST", "/reach"))
                if r.status_code == 200:
                    d = r.json()
                    return {"reachable": bool(d.get("reachable")), "source": d.get("source"), "server": server, "why": d.get("why", "")}
                last = f"{server}: {r.status_code} {r.text[:200]}"
            except Exception as e:  # noqa: BLE001
                last = f"{server}: {type(e).__name__}: {e}"
        return {"reachable": None, "error": last}

    async def udp_check(self, timeout: float) -> dict:
        """does UDP get out, and how do I look from outside? Through the first server that offers STUN (GET /info).
        {udp: True|False, mapped, server, why} or {udp: None} when no server offers it. Only for showing: nothing depends on it"""
        for server in self.servers:
            try:
                async with httpx.AsyncClient(timeout=timeout) as hc:
                    port = (await hc.get(f"{server}/info")).json().get("stun_port")
            except Exception:  # noqa: BLE001  (an older server, or not there: try the next)
                continue
            if port:
                return dict(await stun.check(urlsplit(server).hostname, int(port), timeout), server=server)
        return {"udp": None, "mapped": None, "server": None, "why": "no server offers STUN"}

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


async def inside_my_network(host: str, timeout: float = 2.0) -> bool:
    """is this host on my side of the firewall (a private, loopback or link-local address, or a name that resolves only
    to such)? A name that does not resolve here is not: it is somewhere outside"""
    try:
        a = ipaddress.ip_address(host.strip("[]"))
        return not a.is_global
    except ValueError:
        pass
    try:
        infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout)
        addresses = {i[4][0].split("%")[0] for i in infos}
        return bool(addresses) and all(not ipaddress.ip_address(x).is_global for x in addresses)
    except (OSError, asyncio.TimeoutError, ValueError):
        return False


def origin(url: str) -> tuple:
    """(scheme, host, port) of a URL, the port filled in from the scheme"""
    u = urlsplit(url)
    return u.scheme, u.hostname, u.port or {"http": 80, "https": 443}.get(u.scheme)


class OutTransport(httpx.AsyncBaseTransport):
    """an httpx transport for a client behind a firewall: once attached, every call goes through the server's way out,
    a private address too (the address is written as the server sees it: a broker in the server's own network is reached
    by the server). Straight, through `inner`: the servers' own addresses, a server that offers no way out, and the few
    origins named in `straight` while they are inside my own network (a company LLM gateway: the server cannot reach it).
    local: async host -> bool, "is this host inside my network" (replaceable in tests)"""

    def __init__(self, client: TunnelClient, inner: httpx.AsyncBaseTransport | None = None, straight: list[str] | None = None,
                 local=inside_my_network, local_ttl: float = 60.0):
        self.client, self._inner, self.local, self.local_ttl = client, inner, local, local_ttl
        self.straight = {origin(u) for u in straight or [] if u}
        self._known: dict[str, tuple[bool, float]] = {}

    async def _is_local(self, host: str) -> bool:
        now = time.monotonic()
        hit = self._known.get(host)
        if hit and now - hit[1] < self.local_ttl:
            return hit[0]
        v = await self.local(host)
        self._known[host] = (v, now)
        return v

    async def _straight(self, url: str) -> bool:
        o = origin(url)
        return o in self.straight and await self._is_local(o[1])

    @property
    def inner(self) -> httpx.AsyncBaseTransport:
        if self._inner is None:
            self._inner = httpx.AsyncHTTPTransport()
        return self._inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not self.client.out_ok or self.client.is_server(str(request.url)) or await self._straight(str(request.url)):
            return await self.inner.handle_async_request(request)
        body = await request.aread()
        wait = (request.extensions.get("timeout") or {}).get("read")
        try:
            status, headers, content = await self.client.out(request.method, str(request.url), dict(request.headers), body,
                                                              timeout=(wait or 60.0) + 5.0)
        except OutRefused as e:
            raise httpx.ConnectError(f"way out refused: {e}", request=request) from None
        except httpx.HTTPError as e:
            raise httpx.ConnectError(f"cannot reach the way out: {type(e).__name__}", request=request) from None
        return httpx.Response(status, headers=headers, content=content, request=request)

    async def aclose(self) -> None:
        if self._inner is not None:
            await self._inner.aclose()
