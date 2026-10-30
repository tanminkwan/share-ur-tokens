"""Hash-chained, signed provenance ledger kept by ONE recorder (distributed recorders are the last phase).
Content never goes on-chain: only hashes, public keys (pen names), signatures.
Entry types: event (a declared event with its policy and optional approvers), contract, publish, share, feedback.

Entry shape: {type, payload, sigs, prev, ts, seq, hash, seal:{pub, sig}}; hash = SHA-256 of canon(type, payload, sigs, prev, ts).
Rules live in RULES as small functions run in order (add a rule = add a function). The Ledger does not know about HTTP.
"""
from __future__ import annotations

import copy
import json
import os
import time
from collections import defaultdict
from typing import Callable, Protocol

from .config import Settings
from .crypto import Identity, canon, h, verify

BODY = ("type", "payload", "sigs", "prev", "ts")
TYPES = ("event", "contract", "publish", "share", "feedback")


class LedgerCorrupt(Exception):
    pass


# ---------------- storage ----------------
class LedgerStore(Protocol):
    def load(self) -> list[dict]: ...
    def append(self, entry: dict) -> None: ...


class MemoryStore:
    def __init__(self):
        self.rows: list[dict] = []

    def load(self) -> list[dict]:
        return list(self.rows)

    def append(self, entry: dict) -> None:
        self.rows.append(entry)


class JsonlStore:
    """one entry per line, append-only"""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def append(self, entry: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------- rules ----------------
# The platform does not know what any role or verdict means. Events declare a policy; these rules compare strings.
POLICY_LISTS = ("roles", "conflict_roles", "hidden_roles")
POLICY_KEYS = set(POLICY_LISTS) | {"verdict_roles"}
ISSUER = "issuer"  # policy value meaning "the event issuer" rather than a contracted role


def signers(e: dict) -> list:
    p = e["payload"]
    return {"event": [p.get("issuer"), *p.get("approvers", [])], "publish": [p.get("author")],
            "share": [p.get("provider"), p.get("consumer")], "feedback": [p.get("evaluator")],
            "contract": [p.get("issuer"), p.get("contractor")]}[e["type"]]


def events(chain) -> dict:
    return {x["payload"]["event_id"]: x["payload"] for x in chain if x["type"] == "event"}


def _published(chain) -> set:
    return {x["payload"]["content_hash"] for x in chain if x["type"] == "publish"}


def _roles_of(chain, event_id, pub) -> set:
    return {x["payload"]["role"] for x in chain
            if x["type"] == "contract" and x["payload"].get("event_id") == event_id and x["payload"].get("contractor") == pub}


def _valid_policy(pol) -> bool:
    if not isinstance(pol, dict) or not set(pol) <= POLICY_KEYS:
        return False
    if any(not isinstance(pol.get(k, []), list) or not all(isinstance(x, str) for x in pol.get(k, [])) for k in POLICY_LISTS):
        return False
    vr = pol.get("verdict_roles", {})
    return isinstance(vr, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in vr.items())


def r_type(chain, e, now, s):
    if e["type"] not in TYPES:
        return "unknown type"


def r_prev(chain, e, now, s):
    head = chain[-1]["hash"] if chain else "0" * 64
    if e["prev"] != head:
        return "bad prev hash"


def r_shape(chain, e, now, s):
    if e["type"] == "event":
        p = e["payload"]
        if not isinstance(p.get("approvers", []), list):
            return "bad approvers"
        if p.get("issuer") in p.get("approvers", []):
            return "approver must differ from the issuer"


def r_signatures(chain, e, now, s):
    for who in signers(e):
        sig = e["sigs"].get(who) if who else None
        if not who or not sig or not verify(who, e["payload"], sig):
            return f"missing/invalid signature of {str(who)[:8]}"


def r_time(chain, e, now, s):
    if chain and e["ts"] < chain[-1]["ts"]:
        return "timestamp goes backwards"


def r_event(chain, e, now, s):
    if e["type"] != "event":
        return
    if e["payload"].get("event_id") in events(chain):
        return "event already declared"
    if not _valid_policy(e["payload"].get("policy", {})):
        return "bad policy"


def r_event_ref(chain, e, now, s):
    """an entry that names an event must name a declared one"""
    ev = e["payload"].get("event_id")
    if e["type"] in ("contract", "publish", "feedback") and (ev is not None or e["type"] == "contract") and ev not in events(chain):
        return "unknown event"


def r_contract(chain, e, now, s):
    if e["type"] != "contract":
        return
    p = e["payload"]
    ev = events(chain)[p["event_id"]]
    if p.get("issuer") != ev["issuer"]:
        return "only the event issuer can contract roles"
    roles = ev.get("policy", {}).get("roles")
    if roles and p.get("role") not in roles:
        return "role not allowed by the event policy"


def r_publish(chain, e, now, s):
    if e["type"] != "publish":
        return
    p = e["payload"]
    if p.get("content_hash") in _published(chain):
        return "content already published (first publisher wins)"
    ev = p.get("event_id")
    if ev is not None:
        conflict = set(events(chain)[ev].get("policy", {}).get("conflict_roles", []))
        if conflict & _roles_of(chain, ev, p.get("author")):
            return "a contractor in a conflicting role cannot publish into this event"


def r_known_content(chain, e, now, s):
    if e["type"] in ("share", "feedback") and e["payload"].get("content_hash") not in _published(chain):
        return "unknown content"


def r_nonce(chain, e, now, s):
    if e["type"] in ("share", "contract") and any(
            x["type"] == e["type"] and x["payload"].get("nonce") == e["payload"].get("nonce") for x in chain):
        return "replay (nonce already used)"


def r_feedback(chain, e, now, s):
    if e["type"] != "feedback":
        return
    p, ch = e["payload"], e["payload"].get("content_hash")
    if any(x["type"] == "feedback" and x["payload"]["evaluator"] == p["evaluator"] and x["payload"]["content_hash"] == ch
           and x["payload"].get("verdict") == p.get("verdict") for x in chain):
        return "duplicate feedback (one verdict per evaluator per content)"
    ev = p.get("event_id")
    if ev is not None:
        need = events(chain)[ev].get("policy", {}).get("verdict_roles", {}).get(p.get("verdict"))
        if need == ISSUER and p["evaluator"] != events(chain)[ev]["issuer"]:
            return f"verdict '{p.get('verdict')}' requires the event issuer"
        if need and need != ISSUER and need not in _roles_of(chain, ev, p["evaluator"]):
            return f"verdict '{p.get('verdict')}' requires the '{need}' role in this event"
    if not any(x["type"] == "share" and x["payload"]["content_hash"] == ch and x["payload"]["consumer"] == p["evaluator"] for x in chain):
        return "evaluator never received this content"


RULES: list[Callable] = [r_type, r_prev, r_shape, r_signatures, r_time, r_event, r_event_ref, r_contract,
                         r_publish, r_known_content, r_nonce, r_feedback]


def check(chain: list[dict], e: dict, now: float, settings: Settings) -> str | None:
    for rule in RULES:
        error = rule(chain, e, now, settings)
        if error:
            return error
    return None


# ---------------- the ledger ----------------
class Ledger:
    def __init__(self, identity: Identity, store: LedgerStore, settings: Settings, clock: Callable[[], float] = time.time):
        self.identity, self.store, self.settings, self.clock = identity, store, settings, clock
        self.chain: list[dict] = store.load()
        status = audit_chain(self.chain)
        if status != "ok":
            raise LedgerCorrupt(f"stored ledger failed audit: {status}")

    def head(self) -> str:
        return self.chain[-1]["hash"] if self.chain else "0" * 64

    def find(self, hash_: str) -> dict | None:
        return next((x for x in self.chain if x["hash"] == hash_), None)

    def _seal(self, e: dict) -> dict:
        body = copy.deepcopy({k: e[k] for k in BODY})
        entry = dict(body, seq=len(self.chain), hash=h(canon(body)))
        entry["seal"] = {"pub": self.identity.pub, "sig": self.identity.sign(entry["hash"])}
        self.chain.append(entry)
        self.store.append(entry)
        return entry

    def propose(self, kind: str, payload: dict, sigs: dict) -> tuple[dict | None, str | None]:
        """sequencer path: assign prev/ts, validate, seal, append"""
        e = {"type": kind, "payload": payload, "sigs": sigs, "prev": self.head(), "ts": self.clock()}
        err = check(self.chain, e, self.clock(), self.settings)
        return (None, err) if err else (self._seal(e), None)

    def audit(self) -> str:
        return audit_chain(self.chain)


def audit_chain(chain: list[dict]) -> str:
    """verify hashes, participant signatures and recorder seals of any chain copy"""
    prev = "0" * 64
    for i, e in enumerate(chain):
        if e["prev"] != prev or e["hash"] != h(canon({k: e[k] for k in BODY})):
            return f"TAMPERED at seq {i} (hash chain)"
        if any(not s or not verify(s, e["payload"], e["sigs"].get(s, "")) for s in signers(e)):
            return f"TAMPERED at seq {i} (signature)"
        if "seal" in e and not verify(e["seal"]["pub"], e["hash"], e["seal"]["sig"]):
            return f"TAMPERED at seq {i} (recorder seal)"
        prev = e["hash"]
    return "ok"


def contribution(chain: list[dict]) -> dict:
    """per public key, without knowing what any verdict or role means"""
    author = {x["payload"]["content_hash"]: x["payload"]["author"] for x in chain if x["type"] == "publish"}
    rec = defaultdict(lambda: {"published": 0, "received_by": set(), "verdicts_received": defaultdict(int),
                               "verdicts_given": defaultdict(int), "roles": defaultdict(int), "events": 0, "approvals": 0})
    for e in chain:
        p, t = e["payload"], e["type"]
        if t == "publish":
            rec[p["author"]]["published"] += 1
        elif t == "share" and author.get(p["content_hash"]) not in (None, p["consumer"]):
            rec[author[p["content_hash"]]]["received_by"].add(p["consumer"])
        elif t == "feedback":
            rec[p["evaluator"]]["verdicts_given"][p.get("verdict")] += 1
            if p["content_hash"] in author:
                rec[author[p["content_hash"]]]["verdicts_received"][p.get("verdict")] += 1
        elif t == "contract":
            rec[p["contractor"]]["roles"][p["role"]] += 1
        elif t == "event":
            rec[p["issuer"]]["events"] += 1
            for a in p.get("approvers", []):
                rec[a]["approvals"] += 1
    return {k: {"published": v["published"], "received_by": len(v["received_by"]), "verdicts_received": dict(v["verdicts_received"]),
                "verdicts_given": dict(v["verdicts_given"]), "roles": dict(v["roles"]), "events": v["events"], "approvals": v["approvals"]}
            for k, v in rec.items()}
