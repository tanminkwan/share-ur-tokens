"""Hash-chained, signed provenance ledger. Content never goes on-chain, only hashes + pseudonyms + signatures.

Entry types
  publish  signer: author               -> first publisher of a content hash wins (priority proof)
  share    signers: provider + consumer -> both agreed that this content changed hands (nonce prevents replay)
  feedback signer: evaluator            -> adopt/reject, only by someone who received that content
"""
import copy
import time
from collections import defaultdict

from .common import canon, h, verify

BODY = ("type", "payload", "sigs", "prev", "ts")
MAX_SKEW = 300  # seconds a sequencer timestamp may differ from the validator's clock


class Collector:
    def __init__(self, name: str):
        self.name, self.chain = name, []

    def head(self) -> str:
        return self.chain[-1]["hash"] if self.chain else "0" * 64

    @staticmethod
    def signers(e) -> list:
        p = e["type"], e["payload"]
        t, p = p
        return {"publish": [p.get("author")], "share": [p.get("provider"), p.get("consumer")],
                "feedback": [p.get("evaluator")]}[t]

    def _check(self, e):
        if e["type"] not in ("publish", "share", "feedback"):
            return "unknown type"
        if e["prev"] != self.head():
            return "bad prev hash"
        for s in self.signers(e):
            sig = e["sigs"].get(s)
            if not s or not sig or not verify(s, e["payload"], sig):
                return f"missing/invalid signature of {str(s)[:8]}"
        if self.chain and e["ts"] < self.chain[-1]["ts"]:
            return "timestamp goes backwards"
        if abs(e["ts"] - time.time()) > MAX_SKEW:
            return "timestamp out of range"
        p, ch = e["payload"], e["payload"].get("content_hash")
        published = {x["payload"]["content_hash"] for x in self.chain if x["type"] == "publish"}
        if e["type"] == "publish" and ch in published:
            return "content already published (first publisher wins)"
        if e["type"] in ("share", "feedback") and ch not in published:
            return "unknown content"
        if e["type"] == "share" and any(x["type"] == "share" and x["payload"].get("nonce") == p.get("nonce") for x in self.chain):
            return "replay (nonce already used)"
        if e["type"] == "feedback" and not any(
                x["type"] == "share" and x["payload"]["content_hash"] == ch and x["payload"]["consumer"] == p["evaluator"]
                for x in self.chain):
            return "evaluator never received this content"
        return None

    def _seal(self, e):
        body = copy.deepcopy({k: e[k] for k in BODY})  # each collector owns its copy
        e = dict(body, seq=len(self.chain), hash=h(canon(body)))
        self.chain.append(e)
        return e

    def propose(self, kind, payload, sigs):
        """sequencer path: assign prev/ts, validate, append"""
        e = {"type": kind, "payload": payload, "sigs": sigs, "prev": self.head(), "ts": time.time()}
        err = self._check(e)
        return (None, err) if err else (self._seal(e), None)

    def accept(self, entry):
        """validator path: independently re-check a sequenced entry, recompute its hash, append"""
        err = self._check(entry)
        if not err and h(canon({k: entry[k] for k in BODY})) != entry["hash"]:
            err = "hash mismatch"
        return (None, err) if err else (self._seal(entry), None)

    def audit(self) -> str:
        return audit_chain(self.chain)


def audit_chain(chain) -> str:
    """verify hashes and signatures of any chain copy (collectors and the overseer use the same check)"""
    prev = "0" * 64
    for i, e in enumerate(chain):
        if e["prev"] != prev or e["hash"] != h(canon({k: e[k] for k in BODY})):
            return f"TAMPERED at seq {i} (hash chain)"
        if any(not s or not verify(s, e["payload"], e["sigs"].get(s, "")) for s in Collector.signers(e)):
            return f"TAMPERED at seq {i} (signature)"
        prev = e["hash"]
    return "ok"


def contribution(chain) -> dict:
    """per author: distinct consumers who received their content, and how many of their contents were adopted"""
    author = {x["payload"]["content_hash"]: x["payload"]["author"] for x in chain if x["type"] == "publish"}
    got, adopted = defaultdict(set), defaultdict(int)
    for e in chain:
        p = e["payload"]
        if e["type"] == "share" and author.get(p["content_hash"]) != p["consumer"]:
            got[author[p["content_hash"]]].add(p["consumer"])
        if e["type"] == "feedback" and p.get("verdict") == "adopt":
            adopted[author[p["content_hash"]]] += 1
    return {a: {"received_by": len(got[a]), "adopted": adopted[a]} for a in set(got) | set(adopted) | set(author.values())}
