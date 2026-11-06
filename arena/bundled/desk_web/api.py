"""The owner API (P6-P5): HTTP only. Every /api path needs `Authorization: Bearer <token>`; the screen's static files are
served at /. Open it on the peer's own machine (127.0.0.1 by default)."""
from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..owner_service import OwnerService
from ..web_api import read_body, screen_routes, token_guard

STATIC = os.path.join(os.path.dirname(__file__), "static")


def build_owner_api(service: OwnerService, token: str, static_dir: str = STATIC, routes: list = ()) -> Starlette:
    """routes: more /api routes of a window built on the owner API (they get the same token check)"""
    guarded, body = token_guard(token), read_body

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

    async def nick(r):
        out = await service.set_nick((await body(r)).get("nick", ""))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    async def host(r):
        out = await service.host(await body(r))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    return Starlette(routes=[
        Route("/api/config", guarded(config)),
        Route("/api/state", guarded(state)),
        Route("/api/items", guarded(items)),
        Route("/api/items/{item_id}/answer", guarded(answer), methods=["POST"]),
        Route("/api/nick", guarded(nick), methods=["POST"]),
        Route("/api/events", guarded(host), methods=["POST"]),
        Route("/api/events/{event_id}", guarded(event)),
        Route("/api/events/{event_id}/drive", guarded(drive), methods=["POST"]),
        Route("/api/events/{event_id}/tools/{name}", guarded(tool), methods=["POST"]),
        *[Route(r.path, guarded(r.endpoint), methods=list(r.methods or ["GET"])) for r in routes],
        *screen_routes(static_dir),
    ])
