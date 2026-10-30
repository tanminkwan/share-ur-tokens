"""Hash-chained, signed provenance ledger kept by ONE recorder (a distributed collector is the last phase).
Content never goes on-chain: only hashes, public keys (pen names), signatures.

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
TYPES = ("publish", "share", "feedback", "contract")


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
def signers(e: dict) -> list:
    p = e["payload"]
    return {"publish": [p.get("author")], "share": [p.get("provider"), p.get("consumer")],
            "feedback": [p.get("evaluator")], "contract": [p.get("issuer"), p.get("contractor")]}[e["type"]]


def _published(chain) -> set:
    return {x["payload"]["content_hash"] for x in chain if x["type"] == "publish"}


def r_type(chain, e, now, s):
    if e["type"] not in TYPES:
        return "unknown type"


def r_prev(chain, e, now, s):
    head = chain[-1]["hash"] if chain else "0" * 64
    if e["prev"] != head:
        return "bad prev hash"


def r_signatures(chain, e, now, s):
    for who in signers(e):
        sig = e["sigs"].get(who) if who else None
        if not who or not sig or not verify(who, e["payload"], sig):
            return f"missing/invalid signature of {str(who)[:8]}"


def r_time(chain, e, now, s):
    if chain and e["ts"] < chain[-1]["ts"]:
        return "timestamp goes backwards"


def r_publish(chain, e, now, s):
    if e["type"] != "publish":
        return
    p = e["payload"]
    if p.get("content_hash") in _published(chain):
        return "content already published (first publisher wins)"
    if any(x["type"] == "contract" and x["payload"].get("call_id") == p.get("call_id") and x["payload"].get("contractor") == p.get("author")
           for x in chain):
        return "a contracted recorder/reviewer cannot submit to the same call"


def r_known_content(chain, e, now, s):
    if e["type"] in ("share", "feedback") and e["payload"].get("content_hash") not in _published(chain):
        return "unknown content"


def r_nonce(chain, e, now, s):
    if e["type"] in ("share", "contract") and any(
            x["type"] == e["type"] and x["payload"].get("nonce") == e["payload"].get("nonce") for x in chain):
        return "replay (nonce already used)"


def r_contract_role(chain, e, now, s):
    if e["type"] == "contract" and e["payload"].get("role") not in s.contract_roles:
        return "unsupported role"


def r_feedback(chain, e, now, s):
    if e["type"] != "feedback":
        return
    p, ch = e["payload"], e["payload"].get("content_hash")
    if any(x["type"] == "feedback" and x["payload"]["evaluator"] == p["evaluator"] and x["payload"]["content_hash"] == ch
           and x["payload"].get("verdict") == p.get("verdict") for x in chain):
        return "duplicate feedback (one verdict per evaluator per content)"
    if p.get("verdict") == "review" and not any(
            x["type"] == "contract" and x["payload"]["call_id"] == p.get("call_id") and x["payload"]["contractor"] == p["evaluator"]
            for x in chain):
        return "no review contract for this call"
    if not any(x["type"] == "share" and x["payload"]["content_hash"] == ch and x["payload"]["consumer"] == p["evaluator"] for x in chain):
        return "evaluator never received this content"


RULES: list[Callable] = [r_type, r_prev, r_signatures, r_time, r_publish, r_known_content, r_nonce, r_contract_role, r_feedback]


def check(chain: list[dict], e: dict, now: float, settings: Settings) -> str | None:
    for rule in RULES:
        err = rule(chain, e, now, settings)
        if err:
            return err
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
    """per public key: distinct consumers who received their content (self excluded), adopted contents, roles served"""
    author = {x["payload"]["content_hash"]: x["payload"]["author"] for x in chain if x["type"] == "publish"}
    got, adopted, roles = defaultdict(set), defaultdict(int), defaultdict(int)
    for e in chain:
        p = e["payload"]
        if e["type"] == "share" and author.get(p["content_hash"]) != p["consumer"]:
            got[author[p["content_hash"]]].add(p["consumer"])
        if e["type"] == "feedback" and p.get("verdict") == "adopt":
            adopted[author[p["content_hash"]]] += 1
        if e["type"] == "contract":
            roles[p["contractor"]] += 1
    everyone = set(got) | set(adopted) | set(author.values()) | set(roles)
    return {a: {"received_by": len(got[a]), "adopted": adopted[a], "roles": roles[a]} for a in everyone}
