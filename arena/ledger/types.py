"""Ledger entry types. Each type is one object: who signs, its own rules, what public verify may show, and how it
counts in contributions. Add a type by registering it; the ledger, the recorder and contributions do not change.
The platform does not know what any role or verdict means: events declare a policy and rules compare strings."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from ..crypto import commit_hash
from .elements import check_elements
from .run import valid_run

POLICY_LISTS = ("roles", "conflict_roles", "hidden_roles", "reveal_values", "assigned_kinds", "attest_kinds")
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
    private_keys: Callable[[dict, dict], set] | None = None  # (full payload, its event's policy) -> fields that must go in the envelope


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


def assignments(chain, event_id) -> dict:
    """subject -> assigned parties, from the issuer's assign entries of one event"""
    out = {}
    for x in chain:
        if x["type"] == "assign" and x["payload"].get("event_id") == event_id:
            out.update(x["payload"]["subjects"])
    return out


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
@dataclass(frozen=True)
class EventColumn:
    """an optional column of the event declaration that some module owns (elements, schedule, codebook, ...): its check
    and whether its value shows in the public view. Registered, so the event rule never names them (open/closed)"""
    name: str
    check: Callable | None = None   # (chain, payload, settings) -> why refused, or None; runs when the column is present
    public: bool = True


EVENT_COLUMNS: dict[str, EventColumn] = {}


def register_event_column(c: EventColumn) -> None:
    if c.name in EVENT_COLUMNS:
        raise ValueError(f"event column {c.name!r} registered twice")
    EVENT_COLUMNS[c.name] = c


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
    for col in EVENT_COLUMNS.values():  # the optional columns, each checked by the module that owns it
        if col.check and col.name in p:
            bad = col.check(chain, p, s)
            if bad:
                return bad


def _event_contribute(rec, p, index):
    _inc(rec, p["issuer"], "events")
    if isinstance(p.get("codebook"), dict) and p["codebook"].get("publisher"):  # standing comes from being followed
        _inc(rec, p["codebook"]["publisher"], "codebook_followers")
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
    pol = decl.get("policy", {})
    if pol.get("attest_kinds") and p.get("kind") not in pol["attest_kinds"]:  # opt-in: without the list, kinds are free
        return f"kind '{p.get('kind')}' is not one of the event's kinds {pol['attest_kinds']}"
    if p.get("kind") in pol.get("assigned_kinds", []):
        assigned = assignments(chain, ev).get(p.get("subject"))
        if assigned is None:
            return f"subject '{p.get('subject')}' was never assigned in this event"
        if sorted(p["parties"]) != sorted(assigned):
            return f"parties differ from the parties assigned to '{p.get('subject')}'"
    need = pol.get("attest_roles", {}).get(p.get("kind"))
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


# ---------------- assign ----------------
def _assign_shape(chain, e, now, s):
    subj = e["payload"].get("subjects")
    if not isinstance(subj, dict) or not subj:
        return "subjects must map each subject to its parties"
    for k, v in subj.items():
        if not isinstance(k, str) or not k or not isinstance(v, list) or not v or len(set(v)) != len(v) or not all(isinstance(x, str) for x in v):
            return f"bad parties for subject {k!r}"


def _assign_rule(chain, e, now, s):
    p = e["payload"]
    if p.get("issuer") != events(chain)[p["event_id"]]["issuer"]:
        return "only the event issuer can assign"
    done = assignments(chain, p["event_id"])
    for k, parties in p["subjects"].items():
        if k in done:
            return f"subject {k!r} already assigned"
        if not all(roles_of(chain, p["event_id"], x) for x in parties):
            return f"every party of {k!r} must hold a contract in this event"


# ---------------- key_rotate: key succession ----------------
ROTATABLE = ("recorder", "god")


def current_keys(chain) -> dict:
    """the recorder and god keys valid at the end of this chain: from the genesis, following every key_rotate"""
    if not chain or chain[0]["type"] != "genesis":
        return {"recorder": chain[0]["seal"]["pub"] if chain and "seal" in chain[0] else None, "god": None}
    keys = {"recorder": chain[0]["payload"]["recorder"], "god": chain[0]["payload"]["god"]}
    for x in chain[1:]:
        if x["type"] == "key_rotate":
            keys[x["payload"]["role"]] = x["payload"]["new"]
    return keys


def _rotate_signers(p):
    return [p.get("old"), p.get("new")] + ([p.get("god")] if p.get("role") == "recorder" else [])


def _rotate_shape(chain, e, now, s):
    p = e["payload"]
    if p.get("role") not in ROTATABLE or not p.get("old") or not p.get("new") or p["old"] == p["new"]:
        return "key_rotate needs role (recorder or god), old and new keys"
    if p["role"] == "recorder" and not p.get("god"):
        return "a recorder key change needs god's approval"


def _rotate_rule(chain, e, now, s):
    p, keys = e["payload"], current_keys(chain)
    if chain and chain[0]["type"] != "genesis":
        return "key succession needs a ledger begun by a genesis"
    if p["old"] != keys[p["role"]]:
        return f"old key is not the current {p['role']} key"
    if p["role"] == "recorder" and p["god"] != keys["god"]:
        return "approved by a key that is not the current god key"


# ---------------- chain_link: a community chain links its start into the original (parent) chain ----------------
def _is_hex64(x) -> bool:
    return isinstance(x, str) and len(x) == 64 and all(c in "0123456789abcdef" for c in x)


def _link_shape(chain, e, now, s):
    p = e["payload"]
    if not _is_hex64(p.get("child_ledger_id")) or not p.get("child_god") or not p.get("child_recorder"):
        return "chain_link needs child_ledger_id (the new chain's genesis hash), child_god and child_recorder"


def _link_rule(chain, e, now, s):
    if chain and "parent" in chain[0]["payload"]:  # branches grow only from the trunk (user 2026-11-02, dev/chain-policy.md)
        return "only the trunk (the root chain) takes branch links; a branch chain cannot start a branch"
    if any(x["type"] == "chain_link" and x["payload"]["child_ledger_id"] == e["payload"]["child_ledger_id"] for x in chain):
        return "this chain is already linked"


# ---------------- close ----------------
def _close_rule(chain, e, now, s):
    if e["payload"].get("issuer") != events(chain)[e["payload"]["event_id"]]["issuer"]:
        return "only the event issuer can close it"


def _count(key, who_field):
    return lambda rec, p, index: _inc(rec, p[who_field], key)


def _map_count(key, who_field, name_field):
    return lambda rec, p, index: _inc_map(rec, p[who_field], key, p[name_field])


register_event_column(EventColumn("elements", lambda chain, p, s: check_elements(p["elements"])))


# ---------------- the built-in types ----------------
for _t in (
    EntryType("genesis", lambda p: [p.get("god")], public=lambda p, c: {"god": p["god"], "broker": p["broker"], "recorder": p["recorder"],
                                                                         **({"parent": p["parent"]} if "parent" in p else {})}),
    EntryType("group", lambda p: [p.get("founder")], public=lambda p, c: {"founder": p["founder"], "closed": p["closed"], "brokers": list(p.get("brokers", []))},
              counters={"groups": 0}, contribute=_count("groups", "founder")),
    EntryType("event", lambda p: [p.get("issuer"), *p.get("approvers", [])], shape=_event_shape, rules=(_event_once,),
              public=lambda p, c: {**_rules_hash(p), **({"mode": p["mode"], "apps": p.get("apps", [])} if "mode" in p else {}),
                                   **{c.name: p[c.name] for c in EVENT_COLUMNS.values() if c.public and p.get(c.name)},
                                   "issuer": p["issuer"], "kind": p.get("kind"), "approvers": list(p.get("approvers", []))},
              counters={"events": 0, "approvals": 0}, contribute=_event_contribute),
    EntryType("contract", lambda p: [p.get("issuer"), p.get("contractor")], event_ref="required", unique_nonce=True, rules=(_contract_rule,),
              public=_contract_public, counters={"roles": defaultdict(int)}, contribute=_map_count("roles", "contractor", "role"),
              private_keys=lambda p, pol: {"contractor"} if p.get("role") in (pol or {}).get("hidden_roles", []) else set()),
    EntryType("publish", lambda p: [p.get("author")], event_ref="optional", shape=_publish_shape, rules=(_publish_rule,),
              public=lambda p, c: {"author": p["author"], "content_hash": p["content_hash"], **({"label": p["label"]} if "label" in p else {})},
              counters={"published": 0},
              contribute=_count("published", "author"), index=_publish_index),
    EntryType("share", lambda p: [p.get("provider"), p.get("consumer")], event_ref="optional", needs_content=True, unique_nonce=True,
              private_keys=lambda p, pol: {"provider", "consumer", "content_hash", "terms"},  # who handed what to whom stays private
              counters={"received_by": set()}, contribute=_share_contribute),
    EntryType("feedback", lambda p: [p.get("evaluator")], event_ref="optional", needs_content=True, rules=(_feedback_rule,),
              public=lambda p, c: {k: p[k] for k in ("evaluator", "content_hash", "verdict", "score") if k in p},
              counters={"verdicts_received": defaultdict(int), "verdicts_given": defaultdict(int)}, contribute=_feedback_contribute),
    EntryType("attest", lambda p: list(p.get("parties", [])) or [None], event_ref="optional", unique_nonce=True, shape=_attest_shape,
              rules=(_attest_rule,), public=lambda p, c: {"kind": p.get("kind"), "subject": p.get("subject"), "parties": list(p["parties"]),
                                                          "value": p.get("value")},
              counters={"attested": defaultdict(int)}, contribute=_attest_contribute),
    EntryType("reveal", lambda p: [p.get("author")], event_ref="required", rules=(_reveal_rule,),
              public=lambda p, c: {"author": p["author"], "label": p.get("label"), "value": p.get("value"), "salt": p.get("salt"),
                                   "commit": p.get("commit")},
              counters={"revealed": 0}, contribute=_count("revealed", "author")),
    EntryType("assign", lambda p: [p.get("issuer")], event_ref="required", shape=_assign_shape, rules=(_assign_rule,),
              public=lambda p, c: {"issuer": p["issuer"], "subjects": p["subjects"]}),
    EntryType("chain_link", lambda p: [p.get("child_god"), p.get("child_recorder")], unique_nonce=True, shape=_link_shape, rules=(_link_rule,),
              public=lambda p, c: {k: p.get(k) for k in ("child_ledger_id", "child_god", "child_recorder", "name")}),
    EntryType("key_rotate", _rotate_signers, unique_nonce=True, shape=_rotate_shape, rules=(_rotate_rule,),
              public=lambda p, c: {"role": p.get("role"), "old": p.get("old"), "new": p.get("new"), **({"god": p["god"]} if "god" in p else {})}),
    EntryType("close", lambda p: [p.get("issuer")], event_ref="required", rules=(_close_rule,),
              public=lambda p, c: {"issuer": p["issuer"], "result_hash": p.get("result_hash")}, counters={"closed": 0},
              contribute=_count("closed", "issuer")),
):
    register_entry_type(_t)


def split_payload(kind: str, full: dict, policy: dict | None = None) -> tuple[dict, dict | None]:
    """a full payload -> (the public body to sign, the private fields or None), by the type's rule for what must stay
    private (protocol 3). `policy` is the policy of the event the entry belongs to (from its notarized notice)"""
    from .envelope import with_private
    t = ENTRY_TYPES[kind]
    keys = t.private_keys(full, policy or {}) if t.private_keys else set()
    fields = {k: full[k] for k in keys if k in full}
    return with_private({k: v for k, v in full.items() if k not in fields}, fields), (fields or None)
