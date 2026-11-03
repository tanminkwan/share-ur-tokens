"""python -m arena.keys <command> --home <peer home> ...   (a peer's own keys, 6-K)

    register --recorder URL [--key-peer URL --key-peer-recovers] [--recovery PUB ...] [--backup-file F]
    rotate   --recorder URL (--backup-file F | --key-peer URL)        the promised next key takes over (stolen key)
    recover  --recorder URL --key-peer URL --old PUB                  lost key and backup: the named key peer signs
    restore  (--backup-file F | --key-peer URL --pub PUB) [--force]    same key on a new device
    where                                                             where this peer's key is kept
    status   --recorder URL --pub PUB

The passphrase (and the key peer's recovery secret) are asked for, or read from the environment variables named by
--passphrase-env and --secret-env (for scripts). They are never printed. Run it while the peer is stopped: the key
changes under the peer's home."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys

from ..config import Settings
from ..peer.home import PeerHome
from .flows import KeyFlows


def _secret(env_name: str | None, prompt: str) -> str:
    if env_name:
        v = os.environ.get(env_name)
        if v is None:
            raise SystemExit(f"{env_name} is not set")
        return v
    return getpass.getpass(prompt)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m arena.keys", description="a peer's own keys: register, rotate, recover, restore")
    ap.add_argument("command", choices=["register", "rotate", "recover", "restore", "where", "status"])
    ap.add_argument("--home", help="the peer's home folder (default: ARENA_PERSONAL_PEER_HOME)")
    ap.add_argument("--recorder", help="the recorder API address")
    ap.add_argument("--key-peer", help="the key peer's address")
    ap.add_argument("--key-peer-recovers", action="store_true", help="name the key peer for recovery (register)")
    ap.add_argument("--recovery", action="append", default=[], help="a key peer public key named for recovery (register)")
    ap.add_argument("--backup-file", help="write (register, rotate, recover) or read (rotate, restore) the encrypted backup here")
    ap.add_argument("--old", help="the lost key (recover)")
    ap.add_argument("--pub", help="a public key (restore from a key peer, status)")
    ap.add_argument("--force", action="store_true", help="replace another key in this home (restore)")
    ap.add_argument("--passphrase-env", help="read the backup passphrase from this environment variable")
    ap.add_argument("--secret-env", help="read the key peer's recovery secret from this environment variable")
    return ap


async def run(a, s: Settings, out=sys.stdout) -> int:
    from ..a2a import A2ATransport
    from ..recorder.client import RecorderClient
    home = PeerHome(a.home or s.personal_peer_home, s)
    recorder = RecorderClient(a.recorder, s) if a.recorder else None
    ask = (lambda msg: A2ATransport(s).call(a.key_peer, msg)) if a.key_peer else None
    flows = KeyFlows(s, home.key_store(), home.key_name(), recorder, ask)
    need_secret = bool(a.key_peer)
    if a.command == "where":
        r = {"ok": True, "where": home.key_store().where(home.key_name())}
    elif a.command == "status":
        r = await recorder.key(a.pub)
    else:
        read = lambda: json.load(open(a.backup_file, encoding="utf-8")) if a.backup_file else None
        passphrase = _secret(a.passphrase_env, "backup passphrase: ")
        secret = _secret(a.secret_env, "key peer recovery secret: ") if need_secret else None
        if a.command == "register":
            r = await flows.register(passphrase, a.recovery, secret, a.key_peer_recovers)
        elif a.command == "rotate":
            r = await flows.rotate(passphrase, read(), secret)
        elif a.command == "recover":
            r = await flows.recover(a.old, passphrase, secret)
        else:
            b = read()
            if b is None:
                got = await flows.fetch(a.pub, secret)
                if not got.get("ok"):
                    r = got
                b = got.get("backup")
            r = flows.restore(b, passphrase, a.force) if b else r
        if r.get("ok") and r.get("backup") and a.backup_file and a.command != "restore":
            with open(a.backup_file, "w", encoding="utf-8") as f:
                json.dump(r["backup"], f, ensure_ascii=False, indent=2)
    shown = {k: v for k, v in r.items() if k != "backup"}
    out.write(json.dumps(shown, ensure_ascii=False, indent=2) + "\n")
    return 0 if r.get("ok") else 1


def main(argv=None) -> None:
    a = parser().parse_args(argv)
    raise SystemExit(asyncio.run(run(a, Settings.load())))
