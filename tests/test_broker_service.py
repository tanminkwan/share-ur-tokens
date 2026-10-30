"""R4: the broker service object. Neighbors are in-memory services (no HTTP)."""
import pytest

from arena.broker.neighbors import Caller, InMemoryNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.search import BM25Searcher

SDS = "소속:삼성SDS"


def profile(url, summary, offers=(), labels=(SDS,), until=None, ver=1, now=0):
    return {"url": url, "summary": summary, "offers": list(offers), "labels": list(labels),
            "until": until if until is not None else now + 3600, "ver": ver}


def ad(who, prof):
    return {"pub": who.pub, "profile": prof, "sig": who.sign(prof)}


def notice(issuer, nid="call-1", audience=None, until=None, now=0, text="신입 사원 적응 아이디어 공모"):
    return {"notice_id": nid, "kind": "아이디어 공모", "title": text[:20], "text": text,
            "audience": {"소속": "삼성SDS"} if audience is None else audience, "conditions": {},
            "until": until if until is not None else now + 600, "issuer_pub": issuer.pub, "issuer_url": "http://issuer",
            "recorder_pub": "", "recorder_url": "", "contracts": []}


class Net:
    """three open brokers that share notices, like the demo's applicant group"""

    def __init__(self, settings, clock, n=3, owner_pub=None):
        self.gw = InMemoryNeighbors()
        self.brokers = []
        for i in range(n):
            b = BrokerService(settings, Identity.generate(), BM25Searcher(), self.gw, name=f"b{i}",
                              neighbors=[f"mem://b{j}" for j in range(n) if j != i], owner_pub=owner_pub, clock=clock)
            self.gw.register(f"mem://b{i}", b)
            self.brokers.append(b)


@pytest.fixture
def net(settings, clock):
    return Net(settings, clock)


@pytest.fixture
def b0(net):
    return net.brokers[0]


async def test_r4_1_advertise_and_update(b0, clock):
    me = Identity.generate()
    r = await b0.advertise(ad(me, profile("http://me", "인프라 엔지니어", now=clock())))
    assert r == {"ok": True, "updated": False}
    r = await b0.advertise(ad(me, profile("http://me", "인프라 엔지니어 12년차", ver=2, now=clock())))
    assert r == {"ok": True, "updated": True}
    assert [p["summary"] for p in await b0.list_profiles(Caller.anonymous(), local=True)] == ["인프라 엔지니어 12년차"]


async def test_r4_1_bad_signature_rejected(b0, clock):
    me, other = Identity.generate(), Identity.generate()
    prof = profile("http://me", "x", now=clock())
    assert await b0.advertise({"pub": me.pub, "profile": prof, "sig": other.sign(prof)}) == {"ok": False, "error": "bad signature"}
    tampered = ad(me, prof)
    tampered["profile"] = dict(prof, url="http://evil")  # the url is part of what is signed
    assert (await b0.advertise(tampered))["ok"] is False


async def test_r4_2_expired_profiles_and_notices_disappear(b0, clock):
    me, issuer = Identity.generate(), Identity.generate()
    await b0.advertise(ad(me, profile("http://me", "x", until=clock() + 10)))
    n = notice(issuer, until=clock() + 5)
    await b0.post_notice(n, issuer.sign(n))
    assert len(await b0.visible_notices(me.pub)) == 1
    assert b0.health()["notices"] == 1
    clock.tick(6)  # the notice expired, the profile is still active
    assert await b0.visible_notices(me.pub) == [] and b0.health()["notices"] == 0
    clock.tick(5)  # now the profile expired too
    assert await b0.list_profiles(Caller.anonymous(), local=True) == []
    assert await b0.find(Caller.anonymous(), "x") == []
    assert await b0.visible_notices(me.pub) is None  # no active profile -> refused (R4-7)


async def test_r4_3_list_profiles_merges_neighbors(net, clock):
    a, b = Identity.generate(), Identity.generate()
    await net.brokers[0].advertise(ad(a, profile("http://a", "a", now=clock())))
    await net.brokers[1].advertise(ad(b, profile("http://b", "b", now=clock())))
    got = await net.brokers[0].list_profiles(Caller.anonymous())
    assert {p["pub"] for p in got} == {a.pub, b.pub}
    assert {p["broker"] for p in got} == {"b0", "b1"}


async def test_r4_3_dead_neighbor_does_not_break_answers(net, clock):
    a = Identity.generate()
    await net.brokers[0].advertise(ad(a, profile("http://a", "a", now=clock())))
    net.gw.kill("mem://b1")
    got = await net.brokers[0].list_profiles(Caller.anonymous())
    assert [p["pub"] for p in got] == [a.pub]


async def test_r4_4_find_by_text_role_label_exclude_k(net, clock, settings):
    rec, rev, plain, partner = (Identity.generate() for _ in range(4))
    await net.brokers[0].advertise(ad(rec, profile("http://rec", "정보보안 감사 기록 보관 열람 통제", offers=["record"], now=clock())))
    await net.brokers[1].advertise(ad(rev, profile("http://rev", "공모 심사 평가 기준 심사위원", offers=["review"], now=clock())))
    await net.brokers[2].advertise(ad(plain, profile("http://p", "기록 보관 업무를 해 본 마케터", now=clock())))
    await net.brokers[2].advertise(ad(partner, profile("http://x", "기록 보관 감사", labels=["소속:협력사"], now=clock())))
    hits = await net.brokers[0].find(Caller.anonymous(), "기록 보관 감사", k=10)
    assert hits[0]["pub"] in (rec.pub, partner.pub) and len(hits) == 4
    assert [h["score"] for h in hits] == sorted([h["score"] for h in hits], reverse=True)
    only_rec = await net.brokers[1].find(Caller.anonymous(), "기록 보관 감사", role="record")
    assert [h["pub"] for h in only_rec] == [rec.pub] and only_rec[0]["broker"] == "b0"
    sds = await net.brokers[0].find(Caller.anonymous(), "기록 보관 감사", labels=[SDS], k=10)
    assert partner.pub not in {h["pub"] for h in sds}
    ex = await net.brokers[0].find(Caller.anonymous(), "기록 보관 감사", exclude=[rec.pub], k=10)
    assert rec.pub not in {h["pub"] for h in ex}
    assert len(await net.brokers[0].find(Caller.anonymous(), "기록", k=2)) == 2
    assert len(await net.brokers[0].find(Caller.anonymous(), "기록")) <= settings.search_k
    h0 = hits[0]
    assert set(h0) == {"pub", "pen_name", "url", "offers", "labels", "summary", "score", "broker"}


async def test_r4_4_k_is_capped(b0, clock, settings):
    for i in range(settings.search_max_k + 5):
        p = Identity.generate()
        await b0.advertise(ad(p, profile(f"http://{i}", "기록", now=clock())))
    assert len(await b0.find(Caller.anonymous(), "기록", k=10_000)) == settings.search_max_k


async def test_r4_5_notice_is_shared_once_and_reverified(net, clock):
    issuer, viewer = Identity.generate(), Identity.generate()
    await net.brokers[2].advertise(ad(viewer, profile("http://v", "v", now=clock())))
    n = notice(issuer, now=clock())
    r = await net.brokers[0].post_notice(n, issuer.sign(n))
    assert r["ok"] and r["visible_to"] == 0
    assert [x["notice_id"] for x in await net.brokers[2].visible_notices(viewer.pub)] == ["call-1"]
    assert net.gw.calls.count(("share_notice", "mem://b1")) == 1  # passed on once, not re-forwarded by b1/b2
    assert len([c for c in net.gw.calls if c[0] == "share_notice"]) == 2
    forged = dict(n, notice_id="call-2")
    assert await net.brokers[1].post_notice(forged, issuer.sign(n), shared=True) == {"ok": False, "error": "bad signature"}


async def test_r4_6_only_issuer_closes_and_close_is_shared(net, clock):
    issuer, viewer, stranger = Identity.generate(), Identity.generate(), Identity.generate()
    await net.brokers[1].advertise(ad(viewer, profile("http://v", "v", now=clock())))
    n = notice(issuer, now=clock())
    await net.brokers[0].post_notice(n, issuer.sign(n))
    assert await net.brokers[0].close_notice("call-1", stranger.sign({"close": "call-1"})) == {"ok": False, "error": "not the issuer"}
    assert await net.brokers[0].close_notice("nope", issuer.sign({"close": "nope"})) == {"ok": False, "error": "not the issuer"}
    assert (await net.brokers[0].close_notice("call-1", issuer.sign({"close": "call-1"})))["ok"]
    clock.tick(0.001)
    assert await net.brokers[1].visible_notices(viewer.pub) == []


async def test_r4_7_audience_labels_decide_visibility(b0, clock):
    issuer, sds, partner, both = (Identity.generate() for _ in range(4))
    await b0.advertise(ad(sds, profile("http://s", "s", labels=[SDS], now=clock())))
    await b0.advertise(ad(partner, profile("http://p", "p", labels=["소속:협력사"], now=clock())))
    await b0.advertise(ad(both, profile("http://b", "b", labels=[SDS, "직무:개발"], now=clock())))
    n1 = notice(issuer, "n1", audience={"소속": "삼성SDS"}, now=clock())
    n2 = notice(issuer, "n2", audience={"소속": "삼성SDS", "직무": "개발"}, now=clock())
    n3 = notice(issuer, "n3", audience={}, now=clock())
    for n in (n1, n2, n3):
        await b0.post_notice(n, issuer.sign(n))
    ids = lambda pub: sorted(x["notice_id"] for x in b0._visible_now(pub))
    assert ids(sds.pub) == ["n1", "n3"]
    assert ids(partner.pub) == ["n3"]
    assert ids(both.pub) == ["n1", "n2", "n3"]
    assert (await b0.post_notice(n1, issuer.sign(n1)))["visible_to"] == 2
    assert await b0.visible_notices(Identity.generate().pub) is None  # no profile on this broker -> refused


async def test_r4_8_search_notices_within_visible(b0, clock):
    issuer, viewer = Identity.generate(), Identity.generate()
    await b0.advertise(ad(viewer, profile("http://v", "v", now=clock())))
    a = notice(issuer, "a", text="클라우드 비용 절감 아이디어", now=clock())
    b = notice(issuer, "b", text="신입 사원 온보딩 아이디어", now=clock())
    c = notice(issuer, "c", text="클라우드 보안 협력사 전용", audience={"소속": "협력사"}, now=clock())
    for n in (a, b, c):
        await b0.post_notice(n, issuer.sign(n))
    hits = await b0.search_notices(viewer.pub, "클라우드")
    assert [x["notice_id"] for x in hits] == ["a"] and hits[0]["score"] > 0


async def test_r4_9_closed_group_needs_owner_grant_until_expiry(settings, clock):
    owner, member, outsider = (Identity.generate() for _ in range(3))
    net = Net(settings, clock, n=1, owner_pub=owner.pub)
    d = net.brokers[0]
    assert (await d.advertise(ad(member, profile("http://m", "심사", now=clock()))))["error"] == "members of this peer group only"
    g = {"pub": member.pub, "until": clock() + 100}
    assert await d.grant(g, outsider.sign(g)) == {"ok": False, "error": "grant must be signed by the group owner"}
    assert (await d.grant(g, owner.sign(g)))["ok"]
    assert (await d.advertise(ad(member, profile("http://m", "심사", now=clock()))))["ok"]
    assert await d.list_profiles(Caller(outsider.pub)) is None
    assert await d.find(Caller(outsider.pub), "심사") is None
    assert await d.find(Caller.anonymous(), "심사") is None
    assert [p["pub"] for p in await d.find(Caller(member.pub), "심사")] == [member.pub]
    assert len(await d.list_profiles(Caller(owner.pub))) == 1  # the owner is always a member
    clock.tick(101)
    assert await d.find(Caller(member.pub), "심사") is None  # the grant simply expired


async def test_r4_9_open_group_rejects_grants(b0):
    g = {"pub": "x", "until": 1}
    assert (await b0.grant(g, "00"))["ok"] is False


async def test_r4_10_health(net, clock):
    b = net.brokers[0]
    await b.advertise(ad(Identity.generate(), profile("http://a", "a", now=clock())))
    hl = b.health()
    assert hl == {"ok": True, "name": "b0", "pub": b.identity.pub, "profiles": 1, "notices": 0,
                  "neighbors": ["mem://b1", "mem://b2"], "closed": False}


async def test_pa8_minimal_notice_is_accepted_and_searchable(b0, clock):
    issuer, viewer = Identity.generate(), Identity.generate()
    await b0.advertise(ad(viewer, profile("http://v", "v", labels=[], now=clock())))
    n = {"notice_id": "bare", "issuer_pub": issuer.pub, "until": clock() + 60}
    assert (await b0.post_notice(n, issuer.sign(n)))["ok"]
    assert [x["notice_id"] for x in await b0.visible_notices(viewer.pub)] == ["bare"]  # no audience -> everyone
    assert await b0.search_notices(viewer.pub, "anything") == []
    m = {"notice_id": "m", "issuer_pub": issuer.pub, "until": clock() + 60, "text": "TF 모집 클라우드", "anything": {"app": "data"}}
    await b0.post_notice(m, issuer.sign(m))
    hits = await b0.search_notices(viewer.pub, "클라우드")
    assert [x["notice_id"] for x in hits] == ["m"] and hits[0]["anything"] == {"app": "data"}
