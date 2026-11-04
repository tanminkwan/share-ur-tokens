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
