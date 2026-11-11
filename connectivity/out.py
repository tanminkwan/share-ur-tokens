"""The way out (dev/phase10/out-gateway.md): for a signed key, send one HTTP request to a URL it names and give back the answer.
A general HTTP forward; it knows no protocol of anything that uses it.

The server must not become a way into a private network (SSRF): only http(s) without credentials, the name is resolved here
and every address it gives must be public (or in a range the operator allowed), and the connection is made to the address
that was checked, not to the name again. Redirects are not followed, cookies and hop-by-hop headers do not pass, the
answer is cut off at a size limit, and each key has its own rate and number in flight."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time

import httpx

from .service import RateLimit

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
       "host", "content-length"}  # never passed: they belong to one hop, or are recomputed
METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
DEFAULT_PORT = {"http": 80, "https": 443}


class OutError(Exception):
    def __init__(self, status: int, why: str, message: str):
        super().__init__(message)
        self.status, self.why, self.message = status, why, message


async def system_resolve(host: str) -> list[str]:
    """every address the system gives for a name"""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


def address_allowed(ip: str, allow: list[str]) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:  # ::ffff:10.0.0.1 is 10.0.0.1
        a = a.ipv4_mapped
    if any(a in ipaddress.ip_network(c, strict=False) for c in allow):
        return True
    return a.is_global


class OutGateway:
    def __init__(self, settings, resolve=system_resolve, transport: httpx.AsyncBaseTransport | None = None, clock=time.time):
        self.s, self.resolve, self.transport = settings, resolve, transport
        self.limit = RateLimit(settings.out_rate_per_sec, clock)
        self.inflight: dict[str, int] = {}
        self.drop = {h.lower() for h in settings.drop_headers}

    async def _target(self, url: str) -> tuple[str, str, int, str, str]:
        """(scheme, host, port, the address to connect to, path and query) or OutError"""
        bad = lambda why: OutError(403, "bad_target", why)
        try:
            u = httpx.URL(url)
        except httpx.InvalidURL:
            raise bad("not a URL") from None
        if u.scheme not in DEFAULT_PORT or not u.host:
            raise bad("only http and https URLs")
        if u.userinfo:
            raise bad("no credentials in the URL")
        port = u.port or DEFAULT_PORT[u.scheme]
        if self.s.out_ports and port not in self.s.out_ports:
            raise bad("this port is not allowed")
        try:
            addresses = await asyncio.wait_for(self.resolve(u.host), self.s.out_timeout_sec)
        except (OSError, asyncio.TimeoutError):
            raise OutError(502, "unreachable", "the name does not resolve") from None
        if not addresses or not all(address_allowed(a, self.s.out_allow) for a in addresses):
            raise bad("not a public address")
        return u.scheme, u.host, port, addresses[0], u.raw_path.decode("ascii")

    async def forward(self, key: str, url: str, method: str, headers: dict, body: bytes):
        """(status, headers, body) of the answer, or OutError"""
        if not self.limit.allow(key):
            raise OutError(429, "out_rate", "too many requests")
        if self.inflight.get(key, 0) >= self.s.out_max_inflight:
            raise OutError(429, "out_inflight", "too many requests in flight for this key")
        self.inflight[key] = self.inflight.get(key, 0) + 1
        try:
            scheme, host, port, ip, path = await self._target(url)
            shown = f"[{ip}]" if ":" in ip else ip
            default = port == DEFAULT_PORT[scheme]
            send = {k: v for k, v in headers.items() if k.lower() not in HOP and k.lower() not in self.drop}
            send["Host"] = host if default else f"{host}:{port}"
            request = httpx.Request(method, f"{scheme}://{shown}:{port}{path}", headers=send, content=body, extensions={"sni_hostname": host})
            return await asyncio.wait_for(self._send(request), self.s.out_timeout_sec)
        except asyncio.TimeoutError:
            raise OutError(504, "out_timeout", "no answer in time") from None
        finally:
            self.inflight[key] -= 1
            if not self.inflight[key]:
                del self.inflight[key]

    async def _send(self, request: httpx.Request):
        limit = self.s.max_body_bytes
        try:
            async with httpx.AsyncClient(transport=self.transport or httpx.AsyncHTTPTransport(), timeout=self.s.out_timeout_sec,
                                         trust_env=False, follow_redirects=False) as hc:
                async with hc.stream(request.method, request.url, headers=request.headers, content=request.content,
                                     extensions=request.extensions) as r:
                    out = b""
                    async for chunk in r.aiter_bytes():
                        out += chunk
                        if len(out) > limit:
                            raise OutError(502, "big_answer", "the answer is too large")
                    gone = HOP | {"content-encoding"} | self.drop  # the body was decoded here, so it is passed plain
                    return r.status_code, {k: v for k, v in r.headers.items() if k.lower() not in gone}, out
        except httpx.TimeoutException:
            raise OutError(504, "out_timeout", "no answer in time") from None
        except httpx.HTTPError as e:
            raise OutError(502, "unreachable", f"{type(e).__name__}") from None
