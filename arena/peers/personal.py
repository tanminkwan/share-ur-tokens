"""python -m arena.peers.personal  (settings: ARENA_PERSONAL_*, ARENA_LLM_* for an agent)

The sample personal peer (P6-P6, P6-Q2): one program for the two people-facing types of dev/peer-spec.md, both facing
other peers with a2a. ARENA_PERSONAL_MODE=agent: the agent drives and the person talks with it in the chat window.
ARENA_PERSONAL_MODE=human: the person drives on the owner desk window (an LLM, if set up, only suggests). The windows are
bundled apps (ARENA_PERSONAL_APPS: console by default, the integrated window to watch and step in; desk, chat), each on its
own local web; the peer core has no screen."""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time

from ..a2a import A2ATransport
from ..broker.failover import FailoverBrokerClient
from ..bundled.chat import ChatApp
from ..bundled.console import ConsoleApp
from ..bundled.desk_web import DeskWebApp
from ..bundled.owner_service import OwnerService
from ..config import ConfigError, Settings
from ..events import EventLog
from ..llm import build_llm, llm_available
from ..peer.assistant import EventAssistant
from ..peer.desk import DeskOwner, OwnerDesk, OwnerDeskApp
from ..peer.home import PeerHome
from ..peer.presence import Presence
from ..peer.node import Peer, PeerConfig
from ..serve import serve_background
from .common import parse_groups

SCREENS = {"human": ["console"], "agent": ["console"]}  # the integrated window in both modes (desk and chat stay selectable)
WINDOWS = ("console", "desk", "chat")


def web_token(s: Settings, home: PeerHome) -> str:
    if s.personal_web_token:
        return s.personal_web_token
    p = home.path("web-token")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(24))
        os.chmod(p, 0o600)
    with open(p, encoding="utf-8") as f:
        return f.read().strip()


def build(s: Settings, extra_apps: list = (), kind: str = "personal") -> tuple[Peer, OwnerService, str]:
    """extra_apps: more apps on the same person's peer (e.g. the sphinx's role); kind: what its windows show (peer_kinds)"""
    groups = parse_groups(s.personal_peer_brokers)
    if not groups:
        raise ConfigError(f"{s.key_of('personal_peer_brokers')}가 비어 있습니다")
    if s.personal_mode not in SCREENS:
        raise ConfigError(f"{s.key_of('personal_mode')}는 agent 또는 human이어야 합니다: {s.personal_mode!r}")
    llm = build_llm(s)  # a misconfigured LLM is an error, not a silent fallback; ARENA_LLM_BACKEND=none: no LLM at all
    if s.personal_mode == "agent" and not llm_available(llm):
        raise ConfigError("agent 모드에는 LLM이 필요합니다(ARENA_LLM_*). LLM 없이 쓰려면 ARENA_PERSONAL_MODE=human")
    screens = list(s.personal_apps) or SCREENS[s.personal_mode]
    unknown = [x for x in screens if x not in WINDOWS]
    if unknown or ("chat" in screens and not llm_available(llm)):
        raise ConfigError(f"{s.key_of('personal_apps')}: console, desk, chat 가운데서 고른다(chat에는 LLM이 필요하다): {screens}")
    home = PeerHome(s.personal_peer_home, s)
    token = web_token(s, home)
    desk = OwnerDesk(clock=time.time, keep=s.desk_keep_items)
    windows = ([ConsoleApp(None, s, s.personal_web_host, s.personal_console_port, token)] if "console" in screens else []) + \
              ([DeskWebApp(None, s.personal_web_host, s.personal_desk_port, token)] if "desk" in screens else []) + \
              ([ChatApp(None, s, s.personal_web_host, s.personal_chat_port, token)] if "chat" in screens else [])
    apps = [OwnerDeskApp(desk), EventAssistant(s), *extra_apps, *windows]
    peer = Peer(home.identity(), s, PeerConfig(url=s.public_url(s.personal_peer_port), labels=list(s.personal_peer_labels),
                                               operator=s.personal_mode, kind=kind),
                home.area(), DeskOwner(desk, s), llm, A2ATransport(s), EventLog(keep=s.event_log_size),
                brokers={g: FailoverBrokerClient.from_urls(urls, s) for g, urls in groups.items()}, apps=apps, home=home)
    service = OwnerService(peer, desk)
    for w in windows:  # the windows act through the owner's use cases, which need the assembled peer
        w.service = service
    return peer, service, token


async def run(s: Settings, built=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    peer, _, _ = built or build(s)
    await serve_background(peer.a2a_app(), s.host, s.personal_peer_port)
    peer.log.emit("peer", peer.pen, f"A2A {peer.config.url} · operator {peer.operator()}")
    await peer.start()  # the screen apps open their local web here
    for app in peer.apps:
        if hasattr(app, "address"):
            print(f"{app.name}: {app.address}", flush=True)
    await Presence(peer).keep()  # posts the profile, keeps connecting to brokers that do not answer yet


def main():
    asyncio.run(run(Settings.load()))


if __name__ == "__main__":
    main()
