"""The files a ceremony passes around (dev/phase8/design.md 3). Pure functions: no network, no files, no clock.

    request     {format: arena-ceremony-request, version, round, chain, ledger_id, god, items: [{name, type, payload, signers}], made_at}
    signatures  {format: arena-ceremony-signatures, version, round, request (the request's hash), signer, sigs: {item name: sig}}
    retirement  {format: arena-key-retirement, version, body: {key, role, ledger_id, handover, head: {seq, hash}, method, at,
                 witnesses, note}, sigs: {witness: sig over canon(body)}}

Every hash and signature is over canonical JSON. A request item names the keys that must sign it offline (`signers`): god for
entry 0 and a recorder handover, the old and the new god key for a god handover."""
from __future__ import annotations

from ..crypto import Identity, canon, h, verify

VERSION = 1
REQUEST, SIGNATURES, RETIREMENT = "arena-ceremony-request", "arena-ceremony-signatures", "arena-key-retirement"
CHAINS = ("trunk", "branch")
ROLES = ("recorder", "god")
METHODS = {"memory-only": "the key was never written to a disk: it lived in the ceremony process and ended with it",
           "file-wiped": "the key file was overwritten and removed (not guaranteed on SSDs and copy-on-write file systems)"}
BODY_FIELDS = ("key", "role", "ledger_id", "handover", "head", "method", "at", "witnesses", "note")


def _hex64(x) -> bool:
    return isinstance(x, str) and len(x) == 64 and all(c in "0123456789abcdef" for c in x)


# ---------------- signing requests ----------------
def item(name: str, kind: str, payload: dict, signers: list[str]) -> dict:
    return {"name": name, "type": kind, "payload": payload, "signers": list(signers)}


def request(round_: int, chain: str, ledger_id: str | None, god: str, items: list[dict], made_at: float) -> dict:
    if chain not in CHAINS:
        raise ValueError(f"chain must be one of {CHAINS}")
    names = [x["name"] for x in items]
    if not items or len(set(names)) != len(names):
        raise ValueError("a request holds at least one item, each with its own name")
    return {"format": REQUEST, "version": VERSION, "round": round_, "chain": chain, "ledger_id": ledger_id, "god": god,
            "items": [dict(x) for x in items], "made_at": made_at}


def request_hash(req: dict) -> str:
    return h(canon(req))


def request_error(req) -> str | None:
    if not isinstance(req, dict) or req.get("format") != REQUEST or req.get("version") != VERSION:
        return "not a ceremony request of a known version"
    if not isinstance(req.get("round"), int) or req.get("chain") not in CHAINS or not _hex64(req.get("god")):
        return "a request needs round, chain and god"
    items = req.get("items")
    if not isinstance(items, list) or not items:
        return "a request needs items"
    for x in items:
        if not isinstance(x, dict) or not isinstance(x.get("name"), str) or not isinstance(x.get("type"), str) \
                or not isinstance(x.get("payload"), dict) or not x.get("signers") or not all(_hex64(p) for p in x["signers"]):
            return "every item needs name, type, payload and signers"
    return None


def sign(req: dict, key: Identity) -> dict:
    """what one offline key returns: its signature on every item it is a signer of"""
    err = request_error(req)
    if err:
        raise ValueError(err)
    mine = {x["name"]: key.sign(x["payload"]) for x in req["items"] if key.pub in x["signers"]}
    if not mine:
        raise ValueError("this key signs nothing in this request")
    return {"format": SIGNATURES, "version": VERSION, "round": req["round"], "request": request_hash(req), "signer": key.pub, "sigs": mine}


def collect(req: dict, docs: list[dict]) -> tuple[dict | None, str | None]:
    """the signatures of every item from the signature files, checked: {item name: {signer: sig}}, or why not"""
    err = request_error(req)
    if err:
        return None, err
    want = request_hash(req)
    got: dict = {x["name"]: {} for x in req["items"]}
    for d in docs:
        if not isinstance(d, dict) or d.get("format") != SIGNATURES or d.get("version") != VERSION:
            return None, "not a ceremony signature file of a known version"
        if d.get("round") != req["round"] or d.get("request") != want:
            return None, "these signatures are for another request"
        signer, sigs = d.get("signer"), d.get("sigs")
        if not isinstance(sigs, dict):
            return None, "signatures missing"
        for name, sig in sigs.items():
            x = next((i for i in req["items"] if i["name"] == name), None)
            if x is None or signer not in x["signers"]:
                return None, f"{signer!s:.12} does not sign {name}"
            if not isinstance(sig, str) or not verify(signer, x["payload"], sig):
                return None, f"bad signature on {name}"
            got[name][signer] = sig
    for x in req["items"]:
        missing = [p for p in x["signers"] if p not in got[x["name"]]]
        if missing:
            return None, f"{x['name']} still needs the signature of {missing[0]:.12}"
    return got, None


# ---------------- the retirement declaration ----------------
def declaration(key: str, role: str, ledger_id: str, handover: str, head: dict, method: str, at: float,
                witnesses: list[str], note: str = "") -> dict:
    body = {"key": key, "role": role, "ledger_id": ledger_id, "handover": handover, "head": {"seq": head["seq"], "hash": head["hash"]},
            "method": method, "at": at, "witnesses": list(witnesses), "note": note}
    return {"format": RETIREMENT, "version": VERSION, "body": body, "sigs": {}}


def declaration_hash(d: dict) -> str:
    """what the ledger keeps (publish, purpose retirement): the hash of the body; the signatures are not part of it"""
    return h(canon(d["body"]))


def declaration_error(d, min_witnesses: int, note_max: int) -> str | None:
    """the shape and the witnesses' signatures; not whether the ledger agrees (that is verify's work)"""
    if not isinstance(d, dict) or d.get("format") != RETIREMENT or d.get("version") != VERSION:
        return "not a key retirement declaration of a known version"
    b, sigs = d.get("body"), d.get("sigs")
    if not isinstance(b, dict) or set(b) != set(BODY_FIELDS) or not isinstance(sigs, dict):
        return f"the body has exactly {', '.join(BODY_FIELDS)}"
    if not _hex64(b["key"]) or b["role"] not in ROLES or not _hex64(b["ledger_id"]) or not _hex64(b["handover"]):
        return "key, role, ledger_id and handover are dedicated fields: keys and hashes"
    if not isinstance(b["head"], dict) or set(b["head"]) != {"seq", "hash"} or not isinstance(b["head"]["seq"], int) \
            or not _hex64(b["head"]["hash"]):
        return "head is {seq, hash}"
    if b["method"] not in METHODS:
        return f"method must be one of {', '.join(METHODS)}"
    if not isinstance(b["at"], (int, float)) or not isinstance(b["note"], str) or len(b["note"].encode("utf-8")) > note_max:
        return f"at is a time and note a short text (at most {note_max} bytes)"
    w = b["witnesses"]
    if not isinstance(w, list) or not all(_hex64(x) for x in w) or len(set(w)) != len(w) or b["key"] in w:
        return "witnesses are distinct public keys, not the retired key"
    if len(w) < min_witnesses:
        return f"at least {min_witnesses} witnesses"
    for pub, sig in sigs.items():
        if pub not in w:
            return f"{pub:.12} is not a named witness"
        if not isinstance(sig, str) or not verify(pub, b, sig):
            return f"bad signature by {pub:.12}"
    unsigned = [x for x in w if x not in sigs]
    if unsigned:
        return f"{len(unsigned)} witness(es) have not signed yet"
    return None


def witness_sign(d: dict, me: Identity) -> dict:
    if me.pub not in d["body"]["witnesses"]:
        raise ValueError("this key is not a named witness of this declaration")
    out = dict(d, sigs=dict(d["sigs"]))
    out["sigs"][me.pub] = me.sign(d["body"])
    return out
