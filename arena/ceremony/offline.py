"""The offline side of the ceremony (P8-A1, P8-A3): make the god key and sign requests, on a machine with no network.
This module speaks no HTTP: it imports nothing that does (a test keeps it so). The god key is kept only in the
existing encrypted key-backup format (arena/keys/backup.py), never as a plaintext key file."""
from __future__ import annotations

import json
import os

from ..crypto import Identity
from ..keys.backup import open_backup, seal_backup
from . import formats as F

GOD_KEY, GOD_PUB = "god-key.json", "god.pub"


def write_private(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def make_god_key(out_dir: str, passphrase: str, settings) -> str:
    """a new god key, sealed with the passphrase in <out>/god-key.json; its public key in <out>/god.pub. Never overwrites"""
    for name in (GOD_KEY, GOD_PUB):
        if os.path.exists(os.path.join(out_dir, name)):
            raise FileExistsError(f"{name} already exists in {out_dir}: a god key is made once")
    god = Identity.generate()
    write_private(os.path.join(out_dir, GOD_KEY), json.dumps(seal_backup(god, passphrase, settings), indent=2) + "\n")
    with open(os.path.join(out_dir, GOD_PUB), "w", encoding="utf-8") as f:
        f.write(god.pub + "\n")
    return god.pub


def open_god_key(path: str, passphrase: str, settings) -> Identity:
    with open(path, encoding="utf-8") as f:
        return open_backup(json.load(f), passphrase, settings)["current"]


def read_pub(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        pub = f.read().strip()
    if len(pub) != 64 or any(c not in "0123456789abcdef" for c in pub):
        raise ValueError(f"{path} does not hold a public key")
    return pub


SHOWN = {"genesis": ("group_id", "god", "broker", "recorder", "parent"), "key_rotate": ("role", "old", "new", "god", "ledger_id"),
         "chain_link": ("name", "child_ledger_id", "child_god", "child_recorder", "branch_point", "ledger_id"),
         "parent_link": ("god", "ledger_id", "link")}


def _short(v) -> str:
    if isinstance(v, str):
        return v if len(v) <= 20 else v[:16] + "…"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_short(x)}" for k, x in v.items() if k in ("ledger_id", "seq", "hash", "recorder")) + "}"
    return json.dumps(v, ensure_ascii=False)


def describe(req: dict, me: str | None = None) -> list[str]:
    """what the person at the offline machine reads before signing: the round, the chain, and each item's main fields"""
    err = F.request_error(req)
    if err:
        raise ValueError(err)
    out = [f"round {req['round']} · chain {req['chain']} · ledger_id {_short(req.get('ledger_id') or '(not yet)')}"]
    for x in req["items"]:
        mark = "sign" if me in x["signers"] else "other key signs"
        out.append(f"- {x['name']} ({x['type']}) [{mark}]")
        p = x["payload"]
        out += [f"    {k}: {_short(p[k])}" for k in SHOWN.get(x["type"], sorted(p)) if k in p]
    return out
