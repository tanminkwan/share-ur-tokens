"""HTTP API of the collector. Only translation: request -> service call -> JSON reply."""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..http import guarded, read_json, reply, signed_caller
from .service import CollectorService


def build_collector_app(svc: CollectorService) -> Starlette:
    window = svc.settings.sig_window_sec

    async def post_entry(r: Request):
        b = await read_json(r, "type", "payload", "sigs")
        return reply(await svc.record(b["type"], b["payload"], b["sigs"]))

    async def get_entry(r: Request):
        return JSONResponse(svc.verify(r.path_params["hash"]))

    async def audit(_):
        return JSONResponse(svc.audit())

    async def chain(r: Request):
        return reply(svc.read_chain(signed_caller(r, window, svc.clock)), fail_status=403)

    async def access_log(r: Request):
        return reply(svc.read_access_log(signed_caller(r, window, svc.clock)), fail_status=403)

    async def health(_):
        return JSONResponse(svc.health())

    return Starlette(routes=[
        Route("/entries", guarded(post_entry), methods=["POST"]),
        Route("/entries/{hash}", guarded(get_entry), methods=["GET"]),
        Route("/audit", guarded(audit), methods=["GET"]),
        Route("/chain", guarded(chain), methods=["GET"]),
        Route("/access-log", guarded(access_log), methods=["GET"]),
        Route("/health", guarded(health), methods=["GET"]),
    ])
