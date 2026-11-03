"""The peer side of key succession (P6-K3): the entries a peer writes about its own keys. The ledger rules are in
arena/ledger/peer_keys.py. Every key here is made by the peer itself (Identity.generate on this device)."""
from __future__ import annotations

import os

from ..crypto import Identity
from ..ledger.peer_keys import key_commitment


def _common(group_id: str, ledger_id: str | None) -> dict:
    return {"group_id": group_id, **({"ledger_id": ledger_id} if ledger_id else {})}


def commit_entry(me: Identity, next_key: Identity, group_id: str, ledger_id: str | None, recovery: list[str] = ()) -> tuple[dict, dict]:
    """key_commit: promise the next key (by its hash) and name the key peers that may recover this identity"""
    p = {"pub": me.pub, "next": key_commitment(next_key.pub), "recovery": list(recovery), **_common(group_id, ledger_id)}
    return p, {me.pub: me.sign(p)}


def rotate_entry(old_pub: str, new: Identity, following: Identity, group_id: str, ledger_id: str | None,
                 recovery: list[str] = ()) -> tuple[dict, dict]:
    """peer_rotate by the promised next key: `new` was promised; it promises `following` in turn"""
    p = {"old": old_pub, "new": new.pub, "next": key_commitment(following.pub), "by": "next", "recovery": list(recovery),
         "nonce": os.urandom(8).hex(), **_common(group_id, ledger_id)}
    return p, {new.pub: new.sign(p)}


def recovery_entry(old_pub: str, new_pub: str, following_pub: str, recoverer: str, group_id: str, ledger_id: str | None,
                   recovery: list[str] = (), nonce: str | None = None) -> dict:
    """peer_rotate by recovery: the payload the recovering key peer and the new key both sign"""
    return {"old": old_pub, "new": new_pub, "next": key_commitment(following_pub), "by": "recovery", "recoverer": recoverer,
            "recovery": list(recovery), "nonce": nonce or os.urandom(8).hex(), **_common(group_id, ledger_id)}
