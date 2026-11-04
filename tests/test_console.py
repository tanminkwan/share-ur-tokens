"""The console (user 2026-11-04: "a2a 방식이어도 관전 또는 인간 개입을 위한 인간을 위한 통합 ui는 필요해. 물론 plugin app이고"):
one window to watch an event's conversation as it happens and to step in. The timeline says who spoke, in which
direction; the person speaks as their peer (one a2a message), instructs their agent, answers questions. Scripted LLM only."""
import httpx

from arena.bundled.console import ConsoleApp
from arena.bundled.console.api import build_console_api
from arena.bundled.owner_service import OwnerService
from tests.test_assistant import asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)
from tests.test_desk import desk_peer, hosted

TOKEN = "console-t0ken"


async def console_peer(e, name="me", llm=False):
    p, desk = await desk_peer(e, name, llm=llm)
    console = ConsoleApp(OwnerService(p, desk), e.s, "127.0.0.1", 0, TOKEN)
    p.apps.append(console)
    p._register_one(console, builtin=False)
    console.bind(p.ctx(console))
    hc = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_console_api(console, TOKEN)), base_url="http://console",
                           headers={"Authorization": f"Bearer {TOKEN}"})
    return p, desk, console, hc


async def joined(e, p):
    """an event the host opened; the person joined it by hand"""
    ev = await hosted(e)
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    assert (await OwnerService(p, p.app_by_name("platform.owner_desk").desk).run_tool(ev, "join_event", {}))["ok"] is not False
    await settle(e.host)
    return ev


async def test_the_timeline_shows_who_said_what_and_the_person_speaks_as_their_peer(eco):
    p, desk, console, hc = await console_peer(eco)
    ev = await joined(eco, p)
    host_side = asst(eco.host).events[ev].timeline
    assert any(x["dir"] == "in" and x["kind"] == "join" and x["who"] for x in host_side)  # the host watches who joined
    # the host's agent speaks to the person; the person sees it as an incoming line
    eco.host.llm.push("send", to=p.pen, text="환영합니다. 규칙을 읽어 주세요", data={})
    await asst(eco.host).feed(ctx(eco.host), ev, "계속")
    await settle(eco.host, p)
    view = (await hc.get(f"/api/events/{ev}")).json()
    assert any(x["dir"] == "in" and x["by"] == "peer" and "환영합니다" in x["text"] for x in view["timeline"])
    assert [x["handle"] for x in view["peers"]][0]  # whom I may speak to: the host first
    out_host = [x for x in host_side if x["dir"] == "out"]
    assert out_host and out_host[-1]["by"] == "agent" and out_host[-1]["who"] == p.pen  # the host's agent spoke (watched on its side)
    # the person steps in: one message to the host (a2a, walkie-talkie)
    to = view["peers"][0]["handle"]
    r = await hc.post(f"/api/events/{ev}/say", json={"to": to, "text": "네, 읽었습니다"})
    assert r.status_code == 200
    await settle(eco.host, p)
    mine = (await hc.get(f"/api/events/{ev}")).json()["timeline"]
    assert mine[-1]["dir"] == "out" and mine[-1]["by"] == "owner" and mine[-1]["text"] == "네, 읽었습니다" and mine[-1]["who"] == to
    assert any(x["dir"] == "in" and x["text"] == "네, 읽었습니다" for x in host_side)  # it reached the host
    assert (await hc.post(f"/api/events/{ev}/say", json={"to": to, "text": "  "})).status_code == 400
    # no LLM here: nothing to instruct, no agent to talk with
    assert (await hc.post(f"/api/events/{ev}/tell", json={"text": "참가해"})).status_code == 400
    assert (await hc.get("/api/agent")).json() == {"available": False, "messages": []}
    assert (await hc.post("/api/agent/say", json={"text": "안녕"})).status_code == 400
    # the owner API is all there too, behind the same token
    assert (await hc.get("/api/state")).json()["me"]["operator"] == "human"
    async with httpx.AsyncClient(transport=hc._transport, base_url="http://console") as anon:
        assert (await anon.get(f"/api/events/{ev}")).status_code == 401 and (await anon.post(f"/api/events/{ev}/say", json={})).status_code == 401


async def test_with_an_agent_the_person_instructs_it_and_watches_it_think_and_act(eco):
    p, desk, console, hc = await console_peer(eco, llm=True)
    ev = await hosted(eco)
    p.llm.push("wait")
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    p.llm.push("join_event")
    p.llm.push("wait")
    r = await hc.post(f"/api/events/{ev}/tell", json={"text": "참가 신청해"})
    assert r.status_code == 200
    await settle(p, eco.host)
    t = (await hc.get(f"/api/events/{ev}")).json()["timeline"]
    kinds = [(x["by"], x["kind"]) for x in t]
    assert ("owner", "instruction") in kinds and ("agent", "action") in kinds and ("system", "notice") in kinds
    assert any(x["kind"] == "action" and "참가 신청" in x["text"] and "완료" in x["text"] for x in t)
    assert (await hc.get("/api/agent")).json()["available"] is True
    p.llm.push("reply", text="참가 신청을 해 두었습니다")
    said = (await hc.post("/api/agent/say", json={"text": "어떻게 됐어?"})).json()
    assert said["ok"] and said["messages"][-1]["text"] == "참가 신청을 해 두었습니다"
    assert [m["who"] for m in (await hc.get("/api/agent")).json()["messages"]] == ["owner", "agent"]
