"""Asking for endorsements: the issuer's side (user 2026-11-04: an endorsement is the publisher's own choice, for an
event's weight or standing; "2가지 선택 옵션"). The issuer asks another peer to co-sign its declared event; that peer's
app decides (a person may take their time: the answer may come back pending and be finished later). With the
endorser's signature the issuer either appends an `endorse` entry ("ledger") or makes a token that travels with the
notice ("signature"). The rules and the token: arena/ledger/endorse.py."""
from __future__ import annotations

from ..crypto import verify
from ..ledger.endorse import HOWS, endorsement_body, make_token, token_error


async def ask_endorsement(ctx, *, event_id: str, event_hash: str, recorder_url: str, group_id: str, endorser: str,
                          endorser_url: str | None = None, how: str = "ledger", request: dict | None = None,
                          recorder_pub: str | None = None) -> dict:
    """-> {ok, how, hash | token}, the refusal, or pending (with body and how, to finish later)"""
    if how not in HOWS:
        return {"ok": False, "error": f"how must be one of {', '.join(HOWS)}"}
    body = endorsement_body(event_id, event_hash, ctx.pub, endorser, group_id, await ctx.ledger_id(recorder_url))
    r = await ctx.call_peer(endorser, {"op": "endorse", "body": body, "how": how, "recorder_url": recorder_url, "request": request or {}},
                            group=group_id, event=event_id, url=endorser_url)
    if r.get("pending"):
        return dict(r, body=body, how=how)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    return await finish_endorsement(ctx, body, r["sig"], how, recorder_url, recorder_pub)


async def finish_endorsement(ctx, body: dict, sig: str, how: str, recorder_url: str, recorder_pub: str | None = None) -> dict:
    """the endorser signed: append the entry (its receipt kept if the recorder I trust sealed it), or make the token"""
    if not verify(body["endorser"], body, sig or ""):
        return {"ok": False, "error": "the endorser's signature does not verify"}
    sigs = {ctx.pub: ctx.sign(body), body["endorser"]: sig}
    if how == "signature":
        return {"ok": True, "how": how, "token": make_token(body, sigs)}
    r = await ctx.recorder(recorder_url).record("endorse", body, sigs)
    if r.get("ok"):
        expected = recorder_pub or (await ctx.recorder_trust(recorder_url)).get("recorder")
        ctx.receipts.keep(r, "endorse", body, expected_recorder=expected)
    return {"ok": bool(r.get("ok")), "how": how, "hash": r.get("hash"), **({"error": r["error"]} if not r.get("ok") else {})}


def tokens_of(notice: dict) -> list[dict]:
    """the endorsement tokens a notice carries that check out for this very event (others are left out)"""
    out = []
    for t in notice.get("endorsements") or []:
        b = t.get("body") if isinstance(t, dict) else None
        if token_error(t) is None and b["event_id"] == notice.get("notice_id") and b["event_hash"] == notice.get("event_hash") \
                and b["issuer"] == notice.get("issuer_pub"):
            out.append(t)
    return out
