"""Feasibility spike: hash-chained, dual-signed provenance ledger with 2 collectors.

Proves (in-process, no LLM, no network):
 - first publisher of a content hash wins; a later duplicate publish is rejected (priority)
 - every entry carries a timestamp, monotonic non-decreasing
 - replaying the same share entry is rejected (nonce)
 - publish/share/derive entries are signed by pseudonymous ed25519 keys
 - a share needs BOTH provider and consumer signatures, else rejected
 - a derive must reference parents that exist in the ledger
 - editing any past entry is detected (hash chain) and by comparing two collectors
 - contribution credit flows from derived/shared use back to original authors
Content itself is NOT on the ledger: only its SHA-256 (so content can be deleted).
"""
import copy
import hashlib
import json
import time
from collections import defaultdict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class Identity:
    def __init__(self, label):
        self.label = label
        self._k = Ed25519PrivateKey.generate()
        self.pub = self._k.public_key().public_bytes_raw().hex()  # pseudonym = public key

    def sign(self, payload) -> str:
        return self._k.sign(canon(payload)).hex()


def verify(pub_hex, payload, sig_hex) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(bytes.fromhex(sig_hex), canon(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


class Collector:
    def __init__(self, name):
        self.name, self.chain = name, []

    def head(self):
        return self.chain[-1]["hash"] if self.chain else "0" * 64

    def _required_signers(self, e):
        p = e["payload"]
        return {"publish": [p.get("author")], "derive": [p.get("author")],
                "share": [p.get("provider"), p.get("consumer")]}[e["type"]]

    def validate(self, e):
        if e["prev"] != self.head():
            return "bad prev hash"
        for signer in self._required_signers(e):
            sig = e["sigs"].get(signer)
            if not sig or not verify(signer, e["payload"], sig):
                return f"missing/invalid signature of {signer[:8]}"
        if self.chain and e["ts"] < self.chain[-1]["ts"]:
            return "timestamp goes backwards"
        known = {x["payload"]["content_hash"] for x in self.chain if "content_hash" in x["payload"]}
        if e["type"] in ("publish", "derive") and e["payload"]["content_hash"] in known:
            return "content already published (first publisher wins)"
        if e["type"] == "share" and any(x["type"] == "share" and x["payload"].get("nonce") == e["payload"].get("nonce") for x in self.chain):
            return "replay (nonce already used)"
        if e["type"] == "derive" and not all(p in known for p in e["payload"]["parents"]):
            return "unknown parent"
        if e["type"] == "share" and e["payload"]["content_hash"] not in known:
            return "unknown content"
        return None

    def append(self, e):
        err = self.validate(e)
        if err:
            return err
        body = copy.deepcopy({k: e[k] for k in ("type", "payload", "sigs", "prev", "ts")})  # each collector owns its copy
        e = dict(body, seq=len(self.chain), hash=h(canon(body)))
        self.chain.append(e)
        return None

    def audit(self):
        prev = "0" * 64
        for i, e in enumerate(self.chain):
            body = {k: e[k] for k in ("type", "payload", "sigs", "prev", "ts")}
            if e["prev"] != prev or e["hash"] != h(canon(body)):
                return f"TAMPERED at seq {i} (hash chain)"
            if any(not verify(signer, e["payload"], e["sigs"].get(signer, "")) for signer in self._required_signers(e)):
                return f"TAMPERED at seq {i} (signature)"
            prev = e["hash"]
        return "ok"


def entry(kind, payload, signers, prev):
    return {"type": kind, "payload": payload, "sigs": {s.pub: s.sign(payload) for s in signers}, "prev": prev, "ts": time.time()}


def cross_check(c1, c2):
    """compare two collectors entry by entry; returns first diverging seq or None"""
    for i, (a, b) in enumerate(zip(c1.chain, c2.chain)):
        if a["hash"] != b["hash"]:
            return i
    return None if len(c1.chain) == len(c2.chain) else min(len(c1.chain), len(c2.chain))


def submit(c1, c2, e):
    """collector 1 accepts, collector 2 independently validates & appends the same entry"""
    for c in (c1, c2):
        err = c.append(dict(e, prev=c.head()))  # same ts for both so hashes match
        if err:
            return f"{c.name}: {err}"
    return None


def contribution(chain):
    """credit = number of distinct consumers who used a content or any content derived from it"""
    parents = {}
    author = {}
    for e in chain:
        p = e["payload"]
        if e["type"] in ("publish", "derive"):
            author[p["content_hash"]] = p["author"]
            parents[p["content_hash"]] = p.get("parents", [])

    def ancestors(c, seen=None):
        seen = seen if seen is not None else set()
        for q in parents.get(c, []):
            if q not in seen:
                seen.add(q)
                ancestors(q, seen)
        return seen

    users = defaultdict(set)
    for e in chain:
        if e["type"] == "share":
            p = e["payload"]
            for c in {p["content_hash"]} | ancestors(p["content_hash"]):
                if author[c] != p["consumer"]:
                    users[author[c]].add(p["consumer"])
    return {a: len(u) for a, u in users.items()}


if __name__ == "__main__":
    A, B, C = Identity("A 플랫폼팀"), Identity("B 서비스팀"), Identity("C 신입")
    name = {i.pub: i.label for i in (A, B, C)}
    c1, c2 = Collector("collector-1"), Collector("collector-2")

    k_a = h("CI 캐시 설정 노하우(원문)".encode())
    k_b = h("A의 노하우를 우리 서비스에 적용한 변형".encode())
    print("publish A      :", submit(c1, c2, entry("publish", {"content_hash": k_a, "author": A.pub}, [A], "")))
    print("share A->B     :", submit(c1, c2, entry("share", {"content_hash": k_a, "provider": A.pub, "consumer": B.pub, "terms": "attribution", "nonce": "n1"}, [A, B], "")))
    print("derive B(A)    :", submit(c1, c2, entry("derive", {"content_hash": k_b, "author": B.pub, "parents": [k_a]}, [B], "")))
    print("share B->C     :", submit(c1, c2, entry("share", {"content_hash": k_b, "provider": B.pub, "consumer": C.pub, "terms": "attribution", "nonce": "n2"}, [B, C], "")))

    print("one-sided share:", submit(c1, c2, entry("share", {"content_hash": k_a, "provider": A.pub, "consumer": C.pub, "terms": "", "nonce": "n3"}, [A], "")))
    print("derive w/ fake parent:", submit(c1, c2, entry("derive", {"content_hash": h(b"x"), "author": C.pub, "parents": ["f" * 64]}, [C], "")))
    print("late duplicate publish (C re-publishes A's content):", submit(c1, c2, entry("publish", {"content_hash": k_a, "author": C.pub}, [C], "")))
    replay = entry("share", {"content_hash": k_a, "provider": A.pub, "consumer": B.pub, "terms": "attribution", "nonce": "n1"}, [A, B], "")
    print("replayed share :", submit(c1, c2, replay))
    print("audit c1/c2    :", c1.audit(), "/", c2.audit(), "| cross_check:", cross_check(c1, c2))
    print("credit         :", {name[a]: n for a, n in contribution(c1.chain).items()})

    # attack 1: edit history on collector-1 without fixing hashes
    c1.chain[1]["payload"]["terms"] = "none"
    print("tamper (naive) : c1 =", c1.audit(), "| c2 =", c2.audit(), "| cross_check diverges at:", cross_check(c1, c2))
    c1.chain[1]["payload"]["terms"] = "attribution"

    # attack 2: admin edits an entry AND recomputes every later hash so c1.audit() passes
    c1.chain[1]["payload"]["terms"] = "none"
    prev = c1.chain[0]["hash"]
    for e in c1.chain[1:]:
        e["prev"] = prev
        e["hash"] = h(canon({k: e[k] for k in ("type", "payload", "sigs", "prev", "ts")}))
        prev = e["hash"]
    print("tamper (rehash): c1.audit =", c1.audit(), "| cross_check diverges at:", cross_check(c1, c2), "<- caught twice: signatures no longer match the edited payload, and the other collector disagrees")
