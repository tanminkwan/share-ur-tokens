"""HTTP API of the broker. Only translation: request -> service call -> JSON reply."""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..http import error, guarded, read_json, reply, signed_caller
from ..signing import H_PUB
from .neighbors import Caller
from .service import BrokerService

GROUP_ONLY = "members of this peer group only"
NEED_PROFILE = "signed request from a registered profile required"


def build_broker_app(svc: BrokerService) -> Starlette:
    window = svc.settings.sig_window_sec

    def caller(r: Request) -> Caller:
        """optional signature: verified if present (401 if bad), anonymous if absent"""
        if H_PUB not in r.headers and H_PUB.lower() not in r.headers:
            return Caller.anonymous()
        pub = signed_caller(r, window, svc.clock)
        return Caller(pub, {k: v for k, v in r.headers.items() if k.lower().startswith("x-arena-")})

    def flag(r: Request, name: str) -> bool:
        return r.query_params.get(name, "") in ("1", "true", "yes")

    async def post_profile(r: Request):
        b = await read_json(r, "pub", "profile", "sig")
        return reply(await svc.advertise(b))

    async def get_profiles(r: Request):
        out = await svc.list_profiles(caller(r), local=flag(r, "local"))
        return error(403, GROUP_ONLY) if out is None else JSONResponse({"ok": True, "profiles": out})

    async def search_profiles(r: Request):
        qp = r.query_params
        k = int(qp["k"]) if qp.get("k", "").isdigit() else None
        out = await svc.find(caller(r), qp.get("q", ""), role=qp.get("role") or None, labels=qp.getlist("label"),
                             exclude=qp.getlist("exclude"), k=k, local=flag(r, "local"))
        return error(403, GROUP_ONLY) if out is None else JSONResponse({"ok": True, "peers": out})

    async def post_notice(r: Request):
        b = await read_json(r, "notice", "sig")
        return reply(await svc.post_notice(b["notice"], b["sig"], shared=bool(b.get("shared"))))

    async def close_notice(r: Request):
        b = await read_json(r, "sig")
        return reply(await svc.close_notice(r.path_params["notice_id"], b["sig"], shared=bool(b.get("shared"))), fail_status=403)

    async def get_notices(r: Request):
        caller = signed_caller(r, window, svc.clock)
        since = r.query_params.get("since")
        if since is not None:
            try:
                ch = await svc.changed_notices(caller, float(since))
            except ValueError:
                return error(400, "since must be a number")
            return error(403, NEED_PROFILE) if ch is None else JSONResponse({"ok": True, **ch})
        out = await svc.visible_notices(caller)
        return error(403, NEED_PROFILE) if out is None else JSONResponse({"ok": True, "notices": out})

    async def search_notices(r: Request):
        qp = r.query_params
        k = int(qp["k"]) if qp.get("k", "").isdigit() else None
        out = await svc.search_notices(signed_caller(r, window, svc.clock), qp.get("q", ""), k=k)
        return error(403, NEED_PROFILE) if out is None else JSONResponse({"ok": True, "hits": out})

    async def post_grant(r: Request):
        b = await read_json(r, "grant", "sig")
        return reply(await svc.grant(b["grant"], b["sig"]), fail_status=403)

    async def health(_):
        return JSONResponse(svc.health())

    return Starlette(routes=[
        Route("/profiles", guarded(post_profile), methods=["POST"]),
        Route("/profiles", guarded(get_profiles), methods=["GET"]),
        Route("/profiles/search", guarded(search_profiles), methods=["GET"]),
        Route("/notices", guarded(post_notice), methods=["POST"]),
        Route("/notices", guarded(get_notices), methods=["GET"]),
        Route("/notices/search", guarded(search_notices), methods=["GET"]),
        Route("/notices/{notice_id}/close", guarded(close_notice), methods=["POST"]),
        Route("/grants", guarded(post_grant), methods=["POST"]),
        Route("/health", guarded(health), methods=["GET"]),
    ])
