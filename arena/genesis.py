"""The genesis: the first act of the ecosystem. god creates the genesis broker (the genesis group, open to everyone)
and the recorder, and signs entry 0 of the ledger naming all three. Everything else joins afterwards.

    python -m arena.genesis        # settings: ARENA_GENESIS_*, ARENA_GOD_VIEWERS
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field

from .a2a import A2ATransport
from .broker.api import build_broker_app
from .broker.client import BrokerClient
from .broker.neighbors import HttpNeighbors
from .broker.service import BrokerService
from .broker.store import FileBrokerStore
from .config import ConfigError, Settings
from .crypto import Identity
from .events import EventLog
from .ledger import JsonlStore
from .ledger.trust import anchor_block, branch_parent, link_to_parent, record_parent_link
from .ledger.types import current_keys
from .recorder.client import RecorderClient
from .llm import NoLLM, build_llm
from .peer.area import LocalFolderArea
from .peer.god_role import GodRole
from .peer.home import PeerHome
from .peer.node import Peer, PeerConfig
from .peer.owner import NoOwner
from .peer.record_role import RecordRole
from .recorder.service import RecorderService
from .search import BM25Searcher
from .serve import serve_background

GENESIS_GROUP_NAME = "public"  # how peers refer to the genesis group among their broker groups


def genesis_payload(settings: Settings, god_pub: str, broker_pub: str, recorder_pub: str, parent: dict | None = None) -> dict:
    """entry 0. A community that starts its own ledger names the original chain it links into (P5-G9)"""
    return {"group_id": settings.genesis_group_id, "god": god_pub, "broker": broker_pub, "recorder": recorder_pub,
            **({"parent": parent} if parent else {})}


async def record_genesis(recorder, god: Identity, settings: Settings, broker_pub: str, recorder_pub: str, parent: dict | None = None) -> dict:
    """god signs entry 0 on a recorder (RecorderAPI client or RecorderService)"""
    p = genesis_payload(settings, god.pub, broker_pub, recorder_pub, parent)
    return await recorder.record("genesis", p, {god.pub: god.sign(p)})


def write_anchor(settings: Settings, chain: list[dict]) -> str:
    """the root values to publish outside the ledger (P5-G7): <genesis dir>/trust-anchor.md"""
    path = os.path.join(settings.genesis_dir, "trust-anchor.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(anchor_block(chain))
    return path


@dataclass
class Genesis:
    god: Peer
    recorder: Peer
    broker: BrokerService
    urls: dict
    servers: list = field(default_factory=list)

    def stop(self):
        for s in self.servers:
            s.should_exit = True


def _area(root: str, settings: Settings, line: str) -> LocalFolderArea:
    os.makedirs(root, exist_ok=True)
    notes = os.path.join(root, settings.area_notes_file)
    if not os.path.exists(notes):
        with open(notes, "w", encoding="utf-8") as f:
            f.write(f"- {line}\n")
    return LocalFolderArea(root, settings)


async def start(settings: Settings, viewers=None) -> Genesis:
    d, host = settings.genesis_dir, settings.host
    url = lambda port: f"http://{host}:{port}"
    god_id = Identity.load_or_create(os.path.join(d, "god.key"))
    broker = BrokerService(settings, Identity.load_or_create(os.path.join(d, "broker.key")), BM25Searcher(settings.bm25_k1, settings.bm25_b),
                           HttpNeighbors(settings.neighbor_timeout_sec), name=settings.genesis_broker_name, neighbors=[],
                           group_id=settings.genesis_group_id, store=FileBrokerStore(os.path.join(d, "broker-state.json")))
    rec_key = os.path.join(d, "recorder.key")
    rec_id = Identity.load_or_create(rec_key)
    svc = RecorderService.build(settings, rec_id, JsonlStore(os.path.join(d, "ledger.jsonl")), readers=[god_id.pub, *settings.recorder_readers],
                                access_log_path=os.path.join(d, "recorder-access.jsonl"), key_file=rec_key)
    parent_client = RecorderClient(settings.genesis_parent_recorder_url, settings) if settings.genesis_parent_recorder_url else None
    if not svc.ledger.chain:
        parent = None
        if parent_client:  # a community starting its own ledger: its start is linked into the original chain (P5-G9)
            pt = await parent_client.trust()
            if not pt.get("ok"):
                raise RuntimeError(f"parent recorder: {pt.get('error')}")
            if "parent" in ((pt.get("genesis") or {}).get("payload") or {}):  # P5-G10: branches grow only from the trunk
                raise ConfigError("ARENA_GENESIS_PARENT_RECORDER_URL must be the trunk's recorder: a branch chain cannot start a branch")
            parent = branch_parent(pt, settings.genesis_parent_recorder_url)  # ledger, recorder key, branch point (CP-1)
        r = await record_genesis(svc, god_id, settings, broker.identity.pub, rec_id.pub, parent)
        if not r["ok"]:
            raise RuntimeError(f"genesis failed: {r['error']}")
    else:
        g, keys = svc.ledger.chain[0], current_keys(svc.ledger.chain)
        if g["type"] != "genesis" or g["payload"].get("broker") != broker.identity.pub or keys["god"] != god_id.pub:
            raise ConfigError("the stored ledger was not begun by this god and broker (keys follow key_rotate from the genesis)")
    if parent_client and not (await parent_client.link(svc.ledger.chain[0]["hash"])).get("ok"):
        if svc.ledger.chain[0]["payload"]["recorder"] != rec_id.pub:
            raise RuntimeError("this ledger is not linked into the original chain and its first recorder key is already retired")
        r = await link_to_parent(parent_client, god_id, rec_id, svc.ledger.chain, settings.genesis_broker_name)
        if not r.get("ok"):
            raise RuntimeError(f"could not link this ledger into the original chain: {r.get('error')}")
    if parent_client and len(svc.ledger.chain) == 1:  # entry 1 of a branch: the chain_link the trunk sealed (CP-2)
        link = (await parent_client.link(svc.ledger.chain[0]["hash"])).get("link")
        r = await record_parent_link(svc, god_id, svc.ledger.chain, link or {})
        if not r.get("ok"):
            raise RuntimeError(f"could not record this ledger's parent_link: {r.get('error')}")
    anchor_file = write_anchor(settings, svc.ledger.chain)
    urls = {"broker": url(settings.genesis_broker_port), "recorder": url(settings.genesis_recorder_port),
            "recorder_api": url(settings.genesis_recorder_api_port), "god": url(settings.genesis_god_port)}
    try:
        llm = build_llm(settings)
    except ConfigError:
        llm = NoLLM()
    log, transport = EventLog(keep=settings.event_log_size), A2ATransport(settings)
    brokers = lambda: {GENESIS_GROUP_NAME: BrokerClient(urls["broker"], settings)}
    role = RecordRole(svc, urls["recorder_api"])
    recorder = Peer(rec_id, settings, PeerConfig(url=urls["recorder"]), _area(os.path.join(d, "areas", "recorder"), settings,
                    "제네시스 기록자: god이 만든 첫 기록자. 원장을 검증하고 기록자 서명을 남겨 보관한다"), NoOwner(), llm, transport, log,
                    brokers=brokers(), apps=[role], home=PeerHome(os.path.join(d, "homes", "recorder"), settings))
    god = Peer(god_id, settings, PeerConfig(url=urls["god"]), _area(os.path.join(d, "areas", "god"), settings,
               "god: 제네시스로 만민 broker와 기록자를 만든 peer. 원장 전체를 읽어 감사하고 통계를 낸다"), NoOwner(), llm, transport, log,
               brokers=brokers(), apps=[GodRole(settings, viewers)], home=PeerHome(os.path.join(d, "homes", "god"), settings))
    world = Genesis(god, recorder, broker, urls)
    world.servers.append(await serve_background(build_broker_app(broker), host, settings.genesis_broker_port))
    world.servers.append(await serve_background(role.api(), host, settings.genesis_recorder_api_port))
    for p in (recorder, god):  # profiles first, so an open A2A door means the genesis is complete
        await p.advertise()
    world.servers.append(await serve_background(recorder.a2a_app(), host, settings.genesis_recorder_port))
    world.servers.append(await serve_background(god.a2a_app(), host, settings.genesis_god_port))
    for p in (recorder, god):
        await p.start()
    log.emit("genesis", god.pen, "제네시스: " + json.dumps({"god": god_id.pub, "broker": broker.identity.pub, "recorder": rec_id.pub,
                                                        "ledger_id": svc.ledger.chain[0]["hash"], "anchor": anchor_file, **urls}))
    return world


def main():
    s = Settings.load()

    async def run():
        await start(s)
        while True:
            await asyncio.sleep(3600)
    asyncio.run(run())


if __name__ == "__main__":
    main()
