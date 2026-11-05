"""HTTP API of the recorder. Only translation: request -> service call -> JSON reply."""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..http import guarded, read_json, reply, signed_caller
from .service import RecorderService


def build_recorder_app(svc: RecorderService) -> Starlette:
    window = svc.settings.sig_window_sec

    async def post_entry(r: Request):
        b = await read_json(r, "type", "payload", "sigs")
        return reply(await svc.record(b["type"], b["payload"], b["sigs"], b.get("private")))

    async def get_entry(r: Request):
        return JSONResponse(svc.verify(r.path_params["hash"]))

    async def audit(_):
        return JSONResponse(svc.audit())

    async def chain(r: Request):
        return reply(svc.read_chain(signed_caller(r, window, svc.clock)), fail_status=403)

    async def access_log(r: Request):
        return reply(svc.read_access_log(signed_caller(r, window, svc.clock)), fail_status=403)

    async def track(r: Request):
        return reply(svc.track(r.path_params["pub"]), fail_status=404)

    async def event_entries(r: Request):
        return reply(svc.event_entries(r.path_params["event_id"]), fail_status=404)

    async def trust(_):
        return reply(svc.trust(), fail_status=404)

    async def content(r: Request):
        return reply(svc.content(r.path_params["content_hash"]), fail_status=404)

    async def key(r: Request):
        return reply(svc.key(r.path_params["pub"]), fail_status=404)

    async def delegates(_):
        return reply(svc.delegates())

    async def link(r: Request):
        return reply(svc.link(r.path_params["ledger_id"]), fail_status=404)

    async def log(r: Request):
        try:
            start, limit = int(r.query_params.get("from", 0)), r.query_params.get("limit")
            limit = int(limit) if limit else None
        except ValueError:
            return JSONResponse({"ok": False, "error": "from and limit are numbers"}, status_code=400)
        return JSONResponse(svc.log(start, limit))

    async def codes(_):
        return JSONResponse(svc.codes())

    async def codebooks(_):
        return JSONResponse(svc.codebooks())

    async def health(_):
        return JSONResponse(svc.health())

    return Starlette(routes=[
        Route("/entries", guarded(post_entry), methods=["POST"]),
        Route("/entries/{hash}", guarded(get_entry), methods=["GET"]),
        Route("/audit", guarded(audit), methods=["GET"]),
        Route("/chain", guarded(chain), methods=["GET"]),
        Route("/access-log", guarded(access_log), methods=["GET"]),
        Route("/track/{pub}", guarded(track), methods=["GET"]),
        Route("/events/{event_id}", guarded(event_entries), methods=["GET"]),
        Route("/trust", guarded(trust), methods=["GET"]),
        Route("/links/{ledger_id}", guarded(link), methods=["GET"]),
        Route("/delegates", guarded(delegates), methods=["GET"]),
        Route("/key/{pub}", guarded(key), methods=["GET"]),
        Route("/content/{content_hash}", guarded(content), methods=["GET"]),
        Route("/codes", guarded(codes), methods=["GET"]),
        Route("/log", guarded(log), methods=["GET"]),
        Route("/codebooks", guarded(codebooks), methods=["GET"]),
        Route("/health", guarded(health), methods=["GET"]),
    ])
