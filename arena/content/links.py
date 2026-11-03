"""Permanent links (user 2026-11-03): "원장은 변하지 않고 물리적인 link만 변할 수 있도록". The ledger names a link (a link
peer's public key and a link id) that never changes; the link peer keeps where the content is now. Only the publisher
changes it: every version is signed by the owner (or the owner's current key, following key rotation on the ledger),
so a link peer cannot change a link either, only keep it or lose it. Anyone may run a link peer; it earns standing by
being used, and a work may name several.

    link record: {id, owner, name, ver, targets: [{kind, location, via?}], content_hash?, ts, signer, sig}
    id  = SHA-256(canonical JSON {"owner", "name"})[:32]      (computable before the link exists)
    sig = signer's signature over canonical JSON {"op": "link.set", id, owner, name, ver, targets, content_hash?, ts}"""
from __future__ import annotations

from typing import Awaitable, Callable

from ..crypto import canon, h, verify
from ..ledger.refs import STORAGE_KINDS

KeyOf = Callable[[str], Awaitable[dict]]  # a recorder's key status (GET /key/{pub})


def link_id(owner: str, name: str) -> str:
    return h(canon({"owner": owner, "name": name}))[:32]


def signed_part(rec: dict) -> dict:
    return {"op": "link.set", **{k: rec[k] for k in ("id", "owner", "name", "ver", "targets", "ts")},
            **({"content_hash": rec["content_hash"]} if rec.get("content_hash") else {})}


def make_link(me, owner: str, name: str, ver: int, targets: list[dict], ts: float, content_hash: str | None = None) -> dict:
    rec = {"id": link_id(owner, name), "owner": owner, "name": name, "ver": ver, "targets": list(targets), "ts": ts,
           **({"content_hash": content_hash} if content_hash else {}), "signer": me.pub}
    rec["sig"] = me.sign(signed_part(rec))
    return rec


def targets_error(targets, settings) -> str | None:
    if not isinstance(targets, list) or not targets or len(targets) > settings.ref_storage_max:
        return f"a link needs 1 to {settings.ref_storage_max} targets"
    for t in targets:
        if not isinstance(t, dict) or t.get("kind") not in STORAGE_KINDS or t["kind"] == "link":
            return "each target needs a registered storage kind other than link"
        if not isinstance(t.get("location"), str) or not t["location"] or len(t["location"]) > settings.ref_location_max:
            return f"each target needs a location of at most {settings.ref_location_max} characters"
        check = STORAGE_KINDS[t["kind"]].check
        if check and check(t["location"]):
            return check(t["location"])
    return None


def record_error(rec: dict, settings) -> str | None:
    """the shape, the id and the signature of one link version (who may sign is signer_allowed)"""
    if not isinstance(rec, dict) or not all(k in rec for k in ("id", "owner", "name", "ver", "targets", "ts", "signer", "sig")):
        return "a link record needs id, owner, name, ver, targets, ts, signer and sig"
    if not isinstance(rec["ver"], int) or isinstance(rec["ver"], bool) or rec["ver"] < 1:
        return "ver is a version number from 1"
    if rec["id"] != link_id(rec["owner"], rec["name"]):
        return "the id is not the one the owner and the name give"
    bad = targets_error(rec["targets"], settings)
    if bad:
        return bad
    if not verify(rec["signer"], signed_part(rec), rec["sig"]):
        return "the link version's signature does not verify"
    return None


async def signer_allowed(owner: str, signer: str, key_of: KeyOf | None) -> bool:
    """the identity's current key. Without a recorder to ask, only the owner's own key; with one, the key that key
    rotation on the ledger made current (so a stolen key rotated away can no longer move the owner's links)"""
    if key_of is None:
        return signer == owner
    st = await key_of(owner)
    return signer == st.get("current", owner) and (signer == owner or owner in st.get("lineage", []))


async def verify_link(rec: dict, settings, expected_owner: str | None = None, key_of: KeyOf | None = None) -> str | None:
    """None when this is a link version its owner signed (and, if given, the owner is who the ledger says)"""
    bad = record_error(rec, settings)
    if bad:
        return bad
    if expected_owner and rec["owner"] != expected_owner:
        return "the link belongs to someone other than the work's author"
    if not await signer_allowed(rec["owner"], rec["signer"], key_of):
        return "the link version is not signed by its owner (or the owner's current key)"
    return None
