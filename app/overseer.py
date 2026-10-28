"""The all-seeing peer (절대자): a peer whose key is allow-listed to READ the ledger on every collector.

It cannot write, cannot see content (the ledger holds hashes, pseudonyms, signatures), and cannot re-identify anyone.
It verifies the chain copies itself, cross-checks the two collectors, and computes statistics.
The dashboard is just this peer's window: it has no other path to the ledger.
"""
import time
from collections import Counter

from .common import Identity, alias, emit, rpc
from .ledger import audit_chain, contribution


class Overseer:
    def __init__(self):
        self.id = Identity()
        self.collector_urls = []
        self._cache = (0.0, None)

    async def read(self, url, identity=None):
        who = identity or self.id
        ts = time.time()
        return await rpc(url, {"op": "read", "reader": who.pub, "ts": ts, "sig": who.sign({"op": "read", "ts": ts})})

    async def snapshot(self):
        if time.time() - self._cache[0] < 1.0 and self._cache[1]:
            return self._cache[1]
        c1 = await self.read(self.collector_urls[0])
        c2 = await self.read(self.collector_urls[1])  # read after c1: c2 may be ahead by in-flight entries, never behind
        if not (c1.get("ok") and c2.get("ok")):
            return {"error": c1.get("error") or c2.get("error")}
        a, b = c1["chain"], c2["chain"]
        n = min(len(a), len(b))
        first_diff = next((i for i in range(n) if a[i]["hash"] != b[i]["hash"]), None)
        integrity = {"collector-1": audit_chain(a), "collector-2": audit_chain(b), "first_diff": first_diff,
                     "lengths": [len(a), len(b)], "agree": first_diff is None and audit_chain(a) == "ok" and audit_chain(b) == "ok"}
        if not integrity["agree"] and not getattr(self, "_alerted", False):
            self._alerted = True
            emit("overseer", "절대자", f"원장 불일치/변조 탐지: {integrity}")
        snap = {"integrity": integrity, "ledger": self.rows(a), "stats": self.stats(a)}
        self._cache = (time.time(), snap)
        return snap

    @staticmethod
    def rows(chain):
        return [dict(seq=e["seq"], type=e["type"], hash=e["hash"][:10],
                     who=alias(e["payload"].get("author") or e["payload"].get("provider") or e["payload"].get("evaluator") or e["payload"].get("issuer"))) for e in chain]

    @staticmethod
    def stats(chain):
        types = Counter(e["type"] for e in chain)
        ideas = [e for e in chain if e["type"] == "publish"]
        scores = [e["payload"]["score"] for e in chain if e["type"] == "feedback" and e["payload"].get("verdict") == "review"]
        adopted = sum(1 for e in chain if e["type"] == "feedback" and e["payload"].get("verdict") == "adopt")
        flows = Counter((alias(e["payload"]["provider"]), alias(e["payload"]["consumer"])) for e in chain if e["type"] == "share")
        pubs = {p for e in chain for p in e["sigs"]}
        hist = Counter(int(s) for s in scores)
        return dict(
            entries=len(chain), by_type=dict(types), pseudonyms=len(pubs), ideas=len(ideas), adopted=adopted,
            adoption_rate=round(adopted / len(ideas), 2) if ideas else 0,
            reviews=len(scores), avg_score=round(sum(scores) / len(scores), 2) if scores else None,
            score_hist={str(k): hist[k] for k in sorted(hist)},
            top_flows=[dict(frm=f, to=t, n=n) for (f, t), n in flows.most_common(5)],
            contribution=[dict(who=alias(a), **v) for a, v in sorted(contribution(chain).items(), key=lambda kv: -(kv[1]["adopted"], kv[1]["received_by"])[0])],
            span_sec=round(chain[-1]["ts"] - chain[0]["ts"], 1) if chain else 0)
