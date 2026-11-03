"""The chat app's local web: HTTP only, every /api path needs the token (like the owner desk)."""
from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..web_api import read_body, screen_routes, token_guard

STATIC = os.path.join(os.path.dirname(__file__), "static")


def build_chat_api(chat, token: str, static_dir: str = STATIC) -> Starlette:
    guarded = token_guard(token)

    async def feed(_):
        return JSONResponse(chat.feed())

    async def say(r):
        return JSONResponse({"ok": True, "messages": await chat.say((await read_body(r)).get("text", ""))})

    async def answer(r):
        out = chat.service.answer(r.path_params["item_id"], await read_body(r))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    return Starlette(routes=[
        Route("/api/feed", guarded(feed)),
        Route("/api/say", guarded(say), methods=["POST"]),
        Route("/api/items/{item_id}/answer", guarded(answer), methods=["POST"]),
        *screen_routes(static_dir),
    ])
