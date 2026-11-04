"""Endorsement (user 2026-11-04: "결재는 특별한 것이 아니야. event 게시자의 의도로 하는 거야. event의 효력이나 명성을 위한
장치", "2가지 선택 옵션"). The publisher declares the event alone, then may ask others to co-sign it: appended to the ledger
("ledger") or as a token with the notice ("signature"). The endorser's owner decides; a decline changes nothing for the
event; existing entries are never rewritten. In-memory world, scripted LLM only."""
import json

from arena.ledger.endorse import make_token, token_error
from arena.peer.endorsements import ask_endorsement, tokens_of
from tests.fakes import FakeOwner
from tests.test_assistant import asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)
from tests.test_desk import hosted


async def _ask(e, ev, endorser, how="ledger"):
    st = asst(e.host).events[ev]
    return await ask_endorsement(ctx(e.host), event_id=ev, event_hash=st.event_hash, recorder_url=st.recorder_url, group_id=st.group_id,
                                 endorser=endorser.identity.pub, endorser_url=endorser.config.url, how=how, request={"title": st.title})


async def test_on_the_ledger_an_endorsement_is_appended_and_counted(eco):
    ev = await hosted(eco)
    for p in (eco.a, eco.b):
        await p.events.watch_once(p.ctx(p.events))
    await settle(eco.a, eco.b)
    chain = eco.svc.ledger.chain
    declared = next(x for x in chain if x["type"] == "event")
    before = json.dumps(declared)
    r = await _ask(eco, ev, eco.a)
    assert r["ok"] and r["how"] == "ledger" and r["hash"]
    entry = next(x for x in chain if x["type"] == "endorse")
    assert set(entry["sigs"]) == {eco.host.identity.pub, eco.a.identity.pub} and entry["payload"]["event_hash"] == declared["hash"]
    assert json.dumps(declared) == before  # the event entry, and the hash chain before it, unchanged
    assert any("공동 서명" in q for q, _ in eco.a.owner.asked)  # the endorser's owner decided
    assert eco.svc.track(eco.a.identity.pub)["track"]["endorsements"] == 1 and eco.svc.track(eco.host.identity.pub)["track"]["endorsed"] == 1
    assert any(x["type"] == "endorse" for x in eco.svc.event_entries(ev)["entries"])  # anyone sees it with the event
    again = await _ask(eco, ev, eco.a)
    assert "already endorsed" in again["error"]


async def test_off_the_ledger_a_token_travels_with_the_notice(eco):
    ev = await hosted(eco)
    for p in (eco.a, eco.b):
        await p.events.watch_once(p.ctx(p.events))
    await settle(eco.a, eco.b)
    n = len(eco.svc.ledger.chain)
    r = await _ask(eco, ev, eco.a, how="signature")
    assert r["ok"] and token_error(r["token"]) is None and len(eco.svc.ledger.chain) == n  # the ledger did not grow
    done = await asst(eco.host).keep_endorsement(ctx(eco.host), asst(eco.host).events[ev], dict(r, endorser=eco.a.identity.pub))
    assert done["notice_reposted"]
    await eco.b.events.watch_once(eco.b.ctx(eco.b.events))  # a participant reads the notice again
    await settle(eco.b)
    st = asst(eco.b).events[ev]
    assert [e["endorser"] for e in st.endorsements] == [eco.a.identity.pub]
    assert any(x["kind"] == "endorse" for x in st.timeline) and "공동 서명" in asst(eco.b).prompt.state_line(ctx(eco.b), st)
    # tokens that do not check out for this event are left out
    notice = dict(asst(eco.host).events[ev].notice)
    forged = make_token(dict(r["token"]["body"], endorser=eco.b.identity.pub), r["token"]["sigs"])
    other = make_token(dict(r["token"]["body"], event_id="elsewhere"), r["token"]["sigs"])
    assert [t["body"]["endorser"] for t in tokens_of(dict(notice, endorsements=[forged, other, r["token"], "junk"]))] == [eco.a.identity.pub]
    assert "not an endorsement token" in token_error({"format": "x"})


async def test_a_decline_or_a_forged_event_ends_with_no_endorsement_and_the_event_goes_on(eco):
    ev = await hosted(eco)
    eco.b.owner = FakeOwner(yes=False, why="우리 이름은 걸지 않는다")
    for p in (eco.a, eco.b):
        await p.events.watch_once(p.ctx(p.events))
    await settle(eco.a, eco.b)
    r = await _ask(eco, ev, eco.b)
    assert r == {"ok": False, "error": "우리 이름은 걸지 않는다"}
    assert not any(x["type"] == "endorse" for x in eco.svc.ledger.chain) and ev in asst(eco.host).events  # the event goes on
    st = asst(eco.host).events[ev]
    fake = await ask_endorsement(ctx(eco.host), event_id=ev, event_hash="0" * 64, recorder_url=st.recorder_url, group_id=st.group_id,
                                 endorser=eco.a.identity.pub, endorser_url=eco.a.config.url)
    assert "no such event" in fake["error"]  # the endorser checks the ledger before signing
    assert "how must be" in (await _ask(eco, ev, eco.a, how="fax"))["error"]


async def test_the_basic_assistant_asks_with_its_tool_and_finishes_a_pending_answer(eco):
    from arena.peer.assistant.waiting_calls import TIMER
    ev = await hosted(eco)
    for p in (eco.a, eco.b):
        await p.events.watch_once(p.ctx(p.events))
    await settle(eco.a, eco.b)
    eco.host.llm.push("ask_endorsement", peer=eco.a.pen, how="ledger")
    await asst(eco.host).feed(ctx(eco.host), ev, "a에게 공동 서명을 청하라")
    await settle(eco.host)
    st = asst(eco.host).events[ev]
    assert [e["endorser"] for e in st.endorsements] == [eco.a.identity.pub] and any(x["type"] == "endorse" for x in eco.svc.ledger.chain)
    assert "공동 서명" in asst(eco.host).prompt.state_line(ctx(eco.host), st)
    # the endorser's owner is still deciding: pending, then finished by code when the answer arrives
    asked = []
    real = eco.host.call_peer

    async def call_peer(pub, msg, timeout=None, group=None, event=None, url=None):
        if msg.get("op") != "endorse":
            return await real(pub, msg, timeout, group=group, event=event, url=url)
        asked.append((msg, {"group_id": group, "event_id": event}))
        return {"ok": False, "pending": True, "task_id": "t-e", "url": "mem://b", "error": "still waiting: waiting for the owner"}

    async def check_task(url, task_id, wait=None):
        msg, meta = asked[0]
        return await eco.t.call("mem://b", msg, meta=meta)
    eco.host.call_peer, eco.host.check_task = call_peer, check_task
    eco.host.llm.push("ask_endorsement", peer=eco.b.pen, how="ledger")
    await asst(eco.host).feed(ctx(eco.host), ev, "b에게도 청하라")
    await settle(eco.host)
    assert list(st.waiting_calls) == ["t-e"] and st.waiting_calls["t-e"]["kind"] == "endorse"
    await asst(eco.host).on_timer(ctx(eco.host), {"kind": TIMER, "event_id": ev, "at": eco.host.clock(), "data": {}})
    await settle(eco.host)
    assert sorted(e["endorser"] for e in st.endorsements) == sorted([eco.a.identity.pub, eco.b.identity.pub]) and not st.waiting_calls
    assert len([x for x in eco.svc.ledger.chain if x["type"] == "endorse"]) == 2
