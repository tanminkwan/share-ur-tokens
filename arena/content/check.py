"""A reader checks a copy of a work against its ledger reference (CP-9), step by step:

1. body       the copy, made into bytes by the reference's form, hashes to the registered content hash
2. entry      the recorder knows that entry: a publish, sealed, of this content hash, by this author, on this ledger
3. ledger     the ledger is the real one: from the root values (genesis hash, god's first key), following key succession,
              through the trunk's link if it is a branch; and the entry was sealed by the recorder key valid at its seq
              (skipped, and said so, when the reader has no root values)

The time is the recorder's clock: "this body already existed then"."""
from __future__ import annotations

from typing import Callable

from ..ledger.refs import content_hash_of
from ..ledger.trust import keys_at, verify_linked, verify_trust


async def _ledger_proof(recorder, anchor: dict, recorder_of: Callable | None) -> tuple[bool, str, dict]:
    doc = await recorder.trust()
    if not doc.get("ok"):
        return False, f"trust document: {doc.get('error')}", {}
    g = doc["genesis"]
    if g["hash"] == anchor["genesis_hash"]:
        ok, why, _ = verify_trust(doc, anchor["genesis_hash"], anchor["god_pub"])
        return ok, why, doc
    parent = g["payload"].get("parent")
    if not parent or recorder_of is None:
        return False, "this ledger does not start from the root values (and is not a branch linked into them)", doc
    trunk = recorder_of(parent["recorder_url"])
    link = (await trunk.link(doc["ledger_id"])).get("link")
    ok, why, _ = verify_linked(doc, await trunk.trust(), link or {}, anchor["genesis_hash"], anchor["god_pub"])
    return ok, why, doc


async def check_work(data: bytes, ref: dict, recorder, anchor: dict | None = None, recorder_of: Callable | None = None) -> dict:
    """-> {ok, steps: [{step, ok (True, False, or None when skipped), detail}], seq, at, author, ledger_id, purpose}"""
    steps = []

    def step(name, ok, detail=""):
        steps.append({"step": name, "ok": ok, "detail": detail})
    try:
        got = content_hash_of(data, ref["form"])
        step("body", got == ref["content_hash"], "" if got == ref["content_hash"] else f"the copy hashes to {got[:16]}…, not {ref['content_hash'][:16]}…")
    except (ValueError, UnicodeDecodeError) as e:
        step("body", False, f"the copy is not in form {ref['form']}: {e}")
    v = await recorder.verify(ref["entry"])
    wrong = [k for k, ok in (("exists", v.get("exists")), ("type publish", v.get("type") == "publish"), ("seal", v.get("seal_ok")),
                             ("content hash", v.get("content_hash") == ref["content_hash"]), ("author", v.get("author") == ref["author"]),
                             ("ledger", v.get("ledger_id") == ref["ledger_id"])) if not ok]
    step("entry", not wrong, "" if not wrong else "differs: " + ", ".join(wrong))
    if anchor and anchor.get("genesis_hash"):
        ok, why, doc = await _ledger_proof(recorder, anchor, recorder_of)
        if ok and v.get("exists") and keys_at(doc, v["seq"])["recorder"] != v.get("sealed_by"):
            ok, why = False, "the entry was not sealed by the recorder key valid at its position"
        step("ledger", ok, why)
    else:
        step("ledger", None, "skipped: no root values (ARENA_TRUST_GENESIS_HASH, ARENA_TRUST_GOD_PUB) to prove the ledger from")
    return {"ok": all(s["ok"] is not False for s in steps), "steps": steps, "seq": v.get("seq"), "at": v.get("ts"),
            "author": v.get("author"), "ledger_id": v.get("ledger_id"), "purpose": v.get("purpose")}
