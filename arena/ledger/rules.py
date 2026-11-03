"""Generic rules every entry passes, in order, then the entry type's own rules."""
from __future__ import annotations

from ..crypto import verify
from .elements import element_rules
from .purposes import check_purpose
from .types import ENTRY_TYPES, closed_events, events, groups, published


def signers(e: dict) -> list:
    return ENTRY_TYPES[e["type"]].signers(e["payload"])


def r_type(chain, e, now, s):
    if e["type"] not in ENTRY_TYPES:
        return "unknown type"


def r_prev(chain, e, now, s):
    head = chain[-1]["hash"] if chain else "0" * 64
    if e["prev"] != head:
        return "bad prev hash"


def r_group(chain, e, now, s):
    """every entry names the broker group it happened in; the ledger starts with the genesis; groups are declared once"""
    p = e["payload"]
    gid = p.get("group_id")
    if not isinstance(gid, str) or not gid:
        return "group_id required"
    if e["type"] == "genesis":
        if gid != s.genesis_group_id:
            return "the genesis creates the genesis group"
        if chain:
            return "the genesis happens once, as the first entry"
        return None
    if s.recorder_require_group and (not chain or chain[0]["type"] != "genesis"):
        return "the ledger starts with the genesis"
    if e["type"] == "group":
        if gid == s.genesis_group_id:
            return "the genesis group exists from the beginning and cannot be declared"
        if not isinstance(p.get("closed"), bool) or not isinstance(p.get("brokers", []), list) or not p.get("founder"):
            return "bad group declaration"
        if gid in groups(chain):
            return "group already declared"
    elif s.recorder_require_group and gid != s.genesis_group_id and gid not in groups(chain):
        return f"unknown group: {gid}"


def r_ledger_id(chain, e, now, s):
    """in a ledger begun by a genesis, every later payload names this ledger (its genesis hash), inside what is signed"""
    if not getattr(s, "recorder_require_ledger_id", False) or not chain or chain[0]["type"] != "genesis":
        return None
    if e["payload"].get("ledger_id") != chain[0]["hash"]:
        return "ledger_id missing or not this ledger's (the genesis hash)"


def r_shape(chain, e, now, s):
    t = ENTRY_TYPES[e["type"]]
    return t.shape(chain, e, now, s) if t.shape else None


def r_purpose(chain, e, now, s):
    """a coded purpose must be a registered code, declared on a type it is for (arena/ledger/purposes.py)"""
    return check_purpose(chain, e)


def r_signatures(chain, e, now, s):
    for who in signers(e):
        sig = e["sigs"].get(who) if who else None
        if not who or not sig or not verify(who, e.get("signed_payload", e["payload"]), sig):  # signatures are on the public body
            return f"missing/invalid signature of {str(who)[:8]}"


def r_time(chain, e, now, s):
    if chain and e["ts"] < chain[-1]["ts"]:
        return "timestamp goes backwards"


def r_event_ref(chain, e, now, s):
    """an entry that names an event must name a declared one that is still open"""
    mode, ev = ENTRY_TYPES[e["type"]].event_ref, e["payload"].get("event_id")
    if mode == "required" or (mode == "optional" and ev is not None):
        if ev not in events(chain):
            return "unknown event"
        if ev in closed_events(chain):
            return "event closed"


def r_known_content(chain, e, now, s):
    if ENTRY_TYPES[e["type"]].needs_content and e["payload"].get("content_hash") not in published(chain):
        return "unknown content"


def r_nonce(chain, e, now, s):
    if ENTRY_TYPES[e["type"]].unique_nonce and any(
            x["type"] == e["type"] and x["payload"].get("nonce") == e["payload"].get("nonce") for x in chain):
        return "replay (nonce already used)"


GENERIC = (r_type, r_prev, r_group, r_ledger_id, r_shape, r_purpose, r_signatures, r_time, r_event_ref, r_known_content, r_nonce)


def check(chain: list[dict], e: dict, now: float, settings) -> str | None:
    for rule in GENERIC:
        err = rule(chain, e, now, settings)
        if err:
            return err
    for rule in ENTRY_TYPES[e["type"]].rules:
        err = rule(chain, e, now, settings)
        if err:
            return err
    ev = e["payload"].get("event_id")
    if ev is not None and e["type"] != "event" and ev in events(chain):
        return element_rules(chain, e, events(chain)[ev], settings)  # the elements this event switched on
    return None
