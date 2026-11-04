"""python -m arena.groups <command> --home <founder's peer home> --broker URL ...   (a broker group's founder, P6-N)

    show     --broker URL                                  the group's declaration as the broker keeps it (no key needed)
    declare  --home H --broker URL [--group-broker PUB ...] the group lives on its brokers alone (ledger null), or its next version
    attach   --home H --broker URL --recorder URL           move the declaration onto that ledger; from then on events are recorded
    apply    (--home H | --key-file F) --sphinx URL --purpose TEXT --contact TEXT
             apply to a sphinx to found a branch group with that key as the branch's god; prints the application id
    pass     --sphinx URL --application ID [--home H | --key-file F] [--out pass.json]   where it stands; the pass once given

The founder is the key the group's brokers name (ARENA_BROKER_OWNER_PUB of a closed group, ARENA_BROKER_FOUNDER_PUB of
an open one). One broker of the group is enough: it shares the declaration with its neighbors. A sphinx is a person: after
`apply`, they reach you through --contact and meet you (video call or face to face) before the pass comes."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from ..config import Settings
from .flows import apply_to_sphinx, attach_ledger, declare_group, founding_pass


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m arena.groups", description="a broker group's founder: declare the group, attach a ledger, apply to a sphinx")
    ap.add_argument("command", choices=["show", "declare", "attach", "apply", "pass"])
    ap.add_argument("--home", help="the founder's peer home (default: ARENA_PERSONAL_PEER_HOME)")
    ap.add_argument("--broker", help="the address of one broker of the group (show, declare, attach)")
    ap.add_argument("--key-file", help="the founder key file (e.g. the branch genesis' god key) instead of a peer home (apply, pass)")
    ap.add_argument("--sphinx", help="the sphinx peer's a2a address (apply, pass)")
    ap.add_argument("--purpose", help="what the branch group is for, a short text (apply)")
    ap.add_argument("--contact", help="how the sphinx's person reaches you, e.g. mailto: or a phone (apply)")
    ap.add_argument("--application", help="the application id apply printed (pass)")
    ap.add_argument("--out", help="write the pass JSON here once given (pass)")
    ap.add_argument("--recorder", help="the recorder API address (attach)")
    ap.add_argument("--group-broker", action="append", default=None, help="a broker key of the group (repeat; default: as before, or this broker)")
    return ap


def _founder(a, s: Settings):
    from ..crypto import Identity
    from ..peer.home import PeerHome
    if a.key_file:
        if not os.path.exists(a.key_file):
            raise ValueError(f"no key file at {a.key_file}")
        return Identity.load(a.key_file)
    return PeerHome(a.home or s.personal_peer_home, s).identity()


async def _sphinx(a, s: Settings, ask_of) -> dict:
    from ..a2a import A2ATransport
    if not a.sphinx:
        raise ValueError(f"{a.command} needs --sphinx")
    ask = (ask_of or (lambda url: (lambda msg: A2ATransport(s).call(url, msg))))(a.sphinx)
    if a.command == "apply":
        if not a.purpose or not a.contact:
            raise ValueError("apply needs --purpose and --contact")
        return await apply_to_sphinx(_founder(a, s), ask, a.purpose, a.contact, time.time())
    if not a.application:
        raise ValueError("pass needs --application")
    founder = _founder(a, s).pub if (a.home or a.key_file) else None
    r = await founding_pass(ask, a.application, founder)
    if r.get("ok") and r.get("status") == "passed" and a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(r["pass"], f, ensure_ascii=False, indent=2)
    return r


async def run(a, s: Settings, out=sys.stdout, broker_of=None, recorder_of=None, ask_of=None) -> int:
    from ..broker.client import BrokerClient
    from ..peer.home import PeerHome
    from ..recorder.client import RecorderClient
    try:
        if a.command in ("apply", "pass"):
            r = await _sphinx(a, s, ask_of)
            print(json.dumps(r, ensure_ascii=False, indent=2), file=out)
            return 0 if r.get("ok") else 1
        if not a.broker:
            raise ValueError(f"{a.command} needs --broker")
        broker = (broker_of or (lambda url: BrokerClient(url, s)))(a.broker)
        if a.command == "show":
            r = await broker.group()
        else:
            me = PeerHome(a.home or s.personal_peer_home, s).identity()
            if a.command == "declare":
                r = await declare_group(me, broker, a.group_broker)
            else:
                if not a.recorder:
                    raise ValueError("attach needs --recorder")
                r = await attach_ledger(me, broker, (recorder_of or (lambda url: RecorderClient(url, s)))(a.recorder), a.recorder)
                r.pop("receipt", None)
    except ValueError as e:
        r = {"ok": False, "error": str(e)}
    print(json.dumps(r, ensure_ascii=False, indent=2), file=out)
    return 0 if r.get("ok") else 1


def main(argv=None) -> None:
    a = parser().parse_args(argv)
    raise SystemExit(asyncio.run(run(a, Settings.load())))
