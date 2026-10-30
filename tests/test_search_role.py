"""P3-B: the advanced search peer over in-memory brokers with a deterministic embedder."""
import time

import pytest

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.embedding import EmbedError
from arena.events import EventLog
from arena.llm import NoLLM
from arena.peer.area import LocalFolderArea
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.peer.search_role import SearchRole
from arena.search import BM25Searcher
from arena.signing import sign_message
from tests.fakes import HashEmbedder

SDS, PARTNER = "소속:삼성SDS", "소속:협력사"


def prof(url, summary, offers=(), labels=(SDS,), ver=1):
    return {"url": url, "summary": summary, "offers": list(offers), "labels": list(labels), "until": time.time() + 3600, "ver": ver}


def notice(issuer, nid, text, audience=None):
    return {"notice_id": nid, "issuer_pub": issuer.pub, "until": time.time() + 600, "title": text[:10], "text": text,
            "kind": "모집", "audience": {"소속": "삼성SDS"} if audience is None else audience}


class Net:
    def __init__(self, tmp, settings):
        self.owner = Identity.generate()
        self.open = BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="open", neighbors=[])
        self.closed = BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="closed", neighbors=[], owner_pub=self.owner.pub)
        self.emb = HashEmbedder()
        self.role = SearchRole(self.emb, settings)
        (tmp / "area").mkdir()
        (tmp / "area" / "notes.md").write_text("- 고급 검색 peer: 프로필과 공지를 뜻으로 찾는다\n", encoding="utf-8")
        self.peer = Peer(Identity.generate(), settings, PeerConfig(url="mem://search", labels=[SDS, PARTNER]),
                         LocalFolderArea(str(tmp / "area"), settings), NoOwner(), NoLLM(), LocalTransport(), EventLog(echo=False),
                         brokers={"open": InMemoryBrokerClient(self.open), "closed": InMemoryBrokerClient(self.closed)}, apps=[self.role])

    async def grant(self, who):
        g = {"pub": who.pub, "until": time.time() + 3600}
        await self.closed.grant(g, self.owner.sign(g))

    async def put(self, broker, who, p):
        r = await broker.advertise({"pub": who.pub, "profile": p, "sig": who.sign(p)})
        assert r["ok"], r


@pytest.fixture
async def net(tmp_path, settings):
    n = Net(tmp_path, settings)
    await n.grant(n.peer.identity)
    await n.peer.advertise()
    return n


def signed(who, op, **kw):
    return dict({"op": op, **kw}, **sign_message(who, op))


async def test_p3b1_p3b2_sync_indexes_and_reembeds_only_changes(net):
    a, b = Identity.generate(), Identity.generate()
    await net.put(net.open, a, prof("http://a", "인프라 장애 대응 12년", offers=["review"]))
    await net.put(net.open, b, prof("http://b", "신입 온보딩 교육 담당"))
    s = await net.role.sync(net.peer)
    assert s["open"]["added"] == 3  # a, b and the search peer itself
    assert net.peer.offers() == ["search"]
    before = sum(len(c) for c in net.emb.calls)
    s = await net.role.sync(net.peer)
    assert s["open"] == {"added": 0, "updated": 0, "removed": 0} and sum(len(c) for c in net.emb.calls) == before
    await net.put(net.open, b, prof("http://b", "신입 온보딩과 멘토링 담당", ver=2))
    s = await net.role.sync(net.peer)
    assert s["open"]["updated"] == 1 and net.emb.calls[-1] == ["신입 온보딩과 멘토링 담당 소속:삼성SDS"]
    net.open.profiles[a.pub]["until"] = time.time() - 1  # expired on the broker
    s = await net.role.sync(net.peer)
    assert s["open"]["removed"] == 1


async def test_p3b3_search_profiles_with_filters(net):
    a, b, c = Identity.generate(), Identity.generate(), Identity.generate()
    await net.put(net.open, a, prof("http://a", "공모 심사 평가 기준", offers=["review"]))
    await net.put(net.open, b, prof("http://b", "공모 심사 경험 많은 협력사 분석가", labels=[PARTNER]))
    await net.put(net.open, c, prof("http://c", "물류 창고 재고"))
    await net.role.sync(net.peer)
    r = await net.peer.handle({"op": "search_profiles", "q": "공모 심사", "k": 5})
    pubs = [x["pub"] for x in r["hits"]]
    assert r["ok"] and pubs[:2] in ([a.pub, b.pub], [b.pub, a.pub]) and r["hits"][0]["score"] >= r["hits"][1]["score"]
    assert r["hits"][0]["group"] == "open" and "summary" in r["hits"][0]
    assert net.peer.identity.pub not in [x["pub"] for x in (await net.peer.handle({"op": "search_profiles", "q": "고급 검색 peer", "k": 10}))["hits"]]
    r = await net.peer.handle({"op": "search_profiles", "q": "공모 심사", "role": "review"})
    assert [x["pub"] for x in r["hits"]] == [a.pub]
    r = await net.peer.handle({"op": "search_profiles", "q": "공모 심사", "labels": [SDS], "exclude": [a.pub], "k": 5})
    assert b.pub not in [x["pub"] for x in r["hits"]] and a.pub not in [x["pub"] for x in r["hits"]]
    r = await net.peer.handle({"op": "search_profiles", "q": "공모 심사", "k": 1})
    assert len(r["hits"]) == 1


async def test_p3b4_notices_follow_the_audience_rule_of_the_asker(net):
    issuer, sds, partner = Identity.generate(), Identity.generate(), Identity.generate()
    await net.put(net.open, sds, prof("http://s", "사원"))
    await net.put(net.open, partner, prof("http://p", "협력사", labels=[PARTNER]))
    for n in (notice(issuer, "n1", "신입 온보딩 아이디어 모집"), notice(issuer, "n2", "협력사 온보딩 개선 모집", audience={"소속": "협력사"})):
        await net.open.post_notice(n, issuer.sign(n))
    await net.role.sync(net.peer)  # the search peer carries both labels, so it indexes both notices
    assert {k.split("|")[2] for k in net.role.index.keys() if "|notice|" in k} == {"n1", "n2"}
    r = await net.peer.handle(signed(sds, "search_notices", q="온보딩"))
    assert [x["notice_id"] for x in r["hits"]] == ["n1"]
    r = await net.peer.handle(signed(partner, "search_notices", q="온보딩"))
    assert [x["notice_id"] for x in r["hits"]] == ["n2"]
    r = await net.peer.handle({"op": "search_notices", "q": "온보딩"})
    assert r["ok"] is False and "signed" in r["error"]
    r = await net.peer.handle(signed(Identity.generate(), "search_notices", q="온보딩"))
    assert r["hits"] == []  # no profile anywhere -> sees nothing


async def test_p3b5_closed_group_only_for_its_members(net):
    rev, outsider = Identity.generate(), Identity.generate()
    await net.grant(rev)
    await net.put(net.closed, rev, prof("http://r", "공모 심사 전문가", offers=["review"]))
    await net.put(net.open, outsider, prof("http://o", "사원"))
    await net.role.sync(net.peer)
    r = await net.peer.handle({"op": "search_profiles", "q": "심사 전문가"})
    assert rev.pub not in [x["pub"] for x in r["hits"]]  # anonymous: closed group hidden
    r = await net.peer.handle(signed(outsider, "search_profiles", q="심사 전문가"))
    assert rev.pub not in [x["pub"] for x in r["hits"]]
    r = await net.peer.handle(signed(rev, "search_profiles", q="심사 전문가"))
    assert rev.pub in [x["pub"] for x in r["hits"]] and next(x for x in r["hits"] if x["pub"] == rev.pub)["group"] == "closed"
    bad = signed(rev, "search_profiles", q="x")
    bad["sig"] = "00" * 64
    assert (await net.peer.handle(bad))["ok"] is False


async def test_p3b6_status_and_p3b7_embedder_down(net):
    a = Identity.generate()
    await net.put(net.open, a, prof("http://a", "인프라"))
    await net.role.sync(net.peer)
    st = await net.peer.handle({"op": "search_status"})
    assert st["ok"] and st["groups"]["open"]["profiles"] == 2 and st["groups"]["closed"]["profiles"] == 1 and st["groups"]["closed"]["closed"] is True and st["dim"] == 256

    class Down:
        async def embed(self, texts):
            raise EmbedError("service down")
    net.role.embedder = Down()
    await net.put(net.open, a, prof("http://a", "인프라 v2", ver=2))
    s = await net.role.sync(net.peer)
    assert s["open"]["error"] and len(net.role.index) == 3  # index kept as is (2 open + 1 closed)
    assert any("임베딩" in e["text"] for e in net.peer.log.tail(5))
    r = await net.peer.handle({"op": "search_profiles", "q": "인프라"})
    assert r["ok"] is False and "service down" in r["error"]
