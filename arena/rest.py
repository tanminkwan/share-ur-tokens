"""The `api` connection method (P6-A8): the platform's REST binding of the same ops a peer answers over A2A.

    POST {url}/ops/{op}   body {"input": ..., other message fields}   headers X-Arena-Group / X-Arena-Event (optional)
    -> the same JSON reply as over A2A (for service peers: result, receipt, receipt_sig)

A peer without an AI agent (an API-only peer) opens only this. RestTransport is the caller's side."""
from __future__ import annotations

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .egress import Egress
from .a2a import H_EVENT, H_GROUP, _dispatch

OPS_PATH = "/ops/{op}"


def build_rest_app(handler) -> Starlette:
    async def op(r: Request):
        try:
            body = await r.json()
        except ValueError:
            return JSONResponse({"ok": False, "error": "JSON body required"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON object required"}, status_code=400)
        msg = {**body, "op": r.path_params["op"]}
        meta = {"group_id": r.headers.get(H_GROUP), "event_id": r.headers.get(H_EVENT), "context_id": None}
        try:
            return JSONResponse(await _dispatch(handler, msg, meta))
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return Starlette(routes=[Route(OPS_PATH, op, methods=["POST"])])


class RestTransport:
    def __init__(self, settings, http: httpx.AsyncClient | None = None):
        self.timeout, self._http = settings.http_timeout_sec, http
        self.egress = Egress()  # how calls leave (arena/egress.py); a peer hands its own one in

    async def call(self, url: str, msg: dict, timeout: float | None = None, meta: dict | None = None) -> dict:
        meta = meta or {}
        headers = {k: v for k, v in ((H_GROUP, meta.get("group_id")), (H_EVENT, meta.get("event_id"))) if v}
        target = url.rstrip("/") + OPS_PATH.format(op=msg["op"])
        body = {k: v for k, v in msg.items() if k != "op"}
        if self._http is not None:
            r = await self._http.post(target, json=body, headers=headers)
        else:
            async with self.egress.client(timeout=timeout or self.timeout) as hc:
                r = await hc.post(target, json=body, headers=headers)
        return r.json()
