"""P4-B: signed direct requests to chosen peers, without a notice board."""
import asyncio
import time

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.events import EventLog
from arena.llm import NoLLM
from arena.peer.app import PeerApp
from arena.peer.area import LocalFolderArea
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.search import BM25Searcher


class Catch(PeerApp):
    def __init__(self):
        self.got = []

    async def on_request(self, peer, request, sender):
        await asyncio.sleep(0.05)  # slow on purpose: the sender must not wait for this
        self.got.append((request["request_id"], sender))


def world(tmp_path, settings, n=3, labels=("소속:삼성SDS",)):
    t, log = LocalTransport(), EventLog(echo=False)
    broker = BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])
    peers = []
    for i in range(n):
        (tmp_path / f"p{i}").mkdir()
        lab = labels if i else ["소속:협력사"]
        p = Peer(Identity.generate(), settings, PeerConfig(url=f"mem://p{i}", labels=list(lab)), LocalFolderArea(str(tmp_path / f"p{i}"), settings),
                 NoOwner(), NoLLM(), t, log, brokers={"b": InMemoryBrokerClient(broker)}, apps=[Catch()])
        t.register(p.config.url, p.handle)
        peers.append(p)
    return peers


def req(issuer, rid="r1", audience=None, until=None):
    return {"request_id": rid, "issuer_pub": issuer.identity.pub, "issuer_url": issuer.config.url, "until": until or time.time() + 60,
            "title": "자료 요청", "text": "클라우드 비용 사례를 보내 주세요", **({"audience": audience} if audience else {})}


async def test_p4b1_b2_b3_b4_direct_request_round_trip(tmp_path, settings):
    partner, a, b = world(tmp_path, settings)
    t0 = time.time()
    acks = await a.solicit([b.config.url, partner.config.url, "mem://nobody"], req(a, audience={"소속": "삼성SDS"}))
    assert time.time() - t0 < 0.05  # acks come back before the slow app work
    assert acks[b.config.url] == {"ok": True, "received": True}
    assert acks[partner.config.url]["ok"] is False and "audience" in acks[partner.config.url]["error"]
    assert acks["mem://nobody"]["ok"] is False
    assert [r["request_id"] for r, _ in [(x["request"], x["sender"]) for x in b.inbox]] == ["r1"]
    await asyncio.sleep(0.1)
    assert b.app(Catch).got == [("r1", a.identity.pub)] and partner.app(Catch).got == []


async def test_p4b3_signature_expiry_and_duplicates(tmp_path, settings):
    _, a, b = world(tmp_path, settings)
    r = req(a)
    good = {"op": "solicit", "request": r, "sig": a.sign(r)}
    assert (await b.handle(good))["ok"]
    assert (await b.handle(good)) == {"ok": False, "error": "duplicate request"}
    forged = {"op": "solicit", "request": dict(r, request_id="r2", text="바뀐 내용"), "sig": a.sign(r)}
    assert (await b.handle(forged))["error"] == "bad signature"
    old = req(a, rid="r3", until=time.time() - 1)
    assert (await b.handle({"op": "solicit", "request": old, "sig": a.sign(old)}))["error"] == "request expired"


async def test_p4b3_inbox_is_bounded(tmp_path, settings):
    from arena.config import Settings
    from tests.conftest import make_env
    s = Settings.load(env=make_env(tmp_path, ARENA_SOLICIT_INBOX_SIZE="2"), dotenv_path=None)
    _, a, b = world(tmp_path, s)
    for i in range(4):
        r = req(a, rid=f"r{i}")
        await b.handle({"op": "solicit", "request": r, "sig": a.sign(r)})
    assert [x["request"]["request_id"] for x in b.inbox] == ["r2", "r3"]
