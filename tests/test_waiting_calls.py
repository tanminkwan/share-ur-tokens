"""The basic assistant's calls that come back pending (the other peer's owner is still deciding): kept per event,
looked at again by the peer's scheduler, and finished by code when the answer arrives (WaitingCalls). No LLM."""
import pytest

from arena.peer.assistant.waiting_calls import FINISHERS, TIMER, WaitingCalls, finisher
from tests.test_assistant import asst, ctx, eco, open_event, settle  # noqa: F401  (eco is a fixture)


async def _joined(eco):
    ev = await open_event(eco)
    await eco.a.events.watch_once(eco.a.ctx(eco.a.events))
    eco.a.llm.push("join_event")
    await eco.a.events.watch_once(eco.a.ctx(eco.a.events))
    await settle(eco.a, eco.host)
    return ev


async def test_a_contract_the_other_owner_is_still_deciding_is_finished_when_the_answer_arrives(eco):
    ev = await _joined(eco)
    asked, looks = [], []
    real_call_peer = eco.host.call_peer

    async def call_peer(pub, msg, timeout=None, group=None, event=None, url=None):
        if msg.get("op") != "engage":
            return await real_call_peer(pub, msg, timeout, group=group, event=event, url=url)
        asked.append((msg, {"group_id": group, "event_id": event}))
        return {"ok": False, "pending": True, "task_id": "task-1", "url": "mem://a", "error": "still waiting: waiting for the owner (a person) to answer"}

    async def check_task(url, task_id, wait=None, pub=None):
        looks.append(task_id)
        if len(looks) == 1:
            return {"ok": False, "pending": True, "task_id": task_id, "url": url, "error": "still waiting: waiting for the owner (a person) to answer"}
        msg, meta = asked[0]
        return await eco.t.call("mem://a", msg, meta=meta)  # the person said yes: the contractor's real answer
    eco.host.call_peer, eco.host.check_task = call_peer, check_task
    eco.host.llm.push("contract", role="member", peer=eco.a.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "계속")
    await settle(eco.host)
    st = asst(eco.host).events[ev]
    assert not [x for x in eco.svc.ledger.chain if x["type"] == "contract"]  # not refused, not recorded: waiting
    assert list(st.waiting_calls) == ["task-1"] and st.waiting_calls["task-1"]["kind"] == "contract"
    assert [t["kind"] for t in ctx(eco.host).timers(ev)].count(TIMER) == 1  # the scheduler will look again
    assert "기다리는 답: contract(task-1)" in asst(eco.host).prompt.state_line(ctx(eco.host), st)
    timer = {"kind": TIMER, "event_id": ev, "at": eco.host.clock(), "data": {}}
    await asst(eco.host).on_timer(ctx(eco.host), timer)  # first look: still deciding
    assert list(st.waiting_calls) == ["task-1"] and not [x for x in eco.svc.ledger.chain if x["type"] == "contract"]
    await asst(eco.host).on_timer(ctx(eco.host), timer)  # the answer arrived: code records the contract
    await settle(eco.host)
    c = [x for x in eco.svc.ledger.chain if x["type"] == "contract"]
    assert len(c) == 1 and c[0]["payload"]["contractor"] == eco.a.identity.pub and not st.waiting_calls
    assert ["member", eco.a.identity.pub] in st.contracts
    assert any("[기다리던 답]" in line for line in st.transcript)


async def test_check_pending_now_and_a_refusal_ends_the_wait(eco):
    from arena.peer.assistant.tools import check_pending
    ev = await _joined(eco)
    st = asst(eco.host).events[ev]
    w = asst(eco.host).waiting
    out = w.hold(ctx(eco.host), st, {"task_id": "t-no", "url": "mem://a", "error": "still waiting"}, "contract",
                 {"role": "member", "peer_pub": eco.a.identity.pub, "peer_url": "mem://a", "body": {}, "private": None})
    assert out["pending"] and "거절이 아니다" in out["note"]

    async def refused(url, task_id, wait=None, pub=None):
        return {"ok": False, "error": "the owner said no"}
    eco.host.check_task = refused
    r = await check_pending(asst(eco.host), ctx(eco.host), st)
    assert r["still_waiting"] == 0 and r["results"][0]["error"] == "the owner said no"
    assert (await check_pending(asst(eco.host), ctx(eco.host), st, task_id="other"))["results"] == []


def test_a_finisher_is_registered_once():
    assert "contract" in FINISHERS
    with pytest.raises(ValueError, match="twice"):
        finisher("contract")(lambda *a: None)
    assert WaitingCalls.line(type("S", (), {"waiting_calls": {}})()) == ""
