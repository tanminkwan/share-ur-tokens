"""A broker group's declaration (P6-N1, user 2026-11-02: "non-recorder 모드로 broker group 단위로 사용도 가능할 수 있겠다").

A group can live on brokers alone. Its founder signs one declaration and the group's brokers keep it:

    {group_id, founder, closed, brokers, ver, ledger}        signed by the founder

`ledger` is null for a group without a ledger. Attaching one later (P6-N3) records the same declaration on a ledger as a
`group` entry and posts the next version with ledger = {ledger_id, recorder_url, recorder, entry}. A ledger once attached
stays (the same ledger_id; only the recorder's address may move). Shared by the broker (which keeps it) and the peers
(which read it), so it sits below both."""
from __future__ import annotations

import re

HEX64 = re.compile(r"[0-9a-f]{64}")
KEYS = ("group_id", "founder", "closed", "brokers", "ver", "ledger")
LEDGER_KEYS = ("ledger_id", "recorder_url", "recorder", "entry")


def group_declaration(group_id: str, founder: str, closed: bool, brokers: list[str], ver: int = 1, ledger: dict | None = None) -> dict:
    return {"group_id": group_id, "founder": founder, "closed": bool(closed), "brokers": list(brokers), "ver": int(ver),
            "ledger": dict(ledger) if ledger else None}


def ledger_error(x) -> str | None:
    if x is None:
        return None
    if not isinstance(x, dict) or set(x) != set(LEDGER_KEYS):
        return "ledger is null or {ledger_id, recorder_url, recorder, entry}"
    if not all(isinstance(x[k], str) and HEX64.fullmatch(x[k]) for k in ("ledger_id", "recorder", "entry")):
        return "ledger_id, recorder and entry are hex64"
    if not isinstance(x["recorder_url"], str) or not re.match(r"https?://", x["recorder_url"]):
        return "recorder_url is an http(s) address"
    return None


def declaration_error(d) -> str | None:
    """None when the declaration has its exact shape"""
    if not isinstance(d, dict) or set(d) != set(KEYS):
        return "a group declaration is {group_id, founder, closed, brokers, ver, ledger}"
    if not isinstance(d["group_id"], str) or not d["group_id"]:
        return "group_id is a name"
    if not isinstance(d["founder"], str) or not HEX64.fullmatch(d["founder"]):
        return "founder is a public key"
    if not isinstance(d["closed"], bool):
        return "closed is true or false"
    if not isinstance(d["brokers"], list) or not d["brokers"] or not all(isinstance(b, str) and HEX64.fullmatch(b) for b in d["brokers"]):
        return "brokers lists the group's broker keys"
    if not isinstance(d["ver"], int) or isinstance(d["ver"], bool) or d["ver"] < 1:
        return "ver counts from 1"
    return ledger_error(d["ledger"])


def next_error(old: dict | None, new: dict) -> str | None:
    """None when `new` may replace `old` (the same group and founder, a newer version, an attached ledger kept)"""
    if old is None:
        return None
    if new["group_id"] != old["group_id"] or new["founder"] != old["founder"]:
        return "the same group keeps its founder"
    if new["ver"] <= old["ver"]:
        return "older or same version"
    if old["ledger"] and (not new["ledger"] or new["ledger"]["ledger_id"] != old["ledger"]["ledger_id"]):
        return "a ledger once attached stays (the same ledger_id)"
    return None


def ledger_entry_payload(d: dict) -> dict:
    """the `group` entry that moves the declaration onto a ledger (P6-N3)"""
    return {"group_id": d["group_id"], "founder": d["founder"], "closed": d["closed"], "brokers": list(d["brokers"])}
