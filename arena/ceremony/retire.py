"""The retirement declaration after the ceremony (P8-C2 .. C5, design.md 3.3, 3.5, 5): the witnesses sign it, one of
them records its hash on the ledger (publish + purpose retirement), anyone verifies it against a recorder's public API.
Saying a key was destroyed cannot be proved by mathematics: the declaration is what the witnesses saw, fixed in time."""
from __future__ import annotations

import os

from . import formats as F


def problems(d: dict, settings) -> str | None:
    return F.declaration_error(d, settings.ceremony_min_witnesses, settings.ledger_free_max_bytes)


async def publish(d: dict, me, recorder, settings) -> dict:
    """one witness records the declaration's hash: only a complete declaration (every named witness signed)"""
    err = problems(d, settings)
    if err:
        return {"ok": False, "error": err}
    if me.pub not in d["body"]["witnesses"]:
        return {"ok": False, "error": "the declaration is recorded by one of its witnesses"}
    p = {"author": me.pub, "content_hash": F.declaration_hash(d), "purpose": "retirement", "group_id": settings.genesis_group_id,
         "ledger_id": d["body"]["ledger_id"], "nonce": os.urandom(8).hex()}
    r = await recorder.record("publish", p, {me.pub: me.sign(p)})
    return {"ok": bool(r.get("ok")), **({"entry": r["hash"], "seq": r["seq"]} if r.get("ok") else {"error": r.get("error")}),
            "content_hash": p["content_hash"]}


async def verify(d: dict, recorder, settings) -> dict:
    """the eight checks of design.md 5, each with its result; ok when all pass. `anchored` says whether the ledger already
    holds the declaration's hash (a correct declaration not yet recorded is told apart from a wrong one)"""
    checks: list[dict] = []

    def check(name: str, why: str | None) -> bool:
        checks.append({"check": name, "ok": why is None, **({"why": why} if why else {})})
        return why is None

    def result(anchored: bool = False) -> dict:
        return {"ok": all(c["ok"] for c in checks) and anchored, "anchored": anchored, "checks": checks}

    if not check("shape and witnesses", problems(d, settings)):
        return result()
    b, dh = d["body"], F.declaration_hash(d)
    health = await recorder.health()
    if not check("same ledger", None if health.get("ledger_id") == b["ledger_id"] else
                 f"this recorder keeps ledger {str(health.get('ledger_id'))[:16]}, not {b['ledger_id'][:16]}"):
        return result()
    trust = await recorder.trust()
    rots = sorted(trust.get("rotations", []), key=lambda e: e["seq"])
    h = next((e for e in rots if e["hash"] == b["handover"]), None)
    why = None
    if h is None:
        why = "no key_rotate with this hash on the ledger"
    elif h["payload"].get("role") != b["role"] or h["payload"].get("old") != b["key"]:
        why = "that key_rotate did not hand this key over"
    elif any(e["seq"] > h["seq"] and e["payload"].get("role") == b["role"] and e["payload"].get("new") == b["key"] for e in rots):
        why = "the key became current again later"
    check("handed over before it went", why)
    head = await recorder.verify(b["head"]["hash"])
    check("head on the ledger", None if head.get("exists") and head.get("seq") == b["head"]["seq"] and head.get("seal_ok")
          else "the named head is not this ledger's entry at that seq")
    found = await recorder.content(dh)
    if not found.get("found"):
        checks.append({"check": "hash on the ledger", "ok": True, "why": "not recorded yet (python -m arena.ceremony publish)"})
        return result(anchored=False)
    check("hash on the ledger", None if found.get("purpose") == "retirement" and found.get("author") in b["witnesses"]
          else "recorded, but not as a retirement by one of its witnesses")
    return result(anchored=True)
