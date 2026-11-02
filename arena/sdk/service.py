"""Service receipts (P6-A2): every answer of an API-providing peer carries a receipt signed by the service, so the caller
can later prove "this service gave this result for this request". Shared by the service peer and its callers."""
from __future__ import annotations

from ..crypto import canon, h, verify

SIGNING_FIELDS = ("sig", "pub", "ts")  # fields a signed message adds; not part of what was asked


def request_hash(request: dict) -> str:
    return h(canon({k: v for k, v in request.items() if k not in SIGNING_FIELDS}))


def make_receipt(service_pub: str, op: str, request: dict, result, ts: float) -> dict:
    return {"service": service_pub, "op": op, "request_hash": request_hash(request), "result_hash": h(canon(result)), "ts": ts}


def verify_service_receipt(reply: dict, request: dict, expected_pub: str) -> str | None:
    """None when reply carries a receipt the expected service signed for exactly this request and this result"""
    rc, sig = reply.get("receipt"), reply.get("receipt_sig", "")
    if not isinstance(rc, dict):
        return "no receipt"
    if rc.get("service") != expected_pub or not verify(expected_pub, rc, sig):
        return "receipt not signed by this service"
    if rc.get("op") != request.get("op") or rc.get("request_hash") != request_hash(request):
        return "receipt is for another request"
    if rc.get("result_hash") != h(canon(reply.get("result"))):
        return "receipt is for another result"
    return None
