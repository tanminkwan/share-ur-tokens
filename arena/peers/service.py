"""python -m arena.peers.service --spec <service.json>  (settings: ARENA_SERVICE_PEER_*)

An API-providing peer made from a spec file alone: python functions or an existing HTTP API, signed receipts, roles it
offers, and results recorded on the ledger where an event entrusts it with them. See dev/app-guide.md and dev/protocol.md."""
import argparse
import asyncio

from ..config import Settings
from ..peer.service import ServiceApp, load_spec
from .common import build_autonomous_peer, run_peer


def build(s: Settings, spec_path: str):
    spec = load_spec(spec_path)
    return build_autonomous_peer(s, "service_peer", [ServiceApp(s, spec)], spec.get("description") or f"서비스 peer {spec['name']}")


def main():
    ap = argparse.ArgumentParser(description="run an API-providing peer from a spec file")
    ap.add_argument("--spec", required=True)
    a = ap.parse_args()
    s = Settings.load()
    asyncio.run(run_peer(build(s, a.spec), s.service_peer_port))


if __name__ == "__main__":
    main()
