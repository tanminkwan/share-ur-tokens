"""Signed HTTP requests: three headers prove who is calling and when. Shared by clients and servers.

    headers = sign_request(identity, "GET", "/chain")
    pub = verify_request(headers, "GET", "/chain", now=time.time(), window=settings.sig_window_sec)

Signed payload: {"op": "<METHOD> <PATH>", "ts": <epoch seconds>}.
"""
from __future__ import annotations

import time

from .crypto import Identity, verify

H_PUB, H_TS, H_SIG = "X-Arena-Pub", "X-Arena-Ts", "X-Arena-Sig"


class SignatureError(Exception):
    pass


def _target(method: str, path: str, ts: float) -> dict:
    return {"op": f"{method.upper()} {path}", "ts": ts}


def sign_request(identity: Identity, method: str, path: str, now: float | None = None) -> dict:
    ts = time.time() if now is None else now
    return {H_PUB: identity.pub, H_TS: repr(float(ts)), H_SIG: identity.sign(_target(method, path, float(ts)))}


def verify_request(headers, method: str, path: str, now: float, window: float) -> str:
    """return the caller's public key, or raise SignatureError"""
    get = headers.get
    pub, ts_raw, sig = get(H_PUB) or get(H_PUB.lower()), get(H_TS) or get(H_TS.lower()), get(H_SIG) or get(H_SIG.lower())
    if not pub or not ts_raw or not sig:
        raise SignatureError("signed request required (X-Arena-Pub, X-Arena-Ts, X-Arena-Sig)")
    try:
        ts = float(ts_raw)
    except ValueError:
        raise SignatureError("bad timestamp") from None
    if abs(now - ts) > window:
        raise SignatureError("request timestamp outside the allowed window")
    if not verify(pub, _target(method, path, ts), sig):
        raise SignatureError("bad request signature")
    return pub


def sign_message(identity: Identity, op: str, now: float | None = None) -> dict:
    """fields to merge into an A2A message so the receiver knows who sent it and when"""
    ts = float(time.time() if now is None else now)
    return {"pub": identity.pub, "ts": ts, "sig": identity.sign({"op": op, "ts": ts})}


def verify_message(msg: dict, now: float, window: float) -> str:
    """public key of a signed A2A message, or raise SignatureError"""
    pub, ts, sig = msg.get("pub"), msg.get("ts"), msg.get("sig")
    if not pub or ts is None or not sig:
        raise SignatureError("signed message required (pub, ts, sig)")
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        raise SignatureError("bad timestamp") from None
    if abs(now - ts) > window:
        raise SignatureError("message timestamp outside the allowed window")
    if not verify(pub, {"op": msg.get("op"), "ts": ts}, sig):
        raise SignatureError("bad message signature")
    return pub
