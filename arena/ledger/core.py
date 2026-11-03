"""The ledger kept by ONE recorder (distributed recorders are the last phase). Content never goes on-chain: only hashes,
public keys, signatures. Entry: {type, payload, sigs, prev, ts, seq, hash, seal:{pub, sig}};
hash = SHA-256 of canon(type, payload, sigs, prev, ts)."""
from __future__ import annotations

import copy
import time
from collections import defaultdict
from typing import Callable

from ..crypto import Identity, canon, h, verify
from .envelope import PRIVATE, assemble, exposed, hash_body, merged, private_hash, stored
from .rules import check, signers
from .store import LedgerStore
from .types import ENTRY_TYPES, events


class LedgerCorrupt(Exception):
    pass


class Ledger:
    def __init__(self, identity: Identity, store: LedgerStore, settings, clock: Callable[[], float] = time.time):
        self.identity, self.store, self.settings, self.clock = identity, store, settings, clock
        self.raw: list[dict] = store.load()            # as stored: public body + envelope
        status = audit_chain(self.raw)
        if status != "ok":
            raise LedgerCorrupt(f"stored ledger failed audit: {status}")
        self.chain: list[dict] = [merged(e) for e in self.raw]  # the full view the rules and services read

    def head(self) -> str:
        return self.chain[-1]["hash"] if self.chain else "0" * 64

    def find(self, hash_: str) -> dict | None:
        return next((x for x in self.chain if x["hash"] == hash_), None)

    def _seal(self, e: dict, envelope: dict | None) -> dict:
        body = copy.deepcopy(hash_body(e))
        entry = dict(body, seq=len(self.raw), hash=h(canon(body)))
        entry["seal"] = {"pub": self.identity.pub, "sig": self.identity.sign(entry["hash"])}
        if envelope:
            entry["envelope"] = copy.deepcopy(envelope)
        self.raw.append(entry)
        self.store.append(entry)
        self.chain.append(merged(entry))
        return self.chain[-1]

    def propose(self, kind: str, payload: dict, sigs: dict, private: dict | None = None) -> tuple[dict | None, str | None]:
        """sequencer path: assign prev/ts, validate, seal, append. `payload` is the signed public body; `private` the
        fields of the private envelope (their hash must be the body's `private` column)"""
        t = ENTRY_TYPES.get(kind)
        if t is None:
            return None, "unknown type"
        e, envelope, view, err = assemble(kind, payload, sigs, private, t.signers)
        if err:
            return None, err
        e.update(prev=self.head(), ts=self.clock())
        view.update(prev=e["prev"], ts=e["ts"])
        err = check(self.chain, view, self.clock(), self.settings)
        if not err and t.private_keys:
            err = exposed(t.private_keys(view["payload"], events(self.chain).get(view["payload"].get("event_id"), {}).get("policy", {})), payload)
        return (None, err) if err else (self._seal(e, envelope), None)

    def audit(self) -> str:
        return audit_chain(self.raw)


def audit_chain(chain: list[dict], anchor: dict | None = None) -> str:
    """verify hashes, participant signatures and recorder seals of any chain copy. Seals must be by the recorder key valid
    at each point (from the genesis, following key_rotate); entries after a genesis must name its ledger_id when they name
    one. With an anchor {genesis_hash, god_pub} (published outside the ledger) the chain must begin with that genesis."""
    chain = [stored(e) for e in chain]  # either form may be audited
    if anchor and (not chain or chain[0]["type"] != "genesis" or chain[0]["hash"] != anchor.get("genesis_hash")
                   or chain[0]["payload"].get("god") != anchor.get("god_pub")):
        return "NOT THIS LEDGER (root of trust: genesis hash or god key differs)"
    prev = "0" * 64
    genesis = chain[0] if chain and chain[0]["type"] == "genesis" else None
    sealer = genesis["payload"]["recorder"] if genesis else (chain[0]["seal"]["pub"] if chain and "seal" in chain[0] else None)
    for i, e in enumerate(chain):
        if e["prev"] != prev or e["hash"] != h(canon(hash_body(e))):
            return f"TAMPERED at seq {i} (hash chain)"
        if e["type"] not in ENTRY_TYPES:
            return f"TAMPERED at seq {i} (signature)"
        env = e.get("envelope")
        if env is not None:  # a full copy: the envelope must be the one the body and the hash name, every signature checks
            if (PRIVATE in e["payload"] or env.get("fields")) and e["payload"].get(PRIVATE) != private_hash(env.get("fields", {})):
                return f"TAMPERED at seq {i} (private envelope)"
            if ("private_sigs" in e or env.get("sigs")) and e.get("private_sigs") != private_hash(env.get("sigs", {})):
                return f"TAMPERED at seq {i} (private envelope)"
            m = merged(e)
            if any(not s or not verify(s, e["payload"], m["sigs"].get(s, "")) for s in signers(m)):
                return f"TAMPERED at seq {i} (signature)"
        else:  # no envelope: a public copy may skip only the signers whose identity is private
            hidden_ok = PRIVATE in e["payload"] or "private_sigs" in e
            if any((not s and not hidden_ok) or (s and not verify(s, e["payload"], e["sigs"].get(s, ""))) for s in signers(e)):
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
