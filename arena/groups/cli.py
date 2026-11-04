"""python -m arena.groups <command> --home <founder's peer home> --broker URL ...   (a broker group's founder, P6-N)

    show     --broker URL                                  the group's declaration as the broker keeps it (no key needed)
    declare  --home H --broker URL [--group-broker PUB ...] the group lives on its brokers alone (ledger null), or its next version
    attach   --home H --broker URL --recorder URL           move the declaration onto that ledger; from then on events are recorded

The founder is the key the group's brokers name (ARENA_BROKER_OWNER_PUB of a closed group, ARENA_BROKER_FOUNDER_PUB of
an open one). One broker of the group is enough: it shares the declaration with its neighbors."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from ..config import Settings
from .flows import attach_ledger, declare_group


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m arena.groups", description="a broker group's founder: declare the group, attach a ledger")
    ap.add_argument("command", choices=["show", "declare", "attach"])
    ap.add_argument("--home", help="the founder's peer home (default: ARENA_PERSONAL_PEER_HOME)")
    ap.add_argument("--broker", required=True, help="the address of one broker of the group")
    ap.add_argument("--recorder", help="the recorder API address (attach)")
    ap.add_argument("--group-broker", action="append", default=None, help="a broker key of the group (repeat; default: as before, or this broker)")
    return ap


async def run(a, s: Settings, out=sys.stdout, broker_of=None, recorder_of=None) -> int:
    from ..broker.client import BrokerClient
    from ..peer.home import PeerHome
    from ..recorder.client import RecorderClient
    broker = (broker_of or (lambda url: BrokerClient(url, s)))(a.broker)
    try:
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
