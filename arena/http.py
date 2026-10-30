"""Starlette plumbing shared by the broker and collector APIs: JSON in/out, error mapping, signed-request check."""
from __future__ import annotations

import json
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse

from .signing import SignatureError, verify_request


class BadRequest(Exception):
    pass


async def read_json(request: Request, *required: str) -> dict:
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise BadRequest("body must be JSON") from None
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    missing = [k for k in required if k not in body]
    if missing:
        raise BadRequest("missing field(s): " + ", ".join(missing))
    return body


def reply(result: dict, fail_status: int = 400) -> JSONResponse:
    """service results are {"ok": bool, ...}; map a failure to an HTTP error code"""
    return JSONResponse(result, status_code=200 if result.get("ok") else fail_status)


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def signed_caller(request: Request, window: float, clock: Callable[[], float]) -> str:
    """public key of a signed request, or raise SignatureError"""
    return verify_request(request.headers, request.method, request.url.path, now=clock(), window=window)


def guarded(handler):
    """turn BadRequest / SignatureError raised in a handler into 400 / 401"""
    async def wrapped(request: Request):
        try:
            return await handler(request)
        except BadRequest as e:
            return error(400, str(e))
        except SignatureError as e:
            return error(401, str(e))
    return wrapped
