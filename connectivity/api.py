"""HTTP of the connectivity server (dev/phase10/design.md 4). Only translation: request -> service call -> response.
The tunnel path /r/<key>/... is open to anyone (what is inside is for the attached server to judge); /poll and /reply
are signed by the attached key."""
from __future__ import annotations

import base64
import json
import re

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .out import HOP, METHODS, OutError
from .reach import CheckLimit, probe, source_allowed
from .service import ConnectivityService, Refused
from .signing import H_SIG, SignatureError, verify_headers

KEY = re.compile(r"^[0-9a-f]{64}$")


def _err(status: int, message: str, why: str | None = None) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, **({"why": why} if why else {})}, status_code=status)


def _pass(headers, drop: set) -> dict:
    return {k.lower(): v for k, v in headers.items() if k.lower() not in HOP and k.lower() not in drop}


def build_connectivity_app(svc: ConnectivityService) -> Starlette:
    s = svc.s
    drop = {h.lower() for h in s.drop_headers}

    def who(r: Request) -> str:
        return verify_headers(r.headers, r.method, r.url.path, now=svc.clock(), window=s.sig_window_sec)

    def source(r: Request) -> str:
        fwd = r.headers.get("x-forwarded-for") if s.trust_forwarded else None
        return fwd.split(",")[0].strip() if fwd else (r.client.host if r.client else "?")

    async def poll(r: Request):
        try:
            key = who(r)
            items = await svc.poll(key, float(r.query_params.get("hold", s.poll_hold_sec)))
        except SignatureError as e:
            return _err(401, str(e))
        except ValueError:
            return _err(400, "hold must be a number")
        except Refused as e:
            return _err(e.status, e.message)
        return JSONResponse({"ok": True, "base": f"{s.base_url}/r/{key}" if s.base_url else None,
                             "requests": [dict(t.view(), body=base64.b64encode(t.body).decode("ascii")) for t in items]})

    async def reply(r: Request):
        try:
            key = who(r)
            d = json.loads(await r.body() or b"{}")
            status, body = int(d["status"]), base64.b64decode(d["body"], validate=True)
            headers = d.get("headers") if isinstance(d.get("headers"), dict) else {}
        except SignatureError as e:
            return _err(401, str(e))
        except (ValueError, TypeError, KeyError):
            return _err(400, "body must be JSON {status: int, headers: {}, body: base64}")
        if not 100 <= status <= 599:
            return _err(400, "status out of range")
        ok = svc.reply(key, r.path_params["request_id"], status, _pass(headers, drop), body)
        return JSONResponse({"ok": ok}, status_code=200 if ok else 404)

    async def tunnel(r: Request):
        key, path = r.path_params["key"], "/" + r.path_params["path"]
        if not KEY.match(key) or (s.paths and path not in s.paths):
            return _err(404, "not found")
        too_big = lambda: _err(413, svc.refuse(413, "big_request", "request body too large").message)
        if int(r.headers.get("content-length") or 0) > s.max_body_bytes:
            return too_big()
        body = b""
        async for chunk in r.stream():
            body += chunk
            if len(body) > s.max_body_bytes:
                return too_big()
        try:
            status, headers, out = await svc.relay(source(r), key, r.method, path, r.url.query, _pass(r.headers, drop), body)
        except Refused as e:
            return _err(e.status, e.message)
        return Response(out, status_code=status, headers=headers)

    checks = CheckLimit(s.check_per_hour, svc.clock)

    async def reach(r: Request):
        """can the caller be reached from outside at its port? the answer names the source address seen"""
        try:
            key = who(r)
            port = int(json.loads(await r.body() or b"{}")["port"])
        except SignatureError as e:
            return _err(401, str(e))
        except (ValueError, TypeError, KeyError):
            return _err(400, "body must be JSON {port: int}")
        if not 1024 <= port <= 65535:
            return _err(400, "port must be 1024..65535")
        if not checks.allow(key):
            return _err(429, svc.refuse(429, "checks", "too many checks for this key").message)
        ip = source(r)
        if not source_allowed(ip, s.probe_allow):
            return JSONResponse({"ok": True, "reachable": False, "source": ip, "why": "source address is not public"})
        ok = await probe(ip, port, key, s.reach_timeout_sec)
        return JSONResponse({"ok": True, "reachable": ok, "source": ip, "why": "" if ok else "no signed answer at that port"})

    async def out(r: Request):
        """send one request for a signed key to the URL it names (dev/phase10/out-gateway.md)"""
        def refused(status, why, message):
            return _err(status, svc.refuse(status, why, message).message, why)
        if not s.out_enabled:
            return refused(403, "out_off", "the way out is off on this server")
        raw = b""
        async for chunk in r.stream():
            raw += chunk
            if len(raw) > 2 * s.max_body_bytes + 65536:  # the body is base64 inside JSON, with headers around it
                return refused(413, "big_request", "request too large")
        try:
            key = verify_headers(r.headers, r.method, r.url.path, now=svc.clock(), window=s.sig_window_sec, body=raw)
        except SignatureError as e:
            return _err(401, str(e))
        if not svc.take_signature(r.headers.get(H_SIG) or ""):
            return _err(401, "this signature was already used")
        if svc.allow_keys is not None and key not in svc.allow_keys:
            return refused(403, "not_allowed", "this key may not use the way out")
        try:
            d = json.loads(raw)
            url, method = d["url"], str(d["method"]).upper()
            headers = {str(k): str(v) for k, v in (d.get("headers") or {}).items()}
            body = base64.b64decode(d.get("body") or "", validate=True)
            if not isinstance(url, str) or method not in METHODS:
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            return _err(400, "body must be JSON {url, method, headers: {}, body: base64}")
        if len(body) > s.max_body_bytes:
            return refused(413, "big_request", "request body too large")
        try:
            status, out_headers, out_body = await svc.out.forward(key, url, method, headers, body)
        except OutError as e:
            return refused(e.status, e.why, e.message)
        svc.out_calls += 1
        svc.out_bytes += len(body) + len(out_body)
        return JSONResponse({"ok": True, "status": status, "headers": out_headers, "body": base64.b64encode(out_body).decode("ascii")})

    async def health(_):
        return JSONResponse(svc.health())

    async def info(_):
        """what a client may use besides HTTP: the STUN port (UDP, on this host) or null; whether the way out (/out) is on"""
        return JSONResponse({"ok": True, "stun_port": s.stun_port or None, "out": bool(s.out_enabled)})

    return Starlette(routes=[
        Route("/health", health),
        Route("/info", info),
        Route("/poll", poll),
        Route("/reply/{request_id}", reply, methods=["POST"]),
        Route("/reach", reach, methods=["POST"]),
        Route("/out", out, methods=["POST"]),
        Route("/r/{key}/{path:path}", tunnel, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]),
    ])
