"""The all-seeing peer (절대자): a peer whose key the recorder(s) have allow-listed to READ the ledger.

It discovers recorders through the broker like everyone else, reads their ledgers directly (p2p), verifies the
chain itself (hashes, participant signatures, recorder seals) and computes statistics. It cannot write, cannot see
content, cannot re-identify anyone. The dashboard is just this peer's window.
"""
import time
from collections import Counter

from .common import Identity, alias, emit, rpc
from .ledger import audit_chain, contribution


class Overseer:
    def __init__(self):
        self.id = Identity()
        self.broker_url, self.recorders = None, []  # [{alias, pub, peer_url}]
        self._cache, self._alerted = (0.0, None), False

    async def locate(self):
        """find peers offering the record role via the broker (discovery, then direct read)"""
        res = await rpc(self.broker_url, {"op": "find", "requester_pub": self.id.pub, "text": "원장 기록 역할(record)을 공개한 peer"})
        self.recorders = [p for p in res.get("peers", []) if "record" in p.get("offers", [])]
        return self.recorders

    async def read(self, url, identity=None):
        who = identity or self.id
        ts = time.time()
        return await rpc(url, {"op": "read", "reader": who.pub, "ts": ts, "sig": who.sign({"op": "read", "ts": ts})})

    async def snapshot(self):
        if time.time() - self._cache[0] < 1.0 and self._cache[1]:
            return self._cache[1]
        if not self.recorders and not await self.locate():
            return {"error": "no recorder found via broker"}
        copies = []
        for rec in self.recorders:  # one in the demo; the same code reads and cross-checks several
            r = await self.read(rec["peer_url"])
            if r.get("ok"):
                copies.append((rec, r["chain"]))
        if not copies:
            return {"error": "read denied"}
        integrity = {"recorders": [dict(who=c[0]["alias"], status=audit_chain(c[1]), length=len(c[1]),
                                        head=(c[1][-1]["hash"][:10] if c[1] else "-")) for c in copies]}
        heads = {c[1][-1]["hash"] if c[1] else "" for c in copies}
        integrity["agree"] = all(x["status"] == "ok" for x in integrity["recorders"]) and len(heads) == 1
        if not integrity["agree"] and not self._alerted:
            self._alerted = True
            emit("overseer", "절대자", f"원장 변조/불일치 탐지: {integrity}")
        chain = copies[0][1]
        profiles = []
        for url in getattr(self, "board_urls", [self.broker_url]):  # both peer groups
            ts = time.time()
            profiles += (await rpc(url, {"op": "list_profiles", "pub": self.id.pub, "ts": ts,
                                         "sig": self.id.sign({"op": "list_profiles", "ts": ts})})).get("profiles", [])
        snap = {"integrity": integrity, "ledger": self.rows(chain), "stats": self.stats(chain),
                "peers": self.per_peer(chain, profiles)}
        self._cache = (time.time(), snap)
        return snap

    @staticmethod
    def rows(chain):
        return [dict(seq=e["seq"], type=e["type"], hash=e["hash"][:10], sealed_by=alias(e["seal"]["pub"]) if "seal" in e else "-",
                     who=alias(e["payload"].get("author") or e["payload"].get("provider") or e["payload"].get("evaluator") or e["payload"].get("issuer"))) for e in chain]

    @staticmethod
    def per_peer(chain, profiles):
        """strengths = the public self-description on the board; track record = what the ledger proves for that pseudonym"""
        rec = {}
        def r(pub):
            return rec.setdefault(pub, {"ideas": 0, "received_by": set(), "adopted": 0, "reviews": 0, "roles": [], "sealed": 0})
        author = {e["payload"]["content_hash"]: e["payload"]["author"] for e in chain if e["type"] == "publish"}
        for e in chain:
            p = e["payload"]
            if e["type"] == "publish":
                r(p["author"])["ideas"] += 1
            elif e["type"] == "share" and author.get(p["content_hash"]) not in (None, p["consumer"]):
                r(author[p["content_hash"]])["received_by"].add(p["consumer"])
            elif e["type"] == "feedback" and p.get("verdict") == "adopt":
                r(author[p["content_hash"]])["adopted"] += 1
            elif e["type"] == "feedback" and p.get("verdict") == "review":
                r(p["evaluator"])["reviews"] += 1
            elif e["type"] == "contract":
                r(p["contractor"])["roles"].append({"record": "기록", "review": "심사"}.get(p["role"], p["role"]))
            if "seal" in e:
                r(e["seal"]["pub"])["sealed"] += 1
        out = []
        for a in profiles:
            t = rec.get(a["pub"], r(a["pub"]))
            out.append(dict(who=alias(a["pub"]), broker=a.get("broker", ""), ver=a.get("ver", 1), offers=a.get("offers", []),
                            strengths=a["summary"], ideas=t["ideas"], received_by=len(t["received_by"]), adopted=t["adopted"],
                            reviews=t["reviews"], roles=", ".join(sorted(set(t["roles"]))), sealed=t["sealed"]))
        return sorted(out, key=lambda x: (-x["adopted"], -x["received_by"], -len(x["roles"]), -x["reviews"], -x["ver"]))

    @staticmethod
    def stats(chain):
        types = Counter(e["type"] for e in chain)
        ideas = [e for e in chain if e["type"] == "publish"]
        scores = [e["payload"]["score"] for e in chain if e["type"] == "feedback" and e["payload"].get("verdict") == "review"]
        adopted = sum(1 for e in chain if e["type"] == "feedback" and e["payload"].get("verdict") == "adopt")
        flows = Counter((alias(e["payload"]["provider"]), alias(e["payload"]["consumer"])) for e in chain if e["type"] == "share")
        pubs = {p for e in chain for p in e["sigs"]}
        hist = Counter(int(s) for s in scores)
        contrib = contribution(chain)
        return dict(
            entries=len(chain), by_type=dict(types), pseudonyms=len(pubs), ideas=len(ideas), adopted=adopted,
            adoption_rate=round(adopted / len(ideas), 2) if ideas else 0,
            reviews=len(scores), avg_score=round(sum(scores) / len(scores), 2) if scores else None,
            score_hist={str(k): hist[k] for k in sorted(hist)},
            top_flows=[dict(frm=f, to=t, n=n) for (f, t), n in flows.most_common(5)],
            contribution=[dict(who=alias(a), **v) for a, v in sorted(contrib.items(), key=lambda kv: (-kv[1]["adopted"], -kv[1]["received_by"], -kv[1]["roles"]))],
            span_sec=round(chain[-1]["ts"] - chain[0]["ts"], 1) if chain else 0)
