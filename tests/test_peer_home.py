"""P5-C20: a peer whose process stops and starts again continues as the same peer from its home folder."""
import asyncio
import os
import stat
import time

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.events import EventLog
from arena.ledger import MemoryStore
from arena.llm import NoLLM
from arena.peer.assistant import EventAssistant
from arena.peer.home import PeerHome
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from arena.search import BM25Searcher


def boot(home_dir, settings, broker, svc, t):
    """what a peer process does when it starts: open its home, assemble, restore"""
    home = PeerHome(str(home_dir), settings)
    p = Peer(home.identity(), settings, PeerConfig(url="mem://me", labels=["소속:예시"]), home.area(), NoOwner(), NoLLM(), t,
             EventLog(echo=False), brokers={"public": InMemoryBrokerClient(broker)}, apps=[EventAssistant(settings)], home=home)
    p.recorder_factory = lambda u: InMemoryRecorderClient(svc)
    t.register(p.config.url, p.handle)
    return p


async def test_p5c20_a_restarted_peer_continues_as_itself(tmp_path, settings):
    broker = BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])
    svc = RecorderService.build(settings, Identity.generate(), MemoryStore(), readers=[])
    t, other = LocalTransport(), Identity.generate()
    home = tmp_path / "home"
    p = boot(home, settings, broker, svc, t)
    (home / "area" / "notes.md").write_text("- 공개 영역 노트\n", encoding="utf-8")
    await p.advertise()
    await p.advertise()
    payload = {"author": p.identity.pub, "content_hash": "c" * 64, "group_id": "public"}
    r = await p.recorder("mem://rec").record("publish", payload, {p.identity.pub: p.sign(payload)})
    assert p.receipts.keep(r, "publish", payload, expected_recorder=svc.identity.pub)
    req = {"request_id": "r-1", "issuer_pub": other.pub, "until": time.time() + 60, "title": "t"}
    assert (await p.handle({"op": "solicit", "request": req, "sig": other.sign(req)}))["ok"]
    a = p.app(EventAssistant)
    a.since = 123.0
    a.seen.add("ev-ignored")
    a.save_cursor(p)
    key_file = home / "identity.key"
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    pub, n_receipts = p.identity.pub, len(p.receipts.items)
    # --- the process stops; a new one starts from the same home ---
    q = boot(home, settings, broker, svc, LocalTransport())
    await q.app(EventAssistant).start(q)
    q.app(EventAssistant)._watch.cancel()
    assert q.identity.pub == pub
    assert len(q.receipts.items) == n_receipts == 1 and q.receipts.missing_from(svc.ledger.chain) == []
    assert q.known_recorders == ["mem://rec"]
    assert (await q.advertise())["ver"] == 3  # the profile version continues
    assert (await q.handle({"op": "solicit", "request": req, "sig": other.sign(req)}))["error"] == "duplicate request"
    qa = q.app(EventAssistant)
    assert qa.since == 123.0 and "ev-ignored" in qa.seen
    assert qa.store(q).root.startswith(str(home))  # events live in the same home
