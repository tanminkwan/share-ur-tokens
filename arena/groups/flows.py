"""The founder's steps for a broker group (P6-N1, N3). The founder holds the key the group's brokers name as founder.

- declare: the group lives on its brokers alone (ledger null), or a new version (e.g. another broker list), keeping an
  attached ledger as it is
- attach: move the declaration onto a ledger as a `group` entry, then post the next version naming that ledger. From then
  on new events are declared there; what was said before is not on the ledger."""
from __future__ import annotations

from ..crypto import Identity
from .decl import group_declaration, ledger_entry_payload


async def _current(broker) -> tuple[dict, dict | None]:
    info = await broker.group()
    if not info.get("ok"):
        raise ValueError(f"the broker did not answer with its group: {info.get('error')}")
    if info.get("genesis"):
        raise ValueError("the genesis group has its ledger from the beginning: nothing to declare")
    return info, info.get("declaration")


async def declare_group(founder: Identity, broker, brokers: list[str] | None = None) -> dict:
    """post the group's declaration: version 1 without a ledger, or the next version (brokers changed, ledger kept)"""
    info, old = await _current(broker)
    if brokers is None:
        brokers = list(old["brokers"]) if old else [(await broker.health())["pub"]]
    decl = group_declaration(info["group_id"], founder.pub, info["closed"], brokers, ver=(old["ver"] + 1) if old else 1,
                             ledger=old["ledger"] if old else None)
    r = await broker.declare_group(founder, decl)
    return {"ok": bool(r.get("ok")), "declaration": decl, **({"error": r["error"]} if not r.get("ok") else {})}


async def attach_ledger(founder: Identity, broker, recorder, recorder_url: str) -> dict:
    """P6-N3: record the declaration on the ledger at recorder_url, then point the broker's declaration at it"""
    info, old = await _current(broker)
    if old is None:
        return {"ok": False, "error": "declare the group first (declare)"}
    if old["ledger"]:
        return {"ok": False, "error": "this group already keeps a ledger", "ledger": old["ledger"]}
    trust = await recorder.trust()
    if not trust.get("ok"):
        return {"ok": False, "error": f"the recorder cannot prove its ledger: {trust.get('error')}"}
    payload = {**ledger_entry_payload(old), "ledger_id": trust["ledger_id"]}
    r = await recorder.record("group", payload, {founder.pub: founder.sign(payload)})
    if not r.get("ok"):
        return {"ok": False, "error": f"the ledger refused the group entry: {r.get('error')}"}
    ledger = {"ledger_id": trust["ledger_id"], "recorder_url": recorder_url, "recorder": trust["recorder"], "entry": r["hash"]}
    decl = group_declaration(old["group_id"], founder.pub, old["closed"], old["brokers"], ver=old["ver"] + 1, ledger=ledger)
    posted = await broker.declare_group(founder, decl)
    if not posted.get("ok"):
        return {"ok": False, "error": f"the broker refused the new declaration: {posted.get('error')}", "entry": r["hash"]}
    return {"ok": True, "declaration": decl, "entry": r["hash"], "receipt": r}


# ---------------- founding a branch group through a sphinx (dev/founding/requirements.md) ----------------
def application(founder: Identity, purpose: str, contact: str, ts: float) -> dict:
    """the signed application: the founder key (the branch's future god) signs it, so the sphinx knows it is theirs"""
    body = {"founder": founder.pub, "purpose": purpose, "contact": contact, "ts": ts}
    return {"op": "sphinx.apply", "application": body, "sig": founder.sign(body)}


async def apply_to_sphinx(founder: Identity, ask, purpose: str, contact: str, now: float) -> dict:
    """ask: one message to the sphinx peer (a2a). The answer comes later: the person behind the sphinx meets you first"""
    return await ask(application(founder, purpose, contact, now))


async def founding_pass(ask, application_id: str, founder: str | None = None) -> dict:
    """where the application stands; a pass that came back is checked here (signature, for this founder)"""
    from ..ledger.founding import pass_error
    r = await ask({"op": "sphinx.status", "application_id": application_id})
    if r.get("ok") and r.get("status") == "passed":
        bad = pass_error(r.get("pass"), founder=founder)
        if bad:
            return {"ok": False, "error": f"the pass does not check out: {bad}"}
    return r
