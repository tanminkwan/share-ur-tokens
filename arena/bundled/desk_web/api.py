"""The owner API (P6-P5): HTTP only. Every /api path needs `Authorization: Bearer <token>`; the screen's static files are
served at /. Open it on the peer's own machine (127.0.0.1 by default)."""
from __future__ import annotations

import hmac
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..owner_service import OwnerService

STATIC = os.path.join(os.path.dirname(__file__), "static")


def build_owner_api(service: OwnerService, token: str, static_dir: str = STATIC) -> Starlette:
    def authorized(r: Request) -> bool:
        got = r.headers.get("authorization", "")
        return hmac.compare_digest(got, f"Bearer {token}")

    def guarded(fn):
        async def wrap(r: Request):
            if not authorized(r):
                return JSONResponse({"ok": False, "error": "token required"}, status_code=401)
            return await fn(r)
        return wrap

    async def body(r: Request) -> dict:
        try:
            d = await r.json()
        except ValueError:
            return {}
        return d if isinstance(d, dict) else {}

    async def config(_):
        return JSONResponse(service.config())

    async def state(_):
        return JSONResponse(service.state())

    async def items(r):
        return JSONResponse({"items": service.items(r.query_params.get("status", "open"))})

    async def answer(r):
        out = service.answer(r.path_params["item_id"], await body(r))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    async def event(r):
        d = service.event(r.path_params["event_id"])
        return JSONResponse(d if d else {"ok": False, "error": "모르는 이벤트"}, status_code=200 if d else 404)

    async def drive(r):
        out = service.set_drive(r.path_params["event_id"], (await body(r)).get("drive", ""))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    async def tool(r):
        out = await service.run_tool(r.path_params["event_id"], r.path_params["name"], (await body(r)).get("args") or {})
        return JSONResponse(out)

    async def host(r):
        out = await service.host(await body(r))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    async def index(_):
        return FileResponse(os.path.join(static_dir, "index.html"))

    return Starlette(routes=[
        Route("/", index),
        Route("/api/config", guarded(config)),
        Route("/api/state", guarded(state)),
        Route("/api/items", guarded(items)),
        Route("/api/items/{item_id}/answer", guarded(answer), methods=["POST"]),
        Route("/api/events", guarded(host), methods=["POST"]),
        Route("/api/events/{event_id}", guarded(event)),
        Route("/api/events/{event_id}/drive", guarded(drive), methods=["POST"]),
        Route("/api/events/{event_id}/tools/{name}", guarded(tool), methods=["POST"]),
        Mount("/static", StaticFiles(directory=static_dir)),
    ])
