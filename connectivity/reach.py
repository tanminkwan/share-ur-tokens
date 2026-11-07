"""Inbound check (dev/phase10/design.md 6): can a server be reached from outside at its own port? The connectivity server
goes back to the address the request came from (never an address the request names), at the one port it was told,
and asks the key to sign a fresh nonce. Private, loopback and link-local sources are not tried unless allowed
(CONNECTIVITY_PROBE_ALLOW), so the service cannot be turned on an internal network."""
from __future__ import annotations

import ipaddress
import secrets
import time
from collections import deque

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.requests import Request
from starlette.responses import JSONResponse

REACH_PATH = "/.well-known/connectivity-reach"


def _what(nonce: str) -> bytes:
    return f"REACH {nonce}".encode()


def source_allowed(ip: str, allow: list[str]) -> bool:
    """a public address, or one inside a range the operator allowed"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if any(a in ipaddress.ip_network(c, strict=False) for c in allow):
        return True
    return a.is_global


async def probe(ip: str, port: int, key_hex: str, timeout: float) -> bool:
    """go back to ip:port and ask for the key's signature on a fresh nonce"""
    nonce = secrets.token_hex(16)
    host = f"[{ip}]" if ":" in ip else ip
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as hc:
            r = await hc.post(f"http://{host}:{port}{REACH_PATH}", json={"nonce": nonce})
        d = r.json()
        if r.status_code != 200 or d.get("key") != key_hex:
            return False
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex)).verify(bytes.fromhex(d.get("sig", "")), _what(nonce))
        return True
    except (httpx.HTTPError, ValueError, InvalidSignature, AttributeError):
        return False


class CheckLimit:
    """at most n checks per key per hour"""

    def __init__(self, per_hour: int, clock=time.time):
        self.n, self.clock, self.seen = per_hour, clock, {}

    def allow(self, key: str) -> bool:
        now, q = self.clock(), self.seen.setdefault(key, deque())
        while q and now - q[0] >= 3600:
            q.popleft()
        if len(q) >= self.n:
            return False
        q.append(now)
        return True


def reach_endpoint(signer, key_hex: str):
    """what the checked side serves at REACH_PATH: its key's signature on the nonce it is given"""
    async def answer(request: Request):
        try:
            nonce = str((await request.json())["nonce"])[:128]
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"ok": False}, status_code=400)
        return JSONResponse({"key": key_hex, "sig": signer(_what(nonce)).hex()})
    return answer
