"""The chat app's local web: HTTP only, every /api path needs the token (like the owner desk)."""
from __future__ import annotations

import hmac
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

STATIC = os.path.join(os.path.dirname(__file__), "static")


def build_chat_api(chat, token: str, static_dir: str = STATIC) -> Starlette:
    def guarded(fn):
        async def wrap(r: Request):
            if not hmac.compare_digest(r.headers.get("authorization", ""), f"Bearer {token}"):
                return JSONResponse({"ok": False, "error": "token required"}, status_code=401)
            return await fn(r)
        return wrap

    async def body(r: Request) -> dict:
        try:
            d = await r.json()
        except ValueError:
            return {}
        return d if isinstance(d, dict) else {}

    async def feed(_):
        return JSONResponse(chat.feed())

    async def say(r):
        return JSONResponse({"ok": True, "messages": await chat.say((await body(r)).get("text", ""))})

    async def answer(r):
        out = chat.service.answer(r.path_params["item_id"], await body(r))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    async def index(_):
        return FileResponse(os.path.join(static_dir, "index.html"))

    return Starlette(routes=[
        Route("/", index),
        Route("/api/feed", guarded(feed)),
        Route("/api/say", guarded(say), methods=["POST"]),
        Route("/api/items/{item_id}/answer", guarded(answer), methods=["POST"]),
        Mount("/static", StaticFiles(directory=static_dir)),
    ])
