"""Ledger entry types. Each type is one object: who signs, its own rules, what public verify may show, and how it
counts in contributions. Add a type by registering it; the ledger, the recorder and contributions do not change.
The platform does not know what any role or verdict means: events declare a policy and rules compare strings."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from ..crypto import commit_hash
from ..peer.plugin import valid_run

POLICY_LISTS = ("roles", "conflict_roles", "hidden_roles", "reveal_values")
POLICY_MAPS = ("verdict_roles", "attest_roles")
POLICY_KEYS = set(POLICY_LISTS) | set(POLICY_MAPS)
ISSUER = "issuer"  # policy value meaning "the event issuer" rather than a contracted role

Rule = Callable[[list, dict, float, object], "str | None"]  # (chain, entry, now, settings) -> error or None


@dataclass(frozen=True)
class EntryType:
    name: str
    signers: Callable[[dict], list]                       # payload -> public keys that must sign
    event_ref: str | None = None                          # None | "optional" | "required": may/must name a declared, open event
    needs_content: bool = False                           # refers to a published content hash
    unique_nonce: bool = False                            # payload nonce may be used once per type
    shape: Rule | None = None                             # checked before signatures
    rules: tuple = ()                                     # type rules, after the generic ones
    public: Callable[[dict, list], dict] = lambda p, chain: {}      # what public verify may show besides type/event/group
    counters: dict = field(default_factory=dict)          # contribution fields this type adds, with their empty values
    contribute: Callable[[dict, dict, dict], None] | None = None    # (records, payload, index) -> update records
    index: Callable[[dict, dict], None] | None = None     # (payload, index) -> first pass for contributions (e.g. authors)


ENTRY_TYPES: dict[str, EntryType] = {}


def register_entry_type(t: EntryType) -> None:
    if t.name in ENTRY_TYPES:
        raise ValueError(f"entry type {t.name!r} registered twice")
    ENTRY_TYPES[t.name] = t


# ---------------- helpers over a chain ----------------
def events(chain) -> dict:
    return {x["payload"]["event_id"]: x["payload"] for x in chain if x["type"] == "event"}


def groups(chain) -> dict:
    return {x["payload"]["group_id"]: x["payload"] for x in chain if x["type"] == "group"}


def closed_events(chain) -> set:
    return {x["payload"]["event_id"] for x in chain if x["type"] == "close"}


def published(chain) -> set:
    return {x["payload"]["content_hash"] for x in chain if x["type"] == "publish"}


def roles_of(chain, event_id, pub) -> set:
    return {x["payload"]["role"] for x in chain
            if x["type"] == "contract" and x["payload"].get("event_id") == event_id and x["payload"].get("contractor") == pub}


def valid_policy(pol) -> bool:
    if not isinstance(pol, dict) or not set(pol) <= POLICY_KEYS:
        return False
    if any(not isinstance(pol.get(k, []), list) or not all(isinstance(x, str) for x in pol.get(k, [])) for k in POLICY_LISTS):
        return False
    for key in POLICY_MAPS:
        m = pol.get(key, {})
        if not isinstance(m, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in m.items()):
            return False
    return True


def _rules_hash(p):
    return {"rules_hash": p["rules_hash"]} if "rules_hash" in p else {}


def _inc(rec, who, key, by=1):
    rec[who][key] += by


def _inc_map(rec, who, key, name):
    rec[who][key][name] += 1


# ---------------- event ----------------
def _event_shape(chain, e, now, s):
    p = e["payload"]
    if not isinstance(p.get("approvers", []), list):
        return "bad approvers"
    if p.get("issuer") in p.get("approvers", []):
        return "approver must differ from the issuer"


def _event_once(chain, e, now, s):
    if e["payload"].get("event_id") in events(chain):
        return "event already declared"
    if not valid_policy(e["payload"].get("policy", {})):
        return "bad policy"
    p = e["payload"]
    if ("mode" in p or "apps" in p) and not valid_run(p.get("mode"), p.get("apps", [])):
        return "bad mode or app list"


def _event_contribute(rec, p, index):
    _inc(rec, p["issuer"], "events")
    for a in p.get("approvers", []):
        _inc(rec, a, "approvals")


# ---------------- contract ----------------
def _contract_rule(chain, e, now, s):
    p = e["payload"]
    ev = events(chain)[p["event_id"]]
    if p.get("issuer") != ev["issuer"]:
        return "only the event issuer can contract roles"
    roles = ev.get("policy", {}).get("roles")
    if roles and p.get("role") not in roles:
        return "role not allowed by the event policy"


def _contract_public(p, chain):
    hidden = events(chain).get(p["event_id"], {}).get("policy", {}).get("hidden_roles", [])
    return {"role": p["role"], "issuer": p["issuer"], "contractor": None if p["role"] in hidden else p["contractor"], **_rules_hash(p)}


# ---------------- publish ----------------
def _publish_shape(chain, e, now, s):
    label = e["payload"].get("label")
    if label is not None and (not isinstance(label, str) or not label or len(label) > s.ledger_label_max):
        return f"label must be a non-empty string of at most {s.ledger_label_max} characters"


def _publish_rule(chain, e, now, s):
    p = e["payload"]
    if p.get("content_hash") in published(chain):
        return "content already published (first publisher wins)"
    ev = p.get("event_id")
    if p.get("label") is not None and any(x["type"] == "publish" and x["payload"].get("label") == p["label"] and x["payload"].get("author") == p["author"]
                                          and x["payload"].get("event_id") == ev for x in chain):
        return "label already used by this author in this event (one registration per label)"
    if ev is not None:
        conflict = set(events(chain)[ev].get("policy", {}).get("conflict_roles", []))
        if conflict & roles_of(chain, ev, p.get("author")):
            return "a contractor in a conflicting role cannot publish into this event"


def _publish_index(p, index):
    index.setdefault("author", {})[p["content_hash"]] = p["author"]


# ---------------- share ----------------
def _share_contribute(rec, p, index):
    author = index.get("author", {}).get(p["content_hash"])
    if author not in (None, p["consumer"]):
        rec[author]["received_by"].add(p["consumer"])


# ---------------- feedback ----------------
def _feedback_rule(chain, e, now, s):
    p, ch = e["payload"], e["payload"].get("content_hash")
    if any(x["type"] == "feedback" and x["payload"]["evaluator"] == p["evaluator"] and x["payload"]["content_hash"] == ch
           and x["payload"].get("verdict") == p.get("verdict") for x in chain):
        return "duplicate feedback (one verdict per evaluator per content)"
    ev = p.get("event_id")
    if ev is not None:
        need = events(chain)[ev].get("policy", {}).get("verdict_roles", {}).get(p.get("verdict"))
        if need == ISSUER and p["evaluator"] != events(chain)[ev]["issuer"]:
            return f"verdict '{p.get('verdict')}' requires the event issuer"
        if need and need != ISSUER and need not in roles_of(chain, ev, p["evaluator"]):
            return f"verdict '{p.get('verdict')}' requires the '{need}' role in this event"
    if not any(x["type"] == "share" and x["payload"]["content_hash"] == ch and x["payload"]["consumer"] == p["evaluator"] for x in chain):
        return "evaluator never received this content"


def _feedback_contribute(rec, p, index):
    _inc_map(rec, p["evaluator"], "verdicts_given", p.get("verdict"))
    author = index.get("author", {}).get(p["content_hash"])
    if author:
        _inc_map(rec, author, "verdicts_received", p.get("verdict"))


# ---------------- attest ----------------
def _attest_shape(chain, e, now, s):
    parties = e["payload"].get("parties")
    if not isinstance(parties, list) or not parties:
        return "attest needs at least one party"
    if len(set(parties)) != len(parties):
        return "duplicate parties"


def _attest_rule(chain, e, now, s):
    p = e["payload"]
    ev = p.get("event_id")
    if ev is None:
        return
    if any(x["type"] == "attest" and x["payload"].get("event_id") == ev and x["payload"].get("kind") == p.get("kind")
           and x["payload"].get("subject") == p.get("subject") for x in chain):
        return "already attested (kind, subject) in this event"
    decl = events(chain)[ev]
    need = decl.get("policy", {}).get("attest_roles", {}).get(p.get("kind"))
    if need == ISSUER and p["parties"] != [decl["issuer"]]:
        return f"attest '{p.get('kind')}' must be by the event issuer alone"
    if need and need != ISSUER and not all(need in roles_of(chain, ev, who) for who in p["parties"]):
        return f"attest '{p.get('kind')}' requires every party to hold the '{need}' role in this event"


def _attest_contribute(rec, p, index):
    for who in p.get("parties", []):
        _inc_map(rec, who, "attested", p.get("kind"))


# ---------------- reveal ----------------
def _reveal_rule(chain, e, now, s):
    """a reveal opens the author's own registration: same event, same label, and the sealed hash must match"""
    p = e["payload"]
    c = next((x for x in chain if x["hash"] == p.get("commit")), None)
    if c is None or c["type"] != "publish" or c["payload"].get("event_id") != p.get("event_id"):
        return "commit must be a registration (publish) in this event"
    if c["payload"].get("author") != p.get("author"):
        return "only the author of the registration can reveal it"
    if c["payload"].get("label") != p.get("label"):
        return "label differs from the registration's label"
    if commit_hash(str(p.get("label")), p.get("value"), str(p.get("salt")), p["author"]) != c["payload"]["content_hash"]:
        return "revealed value and salt do not match the registered hash"
    if any(x["type"] == "reveal" and x["payload"].get("commit") == p["commit"] for x in chain):
        return "this registration is already revealed"
    allowed = events(chain)[p["event_id"]].get("policy", {}).get("reveal_values")
    if allowed and p.get("value") not in allowed:
        return f"value is not one of the event's allowed values {allowed}"


# ---------------- close ----------------
def _close_rule(chain, e, now, s):
    if e["payload"].get("issuer") != events(chain)[e["payload"]["event_id"]]["issuer"]:
        return "only the event issuer can close it"


def _count(key, who_field):
    return lambda rec, p, index: _inc(rec, p[who_field], key)


def _map_count(key, who_field, name_field):
    return lambda rec, p, index: _inc_map(rec, p[who_field], key, p[name_field])


# ---------------- the built-in types ----------------
for _t in (
    EntryType("genesis", lambda p: [p.get("god")], public=lambda p, c: {"god": p["god"], "broker": p["broker"], "recorder": p["recorder"]}),
    EntryType("group", lambda p: [p.get("founder")], public=lambda p, c: {"founder": p["founder"], "closed": p["closed"], "brokers": list(p.get("brokers", []))},
              counters={"groups": 0}, contribute=_count("groups", "founder")),
    EntryType("event", lambda p: [p.get("issuer"), *p.get("approvers", [])], shape=_event_shape, rules=(_event_once,),
              public=lambda p, c: {**_rules_hash(p), **({"mode": p["mode"], "apps": p.get("apps", [])} if "mode" in p else {}),
                                   "issuer": p["issuer"], "kind": p.get("kind"), "approvers": list(p.get("approvers", []))},
              counters={"events": 0, "approvals": 0}, contribute=_event_contribute),
    EntryType("contract", lambda p: [p.get("issuer"), p.get("contractor")], event_ref="required", unique_nonce=True, rules=(_contract_rule,),
              public=_contract_public, counters={"roles": defaultdict(int)}, contribute=_map_count("roles", "contractor", "role")),
    EntryType("publish", lambda p: [p.get("author")], event_ref="optional", shape=_publish_shape, rules=(_publish_rule,),
              public=lambda p, c: {"author": p["author"], "content_hash": p["content_hash"], **({"label": p["label"]} if "label" in p else {})},
              counters={"published": 0},
              contribute=_count("published", "author"), index=_publish_index),
    EntryType("share", lambda p: [p.get("provider"), p.get("consumer")], needs_content=True, unique_nonce=True,
              counters={"received_by": set()}, contribute=_share_contribute),
    EntryType("feedback", lambda p: [p.get("evaluator")], event_ref="optional", needs_content=True, rules=(_feedback_rule,),
              counters={"verdicts_received": defaultdict(int), "verdicts_given": defaultdict(int)}, contribute=_feedback_contribute),
    EntryType("attest", lambda p: list(p.get("parties", [])) or [None], event_ref="optional", unique_nonce=True, shape=_attest_shape,
              rules=(_attest_rule,), public=lambda p, c: {"kind": p.get("kind"), "subject": p.get("subject"), "parties": list(p["parties"]),
                                                          "value": p.get("value")},
              counters={"attested": defaultdict(int)}, contribute=_attest_contribute),
    EntryType("reveal", lambda p: [p.get("author")], event_ref="required", rules=(_reveal_rule,),
              public=lambda p, c: {"author": p["author"], "label": p.get("label"), "value": p.get("value"), "salt": p.get("salt"),
                                   "commit": p.get("commit")},
              counters={"revealed": 0}, contribute=_count("revealed", "author")),
    EntryType("close", lambda p: [p.get("issuer")], event_ref="required", rules=(_close_rule,),
              public=lambda p, c: {"issuer": p["issuer"], "result_hash": p.get("result_hash")}, counters={"closed": 0},
              contribute=_count("closed", "issuer")),
):
    register_entry_type(_t)
