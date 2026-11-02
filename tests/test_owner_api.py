"""P6-P5, P6-P6: the owner API (HTTP, token) over OwnerService, and the sample personal peer's assembly."""
import dataclasses

import httpx
import pytest

from arena.peer.desk.api import build_owner_api
from arena.peer.desk.service import OwnerService
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)
from tests.test_desk import desk_peer, hosted

TOKEN = "t0ken"


async def client(e, llm=False):
    p, desk = await desk_peer(e, "me", llm=llm)
    app = build_owner_api(OwnerService(p, desk), TOKEN)
    hc = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://desk", headers={"Authorization": f"Bearer {TOKEN}"})
    return p, desk, hc


async def test_p6p5_the_owner_api_needs_its_token(eco):
    _, _, hc = await client(eco)
    async with httpx.AsyncClient(transport=hc._transport, base_url="http://desk") as anon:
        assert (await anon.get("/api/state")).status_code == 401
        assert (await anon.get("/api/state", headers={"Authorization": "Bearer wrong"})).status_code == 401
        assert (await anon.get("/")).status_code == 200  # the screen itself carries no data
    me = (await hc.get("/api/state")).json()["me"]
    assert me["operator"] == "human" and me["llm"] is False
    await hc.aclose()


async def test_p6p5_a_human_takes_part_through_the_api(eco):
    p, desk, hc = await client(eco)
    ev = await hosted(eco)
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    st = (await hc.get("/api/state")).json()
    assert [e["event_id"] for e in st["events"]] == [ev] and st["events"][0]["drive"] == "manual" and st["open_items"] >= 1
    items = (await hc.get("/api/items")).json()["items"]
    assert items[0]["kind"] == "notice" and (await hc.post(f"/api/items/{items[0]['id']}/answer", json={})).json()["ok"]
    detail = (await hc.get(f"/api/events/{ev}")).json()
    assert "join_event" in [t["name"] for t in detail["tools"]] and "지금 시각" in detail["state_line"]
    assert (await hc.post(f"/api/events/{ev}/tools/join_event", json={"args": {}})).json()["ok"]
    await settle(eco.host)
    assert p.identity.pub in asst(eco.host).events[ev].applicants
    r = await hc.post(f"/api/events/{ev}/drive", json={"drive": "auto"})
    assert r.status_code == 400 and "manual" in r.json()["error"]
    assert (await hc.get("/api/events/nope")).status_code == 404
    await hc.aclose()


async def test_p6p5_the_owner_hosts_an_event_and_answers_a_question(eco):
    p, desk, hc = await client(eco)
    bad = await hc.post("/api/events", json={"title": "", "kind": "k", "rules": RULES})
    assert bad.status_code == 400 and "title" in bad.json()["error"]
    r = (await hc.post("/api/events", json={"title": "점심 내기", "kind": "놀이", "rules": RULES, "policy": {"roles": ["member"]},
                                             "schedule": [{"at": 4102444800.0, "code": "start"}]})).json()
    assert r["ok"]
    detail = (await hc.get(f"/api/events/{r['event_id']}")).json()
    assert detail["role"] == "host" and detail["schedule"][0]["code"] == "start" and len(detail["timers"]) == 1
    import asyncio
    task = asyncio.create_task(p.owner.ask("이대로 할까요?", "맥락", event_id=r["event_id"]))
    await asyncio.sleep(0)
    q = (await hc.get("/api/items")).json()["items"][0]
    assert q["kind"] == "question"
    assert (await hc.post(f"/api/items/{q['id']}/answer", json={"yes": True, "why": "좋다"})).json()["ok"]
    assert (await task).yes
    assert (await hc.post(f"/api/items/{q['id']}/answer", json={"yes": True})).status_code == 400  # answered once
    await hc.aclose()


def test_p6p6_the_personal_peer_is_a_human_peer_without_an_llm_and_an_agent_with_one(tmp_path, settings):
    from arena.config import ConfigError
    from arena.peers import personal
    base = dict(personal_peer_home=str(tmp_path / "home"), personal_peer_brokers=["public=http://127.0.0.1:1"])
    peer, service, token = personal.build(dataclasses.replace(settings, llm_backend="none", **base))
    assert peer.operator() == "human" and token and service.state()["me"]["operator"] == "human"
    again, _, token2 = personal.build(dataclasses.replace(settings, llm_backend="none", **base))
    assert again.identity.pub == peer.identity.pub and token2 == token  # the same peer and token after a restart
    with pytest.raises(ConfigError):  # an LLM asked for but not set up is an error, not a silent human peer
        personal.build(dataclasses.replace(settings, llm_backend="compat", llm_base_url="", **dict(base, personal_peer_home=str(tmp_path / "h2"))))
    agent, _, _ = personal.build(dataclasses.replace(settings, llm_backend="compat", llm_base_url="http://llm", llm_api_key="k", llm_model_agent="m",
                                                     **dict(base, personal_peer_home=str(tmp_path / "h2"))))
    assert agent.operator() == "agent"
    with pytest.raises(ConfigError):
        personal.build(dataclasses.replace(settings, llm_backend="none", personal_peer_home=str(tmp_path / "h3")))
