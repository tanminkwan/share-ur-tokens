"""python -m arena.content <command> ...   (works and the ledger, CP-9 and CP-10)

    hash     --file F [--form utf8-nfc-lf|bytes]                          the body's hash in a form
    register --home H --recorder URL --file F [--form] [--did DID] [--storage kind=location ...] [--hide-storage] [--out ref.json]
             the author's peer registers the work (publish, authorship) and prints the reference for the colophon
    check    --file F (--ref ref.json | --uri arena-ref:...) [--recorder URL]   a reader checks a copy (root values from .env)
    find     (--file F [--form] | --hash H) --recorder URL                 the registration of a body, without a reference

Text forms: utf8-nfc-lf (default for text: UTF-8, no BOM, LF line ends, NFC) and bytes (the file as it is)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from ..config import Settings
from ..ledger.refs import STORAGE_KINDS, content_hash_of
from .check import check_work
from .reference import from_uri
from .works import register_work


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m arena.content", description="register a work on the ledger, check a copy, find a registration")
    ap.add_argument("command", choices=["hash", "register", "check", "find"])
    ap.add_argument("--file")
    ap.add_argument("--form", default="utf8-nfc-lf")
    ap.add_argument("--hash", dest="content_hash")
    ap.add_argument("--home", help="the author's peer home (default: ARENA_PERSONAL_PEER_HOME)")
    ap.add_argument("--recorder", help="the recorder API address")
    ap.add_argument("--did", help="the author's existing DID, printed in the reference (not checked by the platform)")
    ap.add_argument("--storage", action="append", default=[], help="where the work is kept: kind=location (kinds: " + ", ".join(sorted(STORAGE_KINDS)) + ")")
    ap.add_argument("--hide-storage", action="store_true", help="keep the places in the private envelope")
    ap.add_argument("--media-type")
    ap.add_argument("--out", help="write the reference JSON here (register)")
    ap.add_argument("--ref", help="the reference JSON (check)")
    ap.add_argument("--uri", help="the reference address arena-ref:... (check)")
    return ap


def _storage(items: list[str]) -> list[dict]:
    out = []
    for x in items:
        if "=" not in x:
            raise SystemExit(f"--storage must be kind=location, not {x!r}")
        k, loc = x.split("=", 1)
        out.append({"kind": k.strip(), "location": loc.strip()})
    return out


async def run(a, s: Settings, out=sys.stdout, recorder_of=None) -> int:
    from ..peer.home import PeerHome
    from ..recorder.client import RecorderClient
    recorder_of = recorder_of or (lambda url: RecorderClient(url, s))
    data = open(a.file, "rb").read() if a.file else None
    if a.command == "hash":
        r = {"ok": True, "content_hash": content_hash_of(data, a.form), "form": a.form}
    elif a.command == "register":
        me = PeerHome(a.home or s.personal_peer_home, s).identity()
        r = await register_work(me, data, recorder_of(a.recorder), a.recorder, s.genesis_group_id, a.form, _storage(a.storage),
                                a.media_type, True, a.hide_storage, a.did)
        if r.get("ok") and a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(r["reference"], f, ensure_ascii=False, indent=2)
        r.pop("receipt", None)
    elif a.command == "check":
        ref = json.load(open(a.ref, encoding="utf-8")) if a.ref else from_uri(a.uri)
        anchor = {"genesis_hash": s.trust_genesis_hash, "god_pub": s.trust_god_pub} if s.trust_genesis_hash else None
        r = await check_work(data, ref, recorder_of(a.recorder or ref["recorder_url"]), anchor, recorder_of)
    else:
        h = a.content_hash or content_hash_of(data, a.form)
        r = await recorder_of(a.recorder).content(h)
    out.write(json.dumps(r, ensure_ascii=False, indent=2) + "\n")
    return 0 if r.get("ok") and r.get("found", True) else 1


def main(argv=None) -> None:
    a = parser().parse_args(argv)
    raise SystemExit(asyncio.run(run(a, Settings.load())))
