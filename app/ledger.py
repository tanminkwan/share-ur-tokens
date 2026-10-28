"""Hash-chained, signed provenance ledger kept by a peer in the "record" role. Content never goes on-chain,
only hashes + pseudonyms + signatures. Each sealed entry also carries the recorder's own signature over its hash.

Entry types
  contract signers: issuer + contractor   -> a role (e.g. reviewer) granted for one event; later reviews depend on it
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
    def __init__(self, name: str, identity=None):
        self.name, self.chain, self.identity = name, [], identity  # identity: the recorder peer's key (seals entries)

    def head(self) -> str:
        return self.chain[-1]["hash"] if self.chain else "0" * 64

    @staticmethod
    def signers(e) -> list:
        p = e["type"], e["payload"]
        t, p = p
        return {"publish": [p.get("author")], "share": [p.get("provider"), p.get("consumer")],
                "feedback": [p.get("evaluator")], "contract": [p.get("issuer"), p.get("contractor")]}[t]

    def _check(self, e):
        if e["type"] not in ("publish", "share", "feedback", "contract"):
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
        if e["type"] in ("share", "contract") and any(x["type"] == e["type"] and x["payload"].get("nonce") == p.get("nonce") for x in self.chain):
            return "replay (nonce already used)"
        if e["type"] == "contract" and p.get("role") not in ("review", "record"):
            return "unsupported role"
        if e["type"] == "feedback" and any(
                x["type"] == "feedback" and x["payload"]["evaluator"] == p["evaluator"] and x["payload"]["content_hash"] == ch
                and x["payload"].get("verdict") == p.get("verdict") for x in self.chain):
            return "duplicate feedback (one verdict per evaluator per content)"
        if e["type"] == "feedback" and p.get("verdict") == "review" and not any(
                x["type"] == "contract" and x["payload"]["call_id"] == p.get("call_id") and x["payload"]["contractor"] == p["evaluator"]
                for x in self.chain):
            return "no review contract for this call"
        if e["type"] == "feedback" and not any(
                x["type"] == "share" and x["payload"]["content_hash"] == ch and x["payload"]["consumer"] == p["evaluator"]
                for x in self.chain):
            return "evaluator never received this content"
        return None

    def _seal(self, e):
        body = copy.deepcopy({k: e[k] for k in BODY})
        e = dict(body, seq=len(self.chain), hash=h(canon(body)))
        if self.identity:  # recorder's seal: proves which recorder sealed this entry
            e["seal"] = {"pub": self.identity.pub, "sig": self.identity.sign(e["hash"])}
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
        if "seal" in e and not verify(e["seal"]["pub"], e["hash"], e["seal"]["sig"]):
            return f"TAMPERED at seq {i} (recorder seal)"
        prev = e["hash"]
    return "ok"


def contribution(chain) -> dict:
    """per pseudonym: distinct consumers who received their content, adopted contents, and roles served (contracts).
    Role service counts too: discovery/recording/reviewing are contributions and the basis for rewards."""
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
