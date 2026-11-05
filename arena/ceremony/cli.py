"""python -m arena.ceremony <command>   (dev/phase8: making and retiring the root keys)

  offline machine (no network):
    god-key  --out DIR                                     the god key, sealed with a passphrase (god-key.json), and god.pub
    sign     --key god-key.json --request R --out S        show the request, ask, sign
  ceremony machine:
    run      --god-pub FILE --out DIR --witness PUB --witness PUB [--parent URL --name NAME] [--note TEXT]
  witnesses and anyone:
    witness  --declaration F (--home DIR | --key-file F)   a named witness signs the retirement declaration
    publish  --declaration F (--home | --key-file) --recorder URL     its hash on the ledger (publish + retirement)
    verify   --declaration F --recorder URL
  later, on a stopped genesis folder:
    rotate-request --dir DIR  /  rotate --dir DIR --request R --signatures S        operating recorder key -> next
    rotate-god-request --dir DIR --new-god-pub FILE  /  rotate-god --dir DIR --request R --signatures S1 S2

Passphrases are asked for, or read from the environment variable named by --passphrase-env (scripts, tests). They and
the private keys are never printed. Imports are per command, so the offline commands load no networking code."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys

from ..config import Settings


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m arena.ceremony", description="making and retiring the root keys (dev/phase8)")
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("god-key")
    c.add_argument("--out", required=True)
    c.add_argument("--passphrase-env")
    c = sub.add_parser("sign")
    c.add_argument("--key", required=True)
    c.add_argument("--request", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--yes", action="store_true", help="do not ask (scripts and tests; the request is still shown)")
    c.add_argument("--passphrase-env")
    c = sub.add_parser("run")
    c.add_argument("--god-pub", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--witness", action="append", default=[], help="a witness's public key (repeat)")
    c.add_argument("--parent", help="the trunk recorder's API address: this ceremony starts a branch chain")
    c.add_argument("--name", help="the branch's name in its chain_link")
    c.add_argument("--note", default="")
    for name in ("witness", "publish"):
        c = sub.add_parser(name)
        c.add_argument("--declaration", required=True)
        c.add_argument("--home")
        c.add_argument("--key-file")
        if name == "publish":
            c.add_argument("--recorder", required=True)
        else:
            c.add_argument("--yes", action="store_true")
    c = sub.add_parser("verify")
    c.add_argument("--declaration", required=True)
    c.add_argument("--recorder", required=True)
    c = sub.add_parser("rotate-request")
    c.add_argument("--dir", required=True)
    c = sub.add_parser("rotate-god-request")
    c.add_argument("--dir", required=True)
    c.add_argument("--new-god-pub", required=True)
    for name in ("rotate", "rotate-god"):
        c = sub.add_parser(name)
        c.add_argument("--dir", required=True)
        c.add_argument("--request", required=True)
        c.add_argument("--signatures", nargs="+", required=True)
    return ap


def _passphrase(env_name: str | None, prompt: str, twice: bool = False) -> str:
    if env_name:
        v = os.environ.get(env_name)
        if v is None:
            raise ValueError(f"the environment variable {env_name} is not set")
        return v
    p = getpass.getpass(prompt)
    if twice and getpass.getpass("again: ") != p:
        raise ValueError("the two passphrases differ")
    return p


def _json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _identity(a, s):
    from ..crypto import Identity
    if a.key_file:
        return Identity.load(a.key_file)
    if a.home:
        from ..peer.home import PeerHome
        return PeerHome(a.home, s).identity()
    raise ValueError("give --home or --key-file")


def _ask(lines: list[str], question: str, yes: bool, out, ask) -> bool:
    out.write("\n".join(lines) + "\n")
    return yes or (ask(question + " [y/N] ").strip().lower() in ("y", "yes"))


def command(a, s: Settings, out=sys.stdout, ask=input) -> dict:
    if a.command == "god-key":
        from .offline import make_god_key
        return {"ok": True, "god": make_god_key(a.out, _passphrase(a.passphrase_env, "god key passphrase: ", twice=True), s), "out": a.out}
    if a.command == "sign":
        from . import formats as F
        from .offline import describe, open_god_key
        req = _json(a.request)
        god = open_god_key(a.key, _passphrase(a.passphrase_env, "god key passphrase: "), s)
        if not _ask(describe(req, god.pub), "sign these?", a.yes, out, ask):
            return {"ok": False, "error": "not signed"}
        doc = F.sign(req, god)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        return {"ok": True, "signed": sorted(doc["sigs"]), "out": a.out}
    if a.command == "run":
        from .offline import read_pub
        from .run import run
        parent = None
        if a.parent:
            from ..recorder.client import RecorderClient
            parent = RecorderClient(a.parent, s)
        return asyncio.run(run(s, read_pub(a.god_pub), a.out, a.witness, parent=parent, parent_url=a.parent, name=a.name, note=a.note,
                               say=lambda m: out.write(m + "\n") or out.flush()))
    if a.command == "witness":
        from . import formats as F
        d, me = _json(a.declaration), _identity(a, s)
        b = d["body"]
        lines = [f"retire {b['role']} key {b['key'][:16]}… of ledger {b['ledger_id'][:16]}…, handed over in {b['handover'][:16]}…, "
                 f"method {b['method']}", f"note: {b['note']}"]
        if not _ask(lines, "did you witness this?", a.yes, out, ask):
            return {"ok": False, "error": "not signed"}
        d = F.witness_sign(d, me)
        with open(a.declaration, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return {"ok": True, "witness": me.pub, "signed": len(d["sigs"]), "of": len(b["witnesses"])}
    if a.command in ("publish", "verify"):
        from ..recorder.client import RecorderClient
        from . import retire
        d, rec = _json(a.declaration), RecorderClient(a.recorder, s)
        if a.command == "publish":
            return asyncio.run(retire.publish(d, _identity(a, s), rec, s))
        return asyncio.run(retire.verify(d, rec, s))
    from . import rotate
    if a.command == "rotate-request":
        return rotate.recorder_request(s, a.dir)
    if a.command == "rotate-god-request":
        from .offline import read_pub
        return rotate.god_request(s, a.dir, read_pub(a.new_god_pub))
    docs = [_json(p) for p in a.signatures]
    return asyncio.run((rotate.recorder_apply if a.command == "rotate" else rotate.god_apply)(s, a.dir, _json(a.request), docs))


def main(argv=None) -> None:
    a = parser().parse_args(argv)
    try:
        r = command(a, Settings.load())
    except (ValueError, OSError) as e:
        r = {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001  (a ceremony stop says why in one line; the log in the folder keeps the steps)
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(r, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(0 if r.get("ok") else 1)
