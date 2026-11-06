"""Assemble and run an autonomous peer (no person behind it) from settings with a given prefix, e.g. search_peer_*."""
from __future__ import annotations

import logging
import os

from ..a2a import A2ATransport
from ..broker.failover import FailoverBrokerClient
from ..config import ConfigError, Settings
from ..keys.store import load_or_create, open_key_store
from ..events import EventLog
from ..llm import NoLLM, build_llm
from ..peer.area import LocalFolderArea
from ..peer.node import Peer, PeerConfig
from ..peer.owner import NoOwner
from ..peer.presence import Presence
from ..rest import build_rest_app
from ..serve import serve_background

OPENABLE = ("a2a", "api")


def parse_groups(items: list[str]) -> dict[str, list[str]]:
    """group=url1|url2 ...: several brokers of one group, primary first"""
    out = {}
    for x in items:
        if "=" not in x:
            raise ConfigError(f"broker 그룹은 그룹=주소(|주소...) 형식이어야 합니다: {x!r}")
        g, urls = x.split("=", 1)
        out[g.strip()] = [u.strip() for u in urls.split("|") if u.strip()]
    return out


KINDS = {"key_peer": "key", "link_peer": "link", "foundation_peer": "foundation", "app_store_peer": "app-store", "search_peer": "search",
         "service_peer": "service"}  # what each special-purpose peer is, for any window plugged into it (arena/bundled/peer_kinds.py)


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
    return Peer(load_or_create(open_key_store(settings), get("key_file")), settings,
                PeerConfig(url=settings.public_url(get("port")), labels=list(get("labels")), kind=KINDS.get(prefix, "personal"), nick=get("nick")),
                LocalFolderArea(area_dir, settings), NoOwner(), llm, A2ATransport(settings), EventLog(keep=settings.event_log_size),
                brokers={g: FailoverBrokerClient.from_urls(urls, settings) for g, urls in groups.items()}, apps=apps)


async def run_peer(peer: Peer, port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    await serve_background(peer.a2a_app(), peer.settings.host, port)
    peer.log.emit("peer", peer.pen, f"A2A 서버 {peer.config.url} (skills: {', '.join(peer.skills())})")
    await peer.start()
    await Presence(peer).keep()  # posts the profile, keeps connecting to brokers that do not answer yet


def open_connections(peer: Peer, kinds: list[str], setting: str, api_url: str, ops: list[str]) -> None:
    """the connection methods an API-serving peer opens (a2a, api, or both), listed in its profile"""
    if not kinds or any(k not in OPENABLE for k in kinds):
        raise ConfigError(f"{setting} must be a2a, api or both, not {kinds}")
    peer.config.connections = ([{"kind": "a2a", "url": peer.config.url}] if "a2a" in kinds else []) + \
        ([{"kind": "api", "url": api_url, "ops": sorted(ops)}] if "api" in kinds else [])


async def run_with_connections(peer: Peer, port: int, api_port: int, label: str) -> None:
    """serve the connections the profile lists, post the profile and keep it alive"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    s = peer.settings
    kinds = {c["kind"] for c in peer.config.connections}
    if "a2a" in kinds:
        await serve_background(peer.a2a_app(), s.host, port)
    if "api" in kinds:
        await serve_background(build_rest_app(peer.handle), s.host, api_port)
    peer.log.emit("peer", peer.pen, f"{label} 연결 방식: {', '.join(sorted(kinds))} (op: {', '.join(peer.skills())})")
    await peer.start()
    await Presence(peer).keep()  # posts the profile, keeps connecting to brokers that do not answer yet

