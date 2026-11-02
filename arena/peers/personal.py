"""python -m arena.peers.personal  (settings: ARENA_PERSONAL_*, ARENA_LLM_* for an agent peer)

The sample personal peer (P6-P6): one program for the two people-facing peer types of dev/peer-spec.md. With an LLM set
up it is an `agent` peer (the assistant drives, the owner decides the important things on the desk); without one it is a
`human` peer (the owner drives on the desk). It serves A2A for other peers and the owner's screen on this machine."""
from __future__ import annotations

import asyncio
import logging
import os
import secrets

from ..a2a import A2ATransport
from ..broker.failover import FailoverBrokerClient
from ..config import ConfigError, Settings
from ..events import EventLog
from ..llm import build_llm
from ..peer.assistant import EventAssistant
from ..peer.desk import DeskOwner, OwnerDesk, OwnerDeskApp
from ..peer.desk.api import build_owner_api
from ..peer.desk.service import OwnerService
from ..peer.home import PeerHome
from ..peer.node import Peer, PeerConfig
from ..serve import serve_background
from .common import parse_groups


def desk_token(s: Settings, home: PeerHome) -> str:
    if s.personal_desk_token:
        return s.personal_desk_token
    p = home.path("desk-token")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(24))
        os.chmod(p, 0o600)
    with open(p, encoding="utf-8") as f:
        return f.read().strip()


def build(s: Settings) -> tuple[Peer, OwnerService, str]:
    groups = parse_groups(s.personal_peer_brokers)
    if not groups:
        raise ConfigError(f"{s.key_of('personal_peer_brokers')}가 비어 있습니다")
    home = PeerHome(s.personal_peer_home, s)
    llm = build_llm(s)  # ARENA_LLM_BACKEND=none: a human peer, the owner drives; a misconfigured LLM is an error, not a silent fallback
    desk = OwnerDesk(clock=lambda: __import__("time").time(), keep=s.desk_keep_items)
    peer = Peer(home.identity(), s, PeerConfig(url=f"http://{s.host}:{s.personal_peer_port}", labels=list(s.personal_peer_labels)),
                home.area(), DeskOwner(desk, s), llm, A2ATransport(s), EventLog(keep=s.event_log_size),
                brokers={g: FailoverBrokerClient.from_urls(urls, s) for g, urls in groups.items()},
                apps=[OwnerDeskApp(desk), EventAssistant(s)], home=home)
    return peer, OwnerService(peer, desk), desk_token(s, home)


async def run(s: Settings) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    peer, service, token = build(s)
    await serve_background(peer.a2a_app(), s.host, s.personal_peer_port)
    await serve_background(build_owner_api(service, token), s.personal_desk_host, s.personal_desk_port)
    peer.log.emit("peer", peer.pen, f"A2A {peer.config.url} · operator {peer.operator()}")
    print(f"소유자 화면: http://{s.personal_desk_host}:{s.personal_desk_port}/#token={token}", flush=True)
    await peer.advertise()
    await peer.start()
    while True:
        await asyncio.sleep(max(1.0, s.profile_ttl_sec / 2))
        await peer.advertise()


def main():
    asyncio.run(run(Settings.load()))


if __name__ == "__main__":
    main()
