"""python -m arena.peers.service --spec <service.json>  (settings: ARENA_SERVICE_PEER_*)

An API-providing peer made from a spec file alone: python functions or an existing HTTP API, signed receipts, roles it
offers, and results recorded on the ledger where an event entrusts it with them. It opens the connection methods in
ARENA_SERVICE_PEER_CONNECTIONS: a2a (A2A server), api (REST binding), or both; api only makes an API-only peer, with
no A2A server and no AI agent. See dev/app-guide.md and dev/protocol.md."""
import argparse
import asyncio

from ..config import Settings
from ..peer.service import ServiceApp, load_spec
from .common import build_autonomous_peer, open_connections, run_with_connections


def build(s: Settings, spec_path: str):
    spec = load_spec(spec_path)
    peer = build_autonomous_peer(s, "service_peer", [ServiceApp(s, spec)], spec.get("description") or f"서비스 peer {spec['name']}")
    open_connections(peer, list(s.service_peer_connections), "ARENA_SERVICE_PEER_CONNECTIONS", s.public_url(s.service_peer_api_port),
                     list(spec["ops"]))
    return peer


async def run(peer, s: Settings) -> None:
    await run_with_connections(peer, s.service_peer_port, s.service_peer_api_port, "서비스 peer")


def main():
    ap = argparse.ArgumentParser(description="run an API-providing peer from a spec file")
    ap.add_argument("--spec", required=True)
    a = ap.parse_args()
    s = Settings.load()
    asyncio.run(run(build(s, a.spec), s))


if __name__ == "__main__":
    main()
