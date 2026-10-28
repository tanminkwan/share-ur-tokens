"""Feasibility spike: hash-chained, dual-signed provenance ledger with 2 collectors.

Proves (in-process, no LLM, no network):
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
        known = {x["payload"]["content_hash"] for x in self.chain if "content_hash" in x["payload"]}
        if e["type"] == "derive" and not all(p in known for p in e["payload"]["parents"]):
            return "unknown parent"
        if e["type"] == "share" and e["payload"]["content_hash"] not in known:
            return "unknown content"
        return None

    def append(self, e):
        err = self.validate(e)
        if err:
            return err
        body = copy.deepcopy({k: e[k] for k in ("type", "payload", "sigs", "prev")})  # each collector owns its copy
        e = dict(body, seq=len(self.chain), hash=h(canon(body)))
        self.chain.append(e)
        return None

    def audit(self):
        prev = "0" * 64
        for i, e in enumerate(self.chain):
            body = {k: e[k] for k in ("type", "payload", "sigs", "prev")}
            if e["prev"] != prev or e["hash"] != h(canon(body)):
                return f"TAMPERED at seq {i}"
            prev = e["hash"]
        return "ok"


def entry(kind, payload, signers, prev):
    return {"type": kind, "payload": payload, "sigs": {s.pub: s.sign(payload) for s in signers}, "prev": prev}


def submit(c1, c2, e):
    """collector 1 accepts, collector 2 independently validates & appends the same entry"""
    for c in (c1, c2):
        err = c.append(dict(e, prev=c.head()))
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
    print("share A->B     :", submit(c1, c2, entry("share", {"content_hash": k_a, "provider": A.pub, "consumer": B.pub, "terms": "attribution"}, [A, B], "")))
    print("derive B(A)    :", submit(c1, c2, entry("derive", {"content_hash": k_b, "author": B.pub, "parents": [k_a]}, [B], "")))
    print("share B->C     :", submit(c1, c2, entry("share", {"content_hash": k_b, "provider": B.pub, "consumer": C.pub, "terms": "attribution"}, [B, C], "")))

    print("one-sided share:", submit(c1, c2, entry("share", {"content_hash": k_a, "provider": A.pub, "consumer": C.pub, "terms": ""}, [A], "")))
    print("derive w/ fake parent:", submit(c1, c2, entry("derive", {"content_hash": h(b"x"), "author": C.pub, "parents": ["f" * 64]}, [C], "")))
    print("audit c1/c2    :", c1.audit(), "/", c2.audit(), "| same head:", c1.head() == c2.head())
    print("credit         :", {name[a]: n for a, n in contribution(c1.chain).items()})

    c1.chain[1]["payload"]["terms"] = "none"  # an admin edits history on collector-1
    print("after tamper   : c1 =", c1.audit(), "| c2 =", c2.audit(), "| stored heads equal:", c1.head() == c2.head())
