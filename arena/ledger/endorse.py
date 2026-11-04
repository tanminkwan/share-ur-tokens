"""Endorsement (user 2026-11-04): "결재는 특별한 것이 아니야. event 게시자의 의도로 하는 거야. event의 효력이나 명성을 위한
장치인 거야. 결재로 못 박을 필요 없어", "2가지 선택 옵션이 있다고 하자".

A publisher who wants weight for an event asks other peers to co-sign it, after declaring it alone. Nothing gates the
event; the endorser decides; existing entries never change. Both ways share one signed body, so one endorser signature
serves either:

    body = {event_id, event_hash, issuer, endorser, group_id, ledger_id?}     signed by the issuer and the endorser

- "ledger": an `endorse` entry is appended (the body as its payload). The recorder stamps the time and counts it:
  standing is who endorsed and how many, read from the ledger.
- "signature": the ledger does not grow. The token {format, version, body, sigs} travels with the event's notice;
  anyone checks the two signatures and that event_hash is the declared event (GET /entries/{event_hash})."""
from __future__ import annotations

from ..crypto import verify
from .types import EntryType, _inc, register_entry_type

HOWS = ("ledger", "signature")
FORMAT, VERSION = "arena-endorsement", 1
BODY_KEYS = ("event_id", "event_hash", "issuer", "endorser", "group_id")


def endorsement_body(event_id: str, event_hash: str, issuer: str, endorser: str, group_id: str, ledger_id: str | None = None) -> dict:
    return {"event_id": event_id, "event_hash": event_hash, "issuer": issuer, "endorser": endorser, "group_id": group_id,
            **({"ledger_id": ledger_id} if ledger_id else {})}


def body_error(b) -> str | None:
    if not isinstance(b, dict) or not all(isinstance(b.get(k), str) and b[k] for k in BODY_KEYS):
        return "an endorsement names event_id, event_hash, issuer, endorser and group_id"
    if b["issuer"] == b["endorser"]:
        return "an endorser is someone other than the event's issuer"
    return None


def make_token(body: dict, sigs: dict) -> dict:
    return {"format": FORMAT, "version": VERSION, "body": dict(body), "sigs": dict(sigs)}


def token_error(tok) -> str | None:
    """None when the token is an endorsement both the issuer and the endorser signed (that the event is real is checked
    against the ledger: GET /entries/{event_hash})"""
    if not isinstance(tok, dict) or tok.get("format") != FORMAT or tok.get("version") != VERSION:
        return "not an endorsement token"
    b, sigs = tok.get("body"), tok.get("sigs") or {}
    bad = body_error(b)
    if bad:
        return bad
    for who in (b["issuer"], b["endorser"]):
        if not verify(who, b, sigs.get(who, "")):
            return f"the endorsement lacks the signature of {who[:8]}"
    return None


def _event_entry(chain, event_id):
    return next((x for x in chain if x["type"] == "event" and x["payload"].get("event_id") == event_id), None)


def _shape(chain, e, now, s):
    return body_error(e["payload"])


def _rule(chain, e, now, s):
    p = e["payload"]
    ev = _event_entry(chain, p["event_id"])
    if ev is None or ev["hash"] != p["event_hash"]:
        return "the endorsement names an event that is not declared here (event_id and event_hash)"
    if ev["payload"]["issuer"] != p["issuer"]:
        return "only the event's issuer asks for endorsements"
    if any(x["type"] == "endorse" and x["payload"]["event_id"] == p["event_id"] and x["payload"]["endorser"] == p["endorser"] for x in chain):
        return "this peer already endorsed this event"


def _contribute(rec, p, index):
    _inc(rec, p["endorser"], "endorsements")  # given
    _inc(rec, p["issuer"], "endorsed")        # received for my events


register_entry_type(EntryType(
    "endorse", fields=frozenset({"event_hash", "issuer", "endorser"}), signers=lambda p: [p.get("issuer"), p.get("endorser")],
    shape=_shape, rules=(_rule,),  # no event_ref: an endorsement may come after the event closed (standing)
    public=lambda p, c: {"issuer": p["issuer"], "endorser": p["endorser"], "event_hash": p["event_hash"]},
    counters={"endorsements": 0, "endorsed": 0}, contribute=_contribute))
