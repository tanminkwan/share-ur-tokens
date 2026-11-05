"""The observer's local web: read-only. Every /api path needs the token."""
from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..web_api import screen_routes, token_guard

STATIC = os.path.join(os.path.dirname(__file__), "static")


def build_observer_api(observer, token: str, static_dir: str = STATIC) -> Starlette:
    guarded = token_guard(token)

    async def config(_):
        return JSONResponse(observer.config())

    async def state(_):
        return JSONResponse({"me": observer.me()})

    async def snapshot(_):
        return JSONResponse(await observer.view())

    return Starlette(routes=[
        Route("/api/config", guarded(config)),
        Route("/api/state", guarded(state)),
        Route("/api/snapshot", guarded(snapshot)),
        *screen_routes(static_dir),
    ])
