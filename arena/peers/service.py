"""python -m arena.peers.service --spec <service.json>  (settings: ARENA_SERVICE_PEER_*)

An API-providing peer made from a spec file alone: python functions or an existing HTTP API, signed receipts, roles it
offers, and results recorded on the ledger where an event entrusts it with them. It opens the connection methods in
ARENA_SERVICE_PEER_CONNECTIONS: a2a (A2A server), api (REST binding), or both; api only makes an API-only peer, with
no A2A server and no AI agent. See dev/app-guide.md and dev/protocol.md."""
import argparse
import asyncio
import logging

from ..config import ConfigError, Settings
from ..peer.service import ServiceApp, load_spec
from ..rest import build_rest_app
from ..serve import serve_background
from .common import build_autonomous_peer

OPENABLE = ("a2a", "api")


def build(s: Settings, spec_path: str):
    spec = load_spec(spec_path)
    kinds = [k for k in s.service_peer_connections if k in OPENABLE]
    if not kinds or len(kinds) != len(s.service_peer_connections):
        raise ConfigError(f"ARENA_SERVICE_PEER_CONNECTIONS must be a2a, api or both, not {s.service_peer_connections}")
    peer = build_autonomous_peer(s, "service_peer", [ServiceApp(s, spec)], spec.get("description") or f"서비스 peer {spec['name']}")
    peer.config.connections = ([{"kind": "a2a", "url": peer.config.url}] if "a2a" in kinds else []) + \
        ([{"kind": "api", "url": f"http://{s.host}:{s.service_peer_api_port}", "ops": sorted(spec["ops"])}] if "api" in kinds else [])
    return peer


async def run(peer, s: Settings) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    kinds = {c["kind"] for c in peer.config.connections}
    if "a2a" in kinds:
        await serve_background(peer.a2a_app(), s.host, s.service_peer_port)
    if "api" in kinds:
        await serve_background(build_rest_app(peer.handle), s.host, s.service_peer_api_port)
    peer.log.emit("peer", peer.pen, f"서비스 peer 연결 방식: {', '.join(sorted(kinds))} (op: {', '.join(peer.skills())})")
    await peer.advertise()
    await peer.start()
    while True:  # keep the profile alive before it expires
        await asyncio.sleep(max(1.0, s.profile_ttl_sec / 2))
        await peer.advertise()


def main():
    ap = argparse.ArgumentParser(description="run an API-providing peer from a spec file")
    ap.add_argument("--spec", required=True)
    a = ap.parse_args()
    s = Settings.load()
    asyncio.run(run(build(s, a.spec), s))


if __name__ == "__main__":
    main()
