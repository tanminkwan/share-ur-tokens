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

from .service import ConnectivityService, Refused
from .signing import SignatureError, verify_headers

KEY = re.compile(r"^[0-9a-f]{64}$")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
       "host", "content-length"}  # never passed: they belong to one hop, or are recomputed


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


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
        return JSONResponse({"ok": True, "base": f"{s.base_url}/r/{key}",
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

    async def health(_):
        return JSONResponse(svc.health())

    return Starlette(routes=[
        Route("/health", health),
        Route("/poll", poll),
        Route("/reply/{request_id}", reply, methods=["POST"]),
        Route("/r/{key}/{path:path}", tunnel, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]),
    ])
