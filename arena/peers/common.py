"""Assemble and run an autonomous peer (no person behind it) from settings with a given prefix, e.g. search_peer_*."""
from __future__ import annotations

import asyncio
import logging
import os

from ..a2a import A2ATransport
from ..broker.client import BrokerClient
from ..config import ConfigError, Settings
from ..crypto import Identity
from ..events import EventLog
from ..llm import NoLLM, build_llm
from ..peer.area import LocalFolderArea
from ..peer.node import Peer, PeerConfig
from ..peer.owner import NoOwner
from ..serve import serve_background


def parse_groups(items: list[str]) -> dict[str, str]:
    out = {}
    for x in items:
        if "=" not in x:
            raise ConfigError(f"broker 그룹은 그룹=주소 형식이어야 합니다: {x!r}")
        g, url = x.split("=", 1)
        out[g.strip()] = url.strip()
    return out


def build_autonomous_peer(settings: Settings, prefix: str, apps: list, description: str) -> Peer:
    get = lambda k: getattr(settings, f"{prefix}_{k}")
    groups = parse_groups(get("brokers"))
    if not groups:
        raise ConfigError(f"{settings.key_of(prefix + '_brokers')}가 비어 있습니다")
    area_dir = get("area")
    os.makedirs(area_dir, exist_ok=True)
    notes = os.path.join(area_dir, settings.area_notes_file)
    if not os.path.exists(notes):
        with open(notes, "w", encoding="utf-8") as f:
            f.write(f"- {description}\n")
    try:
        llm = build_llm(settings)
    except ConfigError:
        llm = NoLLM()
    return Peer(Identity.load_or_create(get("key_file")), settings,
                PeerConfig(url=f"http://{settings.host}:{get('port')}", labels=list(get("labels"))),
                LocalFolderArea(area_dir, settings), NoOwner(), llm, A2ATransport(settings), EventLog(keep=settings.event_log_size),
                brokers={g: BrokerClient(u, settings) for g, u in groups.items()}, apps=apps)


async def run_peer(peer: Peer, port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    await serve_background(peer.a2a_app(), peer.settings.host, port)
    peer.log.emit("peer", peer.pen, f"A2A 서버 {peer.config.url} (skills: {', '.join(peer.skills())})")
    await peer.advertise()
    await peer.start()
    while True:  # keep the profile alive before it expires
        await asyncio.sleep(max(1.0, peer.settings.profile_ttl_sec / 2))
        await peer.advertise()
