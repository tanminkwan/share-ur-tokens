"""P6-P2 ~ P6-P4: the operator column, the owner desk and the drives. No real LLM: a human peer has none (NoLLM) and the
agent peers use the scripted double."""
import asyncio
import dataclasses

from arena.llm import NoLLM
from arena.peer.desk import DeskOwner, OwnerDesk, OwnerDeskApp
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

POL = {"roles": ["member"]}


async def desk_peer(e, name, llm=True):
    desk = OwnerDesk(lambda: 0.0)
    app = OwnerDeskApp(desk)
    p = e.peer(name, apps=[app], owner=DeskOwner(desk, e.s))
    if not llm:
        p.llm = NoLLM()
    await app.start(p.ctx(app))
    await p.advertise()  # the broker shows notices only to peers that posted a profile
    return p, desk


async def hosted(e, title="공모"):
    ev = await asst(e.host).host_event(ctx(e.host), title=title, kind="k", rules=RULES, policy=POL, instruction="신청자와 계약하라")
    await settle(e.host)
    return ev


async def test_p6p2_profiles_say_who_answers_and_the_broker_checks_it(eco):
    human, _ = await desk_peer(eco, "human", llm=False)
    assert (await human.advertise())["operator"] == "human" and (await eco.a.advertise())["operator"] == "agent"
    from arena.peers.app_store import build
    store = build(dataclasses.replace(eco.s, app_store_peer_brokers=["public=http://127.0.0.1:1"], app_store_peer_area=str(eco.tmp / "st"),
                                      app_store_peer_key_file=str(eco.tmp / "st.key"), app_store_dir=str(eco.tmp / "sd")))
    assert store.operator() == "service"
    bad = dict(human.last_profile, operator="robot")
    r = await eco.broker.advertise({"pub": human.identity.pub, "profile": bad, "sig": human.identity.sign(bad)})
    assert not r["ok"] and "operator" in r["error"]


async def test_p6p3_the_desk_waits_for_answers_times_out_as_no_and_closes_awaited_items_on_restart(eco):
    desk = OwnerDesk(lambda: 0.0)
    owner = DeskOwner(desk, dataclasses.replace(eco.s, desk_question_timeout_sec=5.0))
    task = asyncio.create_task(owner.ask("참가할까요?", "규칙", event_id="ev-1"))
    await asyncio.sleep(0)
    q = desk.list()[0]
    assert q.kind == "question" and q.event_id == "ev-1"
    desk.answer(q.id, {"yes": True, "why": "좋아요"})
    a = await task
    assert a.yes and a.why == "좋아요" and desk.list() == []
    quick = DeskOwner(desk, dataclasses.replace(eco.s, desk_question_timeout_sec=0.01))
    assert not (await quick.ask("빨리 답해")).yes  # no answer in time = no
    desk.add("question", "다시 시작하면?")
    kept = [it.to_dict() for it in desk.items.values()]
    again = OwnerDesk(lambda: 0.0)
    again.load(kept)
    assert again.list() == [] and len(again.list("all")) == 3  # the open question was closed as no


async def test_p6p4_manual_the_owner_drives_with_the_same_tools(eco):
    human, desk = await desk_peer(eco, "human", llm=False)
    ev = await hosted(eco)
    await human.events.watch_once(human.ctx(human.events))
    await settle(human)
    st = asst(human).events[ev]
    assert st.drive == "manual"
    notice = [it for it in desk.list() if it.kind == "notice"]
    assert notice and notice[0].event_id == ev  # the notice came to the desk, no LLM ran
    view = asst(human).tools_view(st)
    names = [t["name"] for t in view]
    assert "join_event" in names and "wait" not in names and "contract" not in names  # host-only tools are not offered
    assert "ask_owner" not in names  # the owner does not ask themselves
    join = next(t for t in view if t["name"] == "join_event")
    assert join["label"] == "참가 신청" and not join["help"].startswith("{")
    commit = next(t for t in view if t["name"] == "commit")
    assert commit["args"]["properties"]["label"]["title"] == "이름표"
    assert notice[0].body == "" and notice[0].title.startswith("[새 공지]")  # the title is not said twice
    r = await asst(human).owner_run(ctx(human), ev, "join_event", {})
    assert r["ok"]
    await settle(eco.host)
    assert human.identity.pub in asst(eco.host).events[ev].applicants
    assert "manual" in asst(human).set_drive(ctx(human), ev, "auto")["error"]  # no LLM: manual only


async def test_p6p4_suggest_the_llm_proposes_and_the_owner_approves_or_rejects(eco):
    a, desk = await desk_peer(eco, "agent")
    ev = await hosted(eco)
    a.llm.push("wait")
    await a.events.watch_once(a.ctx(a.events))
    await settle(a)
    assert asst(a).set_drive(ctx(a), ev, "suggest")["ok"]
    a.llm.push("join_event")
    await asst(a).feed(ctx(a), ev, "참가하라")
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(it.kind == "suggestion" for it in desk.list()):
            break
    s = next(it for it in desk.list() if it.kind == "suggestion")
    assert s.fields["tool"] == "join_event"
    desk.answer(s.id, {"approve": False})
    await settle(a)
    st = asst(a).events[ev]
    assert any("[소유자 거절] join_event" in x for x in st.transcript) and not st.joined
    a.llm.push("join_event")
    await asst(a).feed(ctx(a), ev, "다시 참가하라")
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(it.kind == "suggestion" for it in desk.list()):
            break
    desk.answer(next(it for it in desk.list() if it.kind == "suggestion").id, {"approve": True})
    await settle(a)
    assert st.joined
