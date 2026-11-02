"""R3 over HTTP: the Starlette app (ASGI transport) and both clients behave the same."""
import httpx
import pytest

from arena.recorder.api import build_recorder_app
from arena.recorder.client import RecorderAPI, RecorderClient, InMemoryRecorderClient
from arena.recorder.service import RecorderService
from arena.crypto import Identity
from arena.ledger import MemoryStore
from arena.signing import sign_request
from tests.test_ledger import Cast


@pytest.fixture
def cast():
    return Cast()


@pytest.fixture
def reader():
    return Identity.generate()


@pytest.fixture
def svc(settings, reader):
    return RecorderService.build(settings, identity=Identity.generate(), store=MemoryStore(), readers=[reader.pub])


@pytest.fixture
def http(svc):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=build_recorder_app(svc)), base_url="http://recorder")


@pytest.fixture(params=["http", "memory"])
def client(request, svc, http, settings) -> RecorderAPI:
    if request.param == "http":
        return RecorderClient("http://recorder", settings, http_client=http)
    return InMemoryRecorderClient(svc)


async def test_r3_1_post_entries(http, cast):
    kind, p, sigs = cast.publish(ev=None)
    r = await http.post("/entries", json={"type": kind, "payload": p, "sigs": sigs})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["seq"] == 0
    r = await http.post("/entries", json={"type": kind, "payload": p, "sigs": sigs})
    assert r.status_code == 400 and r.json()["error"].startswith("content already published")
    r = await http.post("/entries", content=b"not json")
    assert r.status_code == 400 and not r.json()["ok"]
    r = await http.post("/entries", json={"type": "publish"})
    assert r.status_code == 400 and "payload" in r.json()["error"]


async def test_r3_2_get_entry(http, cast):
    kind, p, sigs = cast.publish(ev=None)
    rec = (await http.post("/entries", json={"type": kind, "payload": p, "sigs": sigs})).json()
    r = (await http.get(f"/entries/{rec['hash']}")).json()
    assert r["exists"] and r["seal_ok"] and r["type"] == "publish"
    assert (await http.get("/entries/abc")).json()["exists"] is False


async def test_r3_3_and_r3_6_audit_health(http):
    assert (await http.get("/audit")).json()["status"] == "ok"
    hl = (await http.get("/health")).json()
    assert hl["ok"] and hl["length"] == 0


async def test_r3_4_chain_requires_signed_allow_listed_reader(http, reader, cast, settings):
    assert (await http.get("/chain")).status_code == 401
    r = await http.get("/chain", headers=sign_request(reader, "GET", "/chain"))
    assert r.status_code == 200 and r.json()["chain"] == []
    stranger = Identity.generate()
    r = await http.get("/chain", headers=sign_request(stranger, "GET", "/chain"))
    assert r.status_code == 403 and r.json()["error"] == "not authorized"
    r = await http.get("/chain", headers=sign_request(reader, "GET", "/audit"))  # signature for another path
    assert r.status_code == 401


async def test_r3_5_access_log_endpoint(http, reader):
    await http.get("/chain", headers=sign_request(Identity.generate(), "GET", "/chain"))
    r = await http.get("/access-log", headers=sign_request(reader, "GET", "/access-log"))
    assert r.status_code == 200 and r.json()["log"][-1]["granted"] is False
    r = await http.get("/access-log", headers=sign_request(Identity.generate(), "GET", "/access-log"))
    assert r.status_code == 403


async def test_r3_9_clients_share_one_interface(client, cast, reader):
    rec = await client.record(*cast.publish(ev=None))
    assert rec["ok"] and rec["seq"] == 0
    bad = await client.record(*cast.publish(ev=None))
    assert bad["ok"] is False and bad["error"].startswith("content already published")
    v = await client.verify(rec["hash"])
    assert v["exists"] and v["type"] == "publish"
    assert (await client.audit())["length"] == 1
    assert (await client.health())["length"] == 1
    assert len((await client.read_chain(reader))["chain"]) == 1
    assert (await client.read_chain(Identity.generate()))["ok"] is False
    assert (await client.read_access_log(reader))["ok"]
