"""What every window's local web API does the same way: the token check on /api paths, reading a JSON body, the screen's
own files and the shared ones (/common: the DOM builder, the token reader)."""
from __future__ import annotations

import hmac
import os

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

COMMON = os.path.join(os.path.dirname(__file__), "common_static")


def token_guard(token: str):
    def guarded(fn):
        async def wrap(r: Request):
            if not hmac.compare_digest(r.headers.get("authorization", ""), f"Bearer {token}"):
                return JSONResponse({"ok": False, "error": "token required"}, status_code=401)
            return await fn(r)
        return wrap
    return guarded


async def read_body(r: Request) -> dict:
    try:
        d = await r.json()
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


NO_CACHE = {"Cache-Control": "no-cache"}  # the browser asks again every time (a cheap 304 when the file is unchanged), so a new version shows at once


class FreshFiles(StaticFiles):
    """static files the browser must revalidate: without this a plain refresh may keep an old script after the peer is updated"""

    def file_response(self, *args, **kw):
        r = super().file_response(*args, **kw)
        r.headers.update(NO_CACHE)
        return r


def screen_routes(static_dir: str) -> list:
    """/ (the window's page), /static (its files), /common (the shared files)"""
    async def index(_):
        return FileResponse(os.path.join(static_dir, "index.html"), headers=NO_CACHE)
    return [Route("/", index), Mount("/static", FreshFiles(directory=static_dir)), Mount("/common", FreshFiles(directory=COMMON))]
