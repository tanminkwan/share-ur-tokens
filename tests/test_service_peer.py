"""P6-A1 ~ A5: the API-providing peer template. A spec file alone makes a service peer (python functions or an HTTP API);
every answer carries a signed receipt; an op may record its computed result on the ledger as the event's contracted role;
service peers (and app distribution peers) are found on the broker; the basic assistant calls them with call_service."""
import dataclasses
import json

import httpx
import pytest

from arena.crypto import Identity
from arena.peer.service import ServiceApp, load_spec
from arena.sdk import verify_service_receipt
from tests.test_assistant import asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

APP_ID = "5c7e2f10-6a4b-4d8e-9f31-2b6c8d0e1a47"


def spec(**over):
    s = {"name": "calc", "version": "1.0", "app_id": APP_ID, "description": "더하기와 큰 수 고르기", "offers": ["계산"],
         "roles": ["referee"],
         "ops": {"add": {"python": "tests.service_samples.calc:add", "description": "두 수를 더한다"},
                 "bigger": {"python": "tests.service_samples.calc:bigger", "description": "큰 수를 고른다", "record": {"kind": "verdict"}},
                 "item": {"http": {"method": "GET", "path": "/items/{id}"}, "description": "물건 조회"}},
         "base_url": "http://backend"}
    s.update(over)
    return s


def backend():
    async def handler(request: httpx.Request):
        return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[1], "name": "의자"})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_p6a1_a_spec_file_is_checked_and_loaded(tmp_path):
    f = tmp_path / "calc.json"
    f.write_text(json.dumps(spec()), encoding="utf-8")
    assert load_spec(str(f))["name"] == "calc"
    for bad in (spec(app_id="x"), spec(ops={}), spec(ops={"a": {"python": "x:y", "http": {"method": "GET", "path": "/"}}})):
        f.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            load_spec(str(f))


async def test_p6a1_a2_ops_answer_with_a_signed_receipt(eco):
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec(), http=backend())])
    req = {"op": "add", "input": {"a": 2, "b": 3}}
    r = await svc.handle(req)
    assert r["ok"] and r["result"] == {"sum": 5}
    assert verify_service_receipt(r, req, svc.identity.pub) is None
    assert verify_service_receipt(dict(r, result={"sum": 6}), req, svc.identity.pub)  # a changed result no longer matches
    assert verify_service_receipt(r, dict(req, input={"a": 9, "b": 3}), svc.identity.pub)  # nor another request
    assert verify_service_receipt(r, req, Identity.generate().pub)  # nor another service
    h = await svc.handle({"op": "item", "input": {"path": {"id": "7"}}})
    assert h["ok"] and h["result"]["result"] == {"id": "7", "name": "의자"} and verify_service_receipt(h, {"op": "item", "input": {"path": {"id": "7"}}}, svc.identity.pub) is None


async def test_p6a1_groups_and_signed_callers_are_enforced(eco):
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec(allow_groups=["g-only"], require_signed=True))])
    assert "group" in (await svc.handle({"op": "add", "input": {"a": 1, "b": 1}}, {"group_id": "public"}))["error"]


async def test_p6a3_an_op_records_its_computed_result_as_the_events_contracted_role(eco):
    from tests.test_assistant import RULES
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec())])
    await svc.advertise()
    host = eco.host
    pol = {"roles": ["member", "referee"], "attest_roles": {"verdict": "referee"}}
    ev = await asst(host).host_event(ctx(host), title="판정", kind="k", rules=RULES, policy=pol, instruction="기다려라")
    await settle(host)
    st = asst(host).events[ev]
    msg = {"op": "bigger", "input": {"a": 3, "b": 7}, "event_id": ev, "subject": "r1", "recorder_url": st.recorder_url}
    refused = await svc.handle(msg)  # not contracted yet: the ledger refuses the record
    assert not refused["ok"] and "referee" in refused["error"]
    host.llm.push("contract", role="referee", peer=svc.pen)  # a peer that offers the role on its profile may be contracted
    await asst(host).feed(ctx(host), ev, "판정 peer와 계약하라")
    await settle(host)
    assert ["referee", svc.identity.pub] in st.contracts
    r = await svc.handle(msg)
    assert r["ok"] and r["result"] == {"winner": "b"} and r["record"]
    at = [e for e in eco.svc.ledger.chain if e["type"] == "attest"][-1]["payload"]
    assert at["kind"] == "verdict" and at["parties"] == [svc.identity.pub] and at["value"]["result"] == {"winner": "b"}


async def test_p6a4_service_peers_and_app_stores_are_found_on_the_broker(eco):
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec())])
    await svc.advertise()
    prof = next(p for p in eco.broker.profiles.values() if p["pub"] == svc.identity.pub)
    assert "service:calc" in prof["offers"] and prof["service"]["ops"]["bigger"] == "큰 수를 고른다"
    found = await eco.host.brokers["public"].find("계산", role="service:calc", identity=eco.host.identity)
    assert [p["pub"] for p in found["peers"]] == [svc.identity.pub]
    from arena.peer.app_store import AppStoreRole
    from arena.peer.app_install import AppInstaller
    store = eco.peer("store", apps=[AppStoreRole(eco.s, str(eco.tmp / "store-dir"))])
    await store.advertise()
    inst = AppInstaller(dataclasses.replace(eco.s, app_store_discover=True))
    assert await inst.store_urls(eco.host.ctx(eco.host.events)) == [store.config.url]


async def test_p6a5_the_assistant_calls_a_service_and_keeps_its_receipt(eco):
    from tests.test_assistant import joined
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec())])
    await svc.advertise()
    ev = await joined(eco)
    a = eco.a
    a.llm.push("call_service", peer=svc.pen, op="add", input_json=json.dumps({"a": 4, "b": 5}))
    await asst(a).feed(ctx(a), ev, "계산을 맡겨라")
    await settle(a)
    st = asst(a).events[ev]
    assert any('"sum": 9' in x for x in st.transcript)
    assert len(st.service_receipts) == 1 and st.service_receipts[0]["receipt"]["service"] == svc.identity.pub


def test_p6a1_the_service_and_app_store_runners_build_their_peers(tmp_path, settings):
    from arena.peers import app_store, service
    s = dataclasses.replace(settings, service_peer_brokers=["public=http://127.0.0.1:1"], service_peer_area=str(tmp_path / "svc"),
                            service_peer_key_file=str(tmp_path / "svc.key"), app_store_peer_brokers=["public=http://127.0.0.1:1"],
                            app_store_peer_area=str(tmp_path / "store"), app_store_peer_key_file=str(tmp_path / "store.key"),
                            app_store_dir=str(tmp_path / "store-dir"))
    f = tmp_path / "calc.json"
    f.write_text(json.dumps(spec()), encoding="utf-8")
    p = service.build(s, str(f))
    assert "add" in p.skills() and "service:calc" in p.offers()
    assert "app_get" in app_store.build(s).skills()


async def test_p6a5_the_host_sees_open_roles_with_the_peers_offering_them_and_its_instruction_stays_pinned(eco):
    """live with-elements run 2: the host's instruction (naming the referee) scrolled away and the host kept asking its owner
    who the referee was. The owner's instruction is now pinned in the prompt, and the state line lists the policy roles
    nobody holds yet with the peers whose profile offers them."""
    from tests.test_assistant import RULES, asst, ctx, settle
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec())])
    await svc.advertise()
    host = eco.host
    ev = await asst(host).host_event(ctx(host), title="판", kind="k", rules=RULES, policy={"roles": ["member", "referee"]},
                                     instruction="판정 peer와 referee 계약을 맺어라")
    await settle(host)
    st = asst(host).events[ev]
    await asst(host).progress_entries(ctx(host), st)
    system = asst(host)._system(ctx(host), st)
    assert "[소유자의 지시] 판정 peer와 referee 계약을 맺어라" in system
    assert f"referee(프로필에 내건 peer: {svc.pen})" in system and "member(프로필에 내건 peer: 없음)" in system
    host.llm.push("contract", role="referee", peer=svc.pen)
    await asst(host).feed(ctx(host), ev, "계약하라")
    await settle(host, svc)
    await asst(host).progress_entries(ctx(host), st)
    assert "referee(" not in asst(host)._system(ctx(host), st)
