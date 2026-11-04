"""The console's local web: the owner API (the desk's use cases) plus the conversation. Every /api path needs the token."""
from __future__ import annotations

import os

from starlette.responses import JSONResponse
from starlette.routing import Route

from ..desk_web.api import build_owner_api
from ..web_api import read_body

STATIC = os.path.join(os.path.dirname(__file__), "static")


def build_console_api(console, token: str, static_dir: str = STATIC):
    service = console.service

    async def say(r):
        b = await read_body(r)
        out = await service.say(r.path_params["event_id"], b.get("to", ""), b.get("text", ""))
        return JSONResponse(out, status_code=200 if out.get("ok", True) and not out.get("error") else 400)

    async def tell(r):
        if not console.agent_available():
            return JSONResponse({"ok": False, "error": "이 peer에는 LLM이 없어 agent에게 지시할 수 없다"}, status_code=400)
        out = await service.tell(r.path_params["event_id"], (await read_body(r)).get("text", ""))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    async def agent_feed(_):
        return JSONResponse(console.agent_feed())

    async def agent_say(r):
        if not console.agent_available():
            return JSONResponse({"ok": False, "error": "이 peer에는 LLM이 없다"}, status_code=400)
        return JSONResponse({"ok": True, "messages": await console.agent_say((await read_body(r)).get("text", ""))})

    return build_owner_api(service, token, static_dir, routes=[
        Route("/api/events/{event_id}/say", say, methods=["POST"]),
        Route("/api/events/{event_id}/tell", tell, methods=["POST"]),
        Route("/api/agent", agent_feed),
        Route("/api/agent/say", agent_say, methods=["POST"]),
    ])
