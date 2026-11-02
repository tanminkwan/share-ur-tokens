"""The ledger kept by ONE recorder (distributed recorders are the last phase). Content never goes on-chain: only hashes,
public keys, signatures. Entry: {type, payload, sigs, prev, ts, seq, hash, seal:{pub, sig}};
hash = SHA-256 of canon(type, payload, sigs, prev, ts)."""
from __future__ import annotations

import copy
import time
from collections import defaultdict
from typing import Callable

from ..crypto import Identity, canon, h, verify
from .rules import check, signers
from .store import LedgerStore
from .types import ENTRY_TYPES

BODY = ("type", "payload", "sigs", "prev", "ts")


class LedgerCorrupt(Exception):
    pass


class Ledger:
    def __init__(self, identity: Identity, store: LedgerStore, settings, clock: Callable[[], float] = time.time):
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


def audit_chain(chain: list[dict], anchor: dict | None = None) -> str:
    """verify hashes, participant signatures and recorder seals of any chain copy. Seals must be by the recorder key valid
    at each point (from the genesis, following key_rotate); entries after a genesis must name its ledger_id when they name
    one. With an anchor {genesis_hash, god_pub} (published outside the ledger) the chain must begin with that genesis."""
    if anchor and (not chain or chain[0]["type"] != "genesis" or chain[0]["hash"] != anchor.get("genesis_hash")
                   or chain[0]["payload"].get("god") != anchor.get("god_pub")):
        return "NOT THIS LEDGER (root of trust: genesis hash or god key differs)"
    prev = "0" * 64
    genesis = chain[0] if chain and chain[0]["type"] == "genesis" else None
    sealer = genesis["payload"]["recorder"] if genesis else (chain[0]["seal"]["pub"] if chain and "seal" in chain[0] else None)
    for i, e in enumerate(chain):
        if e["prev"] != prev or e["hash"] != h(canon({k: e[k] for k in BODY})):
            return f"TAMPERED at seq {i} (hash chain)"
        if e["type"] not in ENTRY_TYPES or any(not s or not verify(s, e["payload"], e["sigs"].get(s, "")) for s in signers(e)):
            return f"TAMPERED at seq {i} (signature)"
        if i > 0 and e["ts"] < chain[i - 1]["ts"]:
            return f"TAMPERED at seq {i} (time goes backwards)"
        if "seal" in e and (e["seal"]["pub"] != sealer or not verify(e["seal"]["pub"], e["hash"], e["seal"]["sig"])):
            return f"TAMPERED at seq {i} (recorder seal)"
        if genesis and i > 0 and "ledger_id" in e["payload"] and e["payload"]["ledger_id"] != genesis["hash"]:
            return f"TAMPERED at seq {i} (an entry of another ledger: ledger_id differs)"
        if e["type"] == "key_rotate" and e["payload"].get("role") == "recorder":
            sealer = e["payload"]["new"]  # from the next entry on
        prev = e["hash"]
    return "ok"


def public_view(e: dict, chain: list[dict]) -> dict:
    """what public verify may show about one entry, by its type"""
    return ENTRY_TYPES[e["type"]].public(e["payload"], chain)


def empty_record() -> dict:
    rec = {}
    for t in ENTRY_TYPES.values():
        for k, v in t.counters.items():
            rec[k] = copy.copy(v)
    return rec


def contribution(chain: list[dict]) -> dict:
    """per public key, without knowing what any verdict or role means; each entry type adds its own counters"""
    index: dict = {}
    for e in chain:
        t = ENTRY_TYPES.get(e["type"])
        if t and t.index:
            t.index(e["payload"], index)
    rec = defaultdict(empty_record)
    for e in chain:
        t = ENTRY_TYPES.get(e["type"])
        if t and t.contribute:
            t.contribute(rec, e["payload"], index)
    return {k: {f: (len(v) if isinstance(v, set) else dict(v) if isinstance(v, dict) else v) for f, v in r.items()} for k, r in rec.items()}
