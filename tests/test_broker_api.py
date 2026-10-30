"""R4 over HTTP: Starlette app via ASGI transport; BrokerClient and InMemoryBrokerClient are interchangeable."""
import httpx
import pytest

from arena.broker.api import build_broker_app
from arena.broker.client import BrokerAPI, BrokerClient, InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.search import BM25Searcher
from arena.signing import sign_request
from tests.test_broker_service import SDS, notice, profile


def make(settings, owner_pub=None):
    return BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="bx", neighbors=[], owner_pub=owner_pub)


def http_for(svc):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=build_broker_app(svc)), base_url="http://broker")


@pytest.fixture
def svc(settings):
    return make(settings)


@pytest.fixture
def http(svc):
    return http_for(svc)


@pytest.fixture(params=["http", "memory"])
def client(request, svc, http, settings) -> BrokerAPI:
    return BrokerClient("http://broker", settings, http_client=http) if request.param == "http" else InMemoryBrokerClient(svc)


async def test_r4_1_post_profiles_raw(http):
    me = Identity.generate()
    prof = profile("http://me", "인프라", now=1e10)
    r = await http.post("/profiles", json={"pub": me.pub, "profile": prof, "sig": me.sign(prof)})
    assert r.status_code == 200 and r.json() == {"ok": True, "updated": False}
    r = await http.post("/profiles", json={"pub": me.pub, "profile": prof, "sig": "00"})
    assert r.status_code == 400
    assert (await http.post("/profiles", json={"pub": me.pub})).status_code == 400


async def test_r4_7_notices_need_signed_request(http):
    assert (await http.get("/notices")).status_code == 401
    stranger = Identity.generate()
    r = await http.get("/notices", headers=sign_request(stranger, "GET", "/notices"))
    assert r.status_code == 403 and r.json()["error"] == "signed request from a registered profile required"


async def test_r4_12_full_flow_through_either_client(client):
    import time
    now = time.time()
    issuer, viewer, rec, partner = (Identity.generate() for _ in range(4))
    assert (await client.advertise(viewer, profile("http://v", "신입 온보딩 교육 담당", now=now)))["ok"]
    assert (await client.advertise(rec, profile("http://r", "감사 기록 보관", offers=["record"], now=now)))["ok"]
    assert (await client.advertise(partner, profile("http://p", "협력사 분석가", labels=["소속:협력사"], now=now)))["ok"]
    assert len((await client.list_profiles())["profiles"]) == 3
    f = await client.find("기록 보관", role="record")
    assert [p["pub"] for p in f["peers"]] == [rec.pub]
    f = await client.find("분석가 온보딩", labels=[SDS], exclude=[rec.pub], k=5)
    assert [p["pub"] for p in f["peers"]] == [viewer.pub]
    n = notice(issuer, now=now)
    assert (await client.post_notice(issuer, n))["visible_to"] == 2
    assert [x["notice_id"] for x in (await client.list_notices(viewer))["notices"]] == ["call-1"]
    assert (await client.list_notices(partner))["notices"] == []
    assert (await client.list_notices(Identity.generate()))["ok"] is False
    assert [x["notice_id"] for x in (await client.search_notices(viewer, "신입 사원"))["hits"]] == ["call-1"]
    assert (await client.close_notice(viewer, "call-1"))["ok"] is False
    assert (await client.close_notice(issuer, "call-1"))["ok"]
    assert (await client.list_notices(viewer))["notices"] == []
    hl = await client.health()
    assert hl["ok"] and hl["profiles"] == 3 and hl["closed"] is False


@pytest.mark.parametrize("kind", ["http", "memory"])
async def test_r4_9_closed_group_over_both_clients(settings, kind):
    import time
    owner, member, outsider = (Identity.generate() for _ in range(3))
    svc = make(settings, owner_pub=owner.pub)
    c = BrokerClient("http://broker", settings, http_client=http_for(svc)) if kind == "http" else InMemoryBrokerClient(svc)
    assert (await c.advertise(member, profile("http://m", "심사 전문가", offers=["review"], now=time.time())))["ok"] is False
    assert (await c.grant(outsider, member.pub, time.time() + 60))["ok"] is False
    assert (await c.grant(owner, member.pub, time.time() + 60))["ok"]
    assert (await c.advertise(member, profile("http://m", "심사 전문가", offers=["review"], now=time.time())))["ok"]
    denied = await c.find("심사", identity=outsider)
    assert denied == {"ok": False, "error": "members of this peer group only"}
    assert (await c.find("심사"))["ok"] is False
    assert (await c.list_profiles(identity=outsider))["ok"] is False
    assert [p["pub"] for p in (await c.find("심사", role="review", identity=owner))["peers"]] == [member.pub]
    assert len((await c.list_profiles(identity=member))["profiles"]) == 1


async def test_r4_9_bad_signature_on_closed_group_is_401(settings):
    owner = Identity.generate()
    http = http_for(make(settings, owner_pub=owner.pub))
    h = sign_request(owner, "GET", "/profiles")
    h["X-Arena-Sig"] = "00" * 64
    assert (await http.get("/profiles/search", params={"q": "x"}, headers=h)).status_code == 401
