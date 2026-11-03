"""A peer's key succession on the ledger (P6-K3, user 2026-11-03).

- key_commit: a peer promises its next key in advance by its hash (`next`), and may name key peers that can recover
  the key (`recovery`). Once per key: changing the promise takes a rotation, which needs the next key.
- peer_rotate: the identity moves to a new key. `by: "next"`: the new key is the promised one (its hash is `next`), so
  a thief holding only the current key cannot rotate. `by: "recovery"`: a key peer the owner named in advance signs
  (after its own check of the person), for a key lost together with its backup. Either way the new entry promises the
  following key. The new key signs; the old key's signature is not needed (it may be lost or stolen).
- after a rotation the ledger refuses anything signed by the old key (rules.r_retired_key).

The keys are made by the peer itself (arena/keys). Records follow the identity: a recorder's track of a key counts
every key of its line (recorder/service.py). Policy: dev/phase6/requirements.md 6-K."""
from __future__ import annotations

from ..crypto import h
from .types import EntryType, _is_hex64, register_entry_type

BY = ("next", "recovery")


def key_commitment(pub: str) -> str:
    """the hash a peer promises for its next key: sha256 of the public key's hex text (UTF-8)"""
    return h(pub.encode("utf-8"))


def succession(chain) -> dict:
    """{"active": {pub: {next, recovery}}, "retired": {old: new}, "before": {new: old}} from key_commit and peer_rotate"""
    active, retired, before = {}, {}, {}
    for e in chain:
        p = e["payload"]
        if e["type"] == "key_commit":
            active[p["pub"]] = {"next": p["next"], "recovery": list(p.get("recovery", []))}
        elif e["type"] == "peer_rotate":
            active.pop(p["old"], None)
            retired[p["old"]], before[p["new"]] = p["new"], p["old"]
            active[p["new"]] = {"next": p["next"], "recovery": list(p.get("recovery", []))}
    return {"active": active, "retired": retired, "before": before}


def lineage(chain, pub: str, s: dict | None = None) -> list[str]:
    """every key of the identity `pub` belongs to, first to latest"""
    s = s or succession(chain)
    first = pub
    while first in s["before"]:
        first = s["before"][first]
    line = [first]
    while line[-1] in s["retired"]:
        line.append(s["retired"][line[-1]])
    return line


def key_status(chain, pub: str) -> dict:
    s = succession(chain)
    line = lineage(chain, pub, s)
    last = line[-1]
    status = "retired" if pub in s["retired"] else "current" if pub in s["active"] else "unknown"
    return {"pub": pub, "status": status, "current": last if last in s["active"] else pub, "lineage": line,
            **({"next": s["active"][last]["next"], "recovery": s["active"][last]["recovery"]} if last in s["active"] else {})}


def known(s: dict, pub: str) -> bool:
    return pub in s["active"] or pub in s["retired"]


def _recovery_error(p: dict, own: str, settings) -> str | None:
    r = p.get("recovery", [])
    if not isinstance(r, list) or not all(isinstance(x, str) and x for x in r) or len(set(r)) != len(r):
        return "recovery must be a list of distinct key peer public keys"
    if len(r) > settings.key_recovery_max:
        return f"at most {settings.key_recovery_max} key peers may be named for recovery"
    if own in r:
        return "a key cannot be named for its own recovery"
    return None


def _commit_shape(chain, e, now, s):
    p = e["payload"]
    if not isinstance(p.get("pub"), str) or not p["pub"] or not _is_hex64(p.get("next")):
        return "key_commit needs pub and next (the hash of the next public key)"
    return _recovery_error(p, p["pub"], s)


def _commit_rule(chain, e, now, s):
    if known(succession(chain), e["payload"]["pub"]):
        return "this key already has a promise or is part of a key line: change it by rotating"


def _rotate_shape(chain, e, now, s):
    p = e["payload"]
    if not all(isinstance(p.get(k), str) and p.get(k) for k in ("old", "new")) or p["old"] == p["new"] or not _is_hex64(p.get("next")):
        return "peer_rotate needs old, new (different) and next (the hash of the key after new)"
    if p.get("by") not in BY:
        return "peer_rotate by must be next or recovery"
    if p["by"] == "recovery" and (not isinstance(p.get("recoverer"), str) or not p["recoverer"] or p["recoverer"] in (p["old"], p["new"])):
        return "a recovery names the recovering key peer (recoverer), not one of the two keys"
    return _recovery_error(p, p["new"], s)


def _rotate_rule(chain, e, now, s):
    p, st = e["payload"], succession(chain)
    if p["old"] not in st["active"]:
        return "old is not a current key with a promised next key (key_commit first)" if p["old"] not in st["retired"] else \
            "old was already rotated"
    if known(st, p["new"]):
        return "the new key is already part of a key line"
    promise = st["active"][p["old"]]
    if p["by"] == "next" and key_commitment(p["new"]) != promise["next"]:
        return "the new key is not the one promised (its hash differs from next)"
    if p["by"] == "recovery" and p["recoverer"] not in promise["recovery"]:
        return "the recoverer was not named for recovery by this key line"


def retired_signer(chain, signers: list) -> str | None:
    retired = succession(chain)["retired"]
    who = next((x for x in signers if x in retired), None)
    return f"signed by a retired key {who[:8]} (rotated to {retired[who][:8]})" if who else None


register_entry_type(EntryType("key_commit", lambda p: [p.get("pub")], shape=_commit_shape, rules=(_commit_rule,),
                              public=lambda p, c: {"pub": p["pub"], "next": p["next"], "recovery": list(p.get("recovery", []))}))
register_entry_type(EntryType("peer_rotate", lambda p: [p.get("new"), *([p.get("recoverer")] if p.get("by") == "recovery" else [])],
                              unique_nonce=True, shape=_rotate_shape, rules=(_rotate_rule,),
                              public=lambda p, c: {k: p.get(k) for k in ("old", "new", "next", "by", "recoverer", "recovery") if k in p}))
