"""Public body and private envelope (protocol 3, user 2026-11-03: "비공개 칸은 공개 본체와 비공개 봉투 방식으로 해").

An entry's `payload` is its public body: anyone may copy it. Fields that must not spread (who handed what to whom, a hidden
role's contractor, a writer's free fields) go in a private envelope; the body carries their hash in its `private`
column, so signing the body binds them. Signers whose very identity is private sign the body too, and their signatures
go in the envelope; the entry's hash covers the hash of those signatures (`private_sigs`). The recorder keeps the
envelope; the copy anyone may take is the public form (no envelope), still checkable: hash chain, seals, public
signatures. Rules run inside the recorder on the merged view (body + envelope), exactly as before."""
from __future__ import annotations

from ..crypto import canon, h

PRIVATE = "private"  # the body column holding the hash of the private fields
BODY = ("type", "payload", "sigs", "prev", "ts")


def private_hash(fields: dict) -> str:
    return h(canon(fields))


def with_private(public: dict, fields: dict | None) -> dict:
    """the body to sign: the public fields plus the hash of the private ones (unchanged when there are none)"""
    return dict(public, **{PRIVATE: private_hash(fields)}) if fields else dict(public)


def hash_body(e: dict) -> dict:
    """what an entry's hash covers"""
    return {**{k: e[k] for k in BODY}, **({"private_sigs": e["private_sigs"]} if "private_sigs" in e else {})}


def merged(e: dict) -> dict:
    """the full view of a stored entry (rules, the recorder's services): body + envelope fields, all signatures. The
    signatures stay checkable against `signed_payload`, the body"""
    env = e.get("envelope")
    if not env:
        return e
    return dict(e, payload={**e["payload"], **env.get("fields", {})}, sigs={**e["sigs"], **env.get("sigs", {})}, signed_payload=e["payload"])


def stored(e: dict) -> dict:
    """the stored form of an entry given either form (a merged view is turned back: body, public signatures, envelope)"""
    if "signed_payload" not in e:
        return e
    env = e.get("envelope") or {}
    priv = set(env.get("sigs", {}))
    out = {k: v for k, v in e.items() if k != "signed_payload"}
    return dict(out, payload=e["signed_payload"], sigs={k: v for k, v in e["sigs"].items() if k not in priv})


def public_form(e: dict) -> dict:
    """the entry as anyone may copy it: no envelope"""
    return {k: v for k, v in e.items() if k not in ("envelope", "signed_payload")}


def body_of(full: dict, body: dict) -> dict | None:
    """the private fields if `body` is exactly the public body of `full` (the rest of `full`, committed by the body's
    `private` hash), else None. Lets a co-signer check what it is shown before signing the body"""
    rest = {k: v for k, v in full.items() if k not in body}
    if any(full.get(k) != v for k, v in body.items() if k != PRIVATE):
        return None
    if rest:
        return rest if body.get(PRIVATE) == private_hash(rest) else None
    return {} if PRIVATE not in body else None
