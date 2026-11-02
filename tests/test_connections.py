"""P6-A6 ~ A8: connection methods are defined in advance (human, a2a, api); a profile lists the peer's connections; the
broker refuses unknown methods or missing fields; the api method is a fixed REST binding of the same ops, replies and
receipts; callers pick a method they can use from the profile; an api-only peer needs no A2A server and no AI agent;
the human method is never used automatically."""
import dataclasses
import json

import httpx

from arena.connections import CONNECTION_KINDS, check_connections
from arena.peer.service import ServiceApp
from arena.rest import RestTransport, build_rest_app
from arena.sdk import verify_service_receipt
from tests.test_assistant import asst, ctx, eco, joined, settle  # noqa: F401  (eco is a fixture)
from tests.test_service_peer import spec


def test_p6a6_three_connection_methods_are_defined_in_advance():
    assert set(CONNECTION_KINDS) >= {"human", "a2a", "api"}
    assert not CONNECTION_KINDS["human"].automatic and CONNECTION_KINDS["a2a"].automatic and CONNECTION_KINDS["api"].automatic
    assert check_connections([{"kind": "a2a", "url": "http://x"}, {"kind": "api", "url": "http://x/api"}]) is None
    assert "unknown" in check_connections([{"kind": "pigeon", "url": "x"}])
    assert "url" in check_connections([{"kind": "api"}])
    assert "contact" in check_connections([{"kind": "human"}])


async def test_p6a7_profiles_carry_connections_and_the_broker_checks_them(eco):
    a = eco.a
    prof = await a.advertise()
    assert prof["connections"] == [{"kind": "a2a", "url": a.config.url}]  # an agent peer: a2a by default
    a.settings = dataclasses.replace(a.settings, peer_human_contact="mailto:a@example.com")
    prof = await a.advertise()
    assert {"kind": "human", "contact": "mailto:a@example.com"} in prof["connections"]  # only when the owner chose to
    bad = dict(prof, connections=[{"kind": "pigeon", "url": "x"}])
    r = await eco.broker.advertise({"pub": a.identity.pub, "profile": bad, "sig": a.identity.sign(bad)})
    assert not r["ok"] and "connection" in r["error"]


async def test_p6a8_the_api_binding_serves_the_same_ops_with_receipts(eco):
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec())])
    app = build_rest_app(svc.handle)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://svc") as hc:
        r = (await hc.post("/ops/add", json={"input": {"a": 2, "b": 5}}, headers={"X-Arena-Group": "public"})).json()
        t = RestTransport(eco.s, http=hc)
        r2 = await t.call("http://svc", {"op": "add", "input": {"a": 1, "b": 1}}, meta={"group_id": "public"})
    assert r["ok"] and r["result"] == {"sum": 7}
    assert verify_service_receipt(r, {"op": "add", "input": {"a": 2, "b": 5}}, svc.identity.pub) is None
    assert r2["result"] == {"sum": 2}


async def test_p6a8_an_api_only_peer_is_called_through_its_profile_and_human_is_never_automatic(eco):
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec())])
    svc.config.connections = [{"kind": "api", "url": "http://svc-api"}, {"kind": "human", "contact": "tel:010-0000-0000"}]
    eco.t.handlers.pop(svc.config.url)  # no A2A server at all
    await svc.advertise()
    rest_app = build_rest_app(svc.handle)
    hc = httpx.AsyncClient(transport=httpx.ASGITransport(app=rest_app), base_url="http://svc-api")
    ev = await joined(eco)
    a = eco.a
    a.rest = RestTransport(eco.s, http=hc)
    a.llm.push("call_service", peer=svc.pen, op="add", input_json=json.dumps({"a": 4, "b": 5}))
    await asst(a).feed(ctx(a), ev, "계산을 맡겨라")
    await settle(a)
    st = asst(a).events[ev]
    assert any('"sum": 9' in x for x in st.transcript) and len(st.service_receipts) == 1
    a.llm.push("contact", peer=svc.pen)
    await asst(a).feed(ctx(a), ev, "사람에게 연락하고 싶다")
    await settle(a)
    assert any("tel:010-0000-0000" in x for x in st.transcript)
    await hc.aclose()


def test_p6a8_the_service_runner_opens_the_configured_connection_methods(tmp_path, settings):
    import pytest
    from arena.config import ConfigError
    from arena.peers import service
    base = dict(service_peer_brokers=["public=http://127.0.0.1:1"], service_peer_area=str(tmp_path / "svc"), service_peer_key_file=str(tmp_path / "k"))
    f = tmp_path / "calc.json"
    f.write_text(json.dumps(spec()), encoding="utf-8")
    only_api = service.build(dataclasses.replace(settings, service_peer_connections=["api"], **base), str(f))
    assert [c["kind"] for c in only_api.connections()] == ["api"] and "add" in only_api.connections()[0]["ops"]
    both = service.build(dataclasses.replace(settings, service_peer_connections=["a2a", "api"], **base), str(f))
    assert [c["kind"] for c in both.connections()] == ["a2a", "api"]
    with pytest.raises(ConfigError):
        service.build(dataclasses.replace(settings, service_peer_connections=["human"], **base), str(f))


async def test_p6a8_a_call_to_a_peer_without_the_op_names_the_peers_that_offer_it(eco):
    """live with-elements run 1: a player sent op judge to a peer that has no such op and got only "unknown op". The tool
    now names the peers whose posted profile offers the op, so the agent can call the right one."""
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec())])
    await svc.advertise()
    ev = await joined(eco)
    a = eco.a
    a.llm.push("call_service", peer=eco.host.pen, op="add", input_json=json.dumps({"a": 1, "b": 2}))
    await asst(a).feed(ctx(a), ev, "계산을 맡겨라")
    await settle(a)
    out = [x for x in asst(a).events[ev].transcript if "call_service 결과" in x][-1]
    assert "unknown op" in out and svc.pen in out
