"""P5-C28 ~ C31: found by live run 6 (every agent waited for another; nobody could see that the opponent had already
registered, and a content hash was mistaken for a ledger entry). Generic features, no event kind is known here:
- a publication may carry a public label (one per author per event), so others can find "X's registration for m3-1"
- the recorder lists one event's entries in their public view (the event's progress, open to anyone)
- the assistant shows that progress (handles and labels, no 64-hex) and adds it to its idle check
- verify on a content hash says which ledger entry holds it"""
import asyncio
import dataclasses
import json

from arena.crypto import h
from arena.recorder.client import InMemoryRecorderClient
from tests.fakes import ledger_id_of
from tests.test_assistant import asst, ctx, eco, joined, settle  # noqa: F401  (eco is a fixture)


def _publish(p, ev, content, label=None):
    payload = {"author": p.identity.pub, "content_hash": h(content.encode()), "event_id": ev, "group_id": "public",
               "ledger_id": ledger_id_of(p)}
    if label is not None:
        payload["label"] = label
    return payload, {p.identity.pub: p.identity.sign(payload)}


async def test_p5c28_a_publication_carries_a_public_label_once_per_author_per_event(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    a.llm.push("commit", label="m1-1", value="바위")
    await asst(a).feed(ctx(a), ev, "등록")
    await settle(a)
    e = [x for x in eco.svc.ledger.chain if x["type"] == "publish"][-1]
    assert e["payload"]["label"] == "m1-1" and eco.svc.verify(e["hash"])["label"] == "m1-1"
    # the same author cannot register a second value under the same label in the same event (no changing your mind)
    assert "label" in (await eco.svc.record("publish", *_publish(a, ev, "다른 값", "m1-1")))["error"]
    # another author may use the same label; a label too long or not a string is refused
    assert (await eco.svc.record("publish", *_publish(b, ev, "b의 값", "m1-1")))["ok"]
    assert "label" in (await eco.svc.record("publish", *_publish(b, ev, "긴 값", "x" * (eco.s.ledger_label_max + 1))))["error"]
    assert "label" in (await eco.svc.record("publish", *_publish(b, ev, "숫자", 7)))["error"]
    # a publication without a label is still fine
    assert (await eco.svc.record("publish", *_publish(b, ev, "이름표 없음")))["ok"]


async def test_p5c29_the_recorder_lists_one_events_entries_in_public_view(eco):
    ev = await joined(eco)
    a = eco.a
    a.llm.push("commit", label="m1-1", value="바위")
    await asst(a).feed(ctx(a), ev, "등록")
    await settle(a)
    r = await InMemoryRecorderClient(eco.svc).event_entries(ev)
    assert r["ok"] and [x["type"] for x in r["entries"]] == ["event", "contract", "contract", "publish"]
    pub = r["entries"][-1]
    assert pub["label"] == "m1-1" and pub["author"] == a.identity.pub and pub["hash"] and "seq" in pub
    assert "value" not in json.dumps(pub)  # only the public view: the committed value never leaves the peer
    assert (await InMemoryRecorderClient(eco.svc).event_entries("ev-none"))["entries"] == []
    eco.svc.settings = dataclasses.replace(eco.svc.settings, recorder_public_event_view=False)
    assert not (await InMemoryRecorderClient(eco.svc).event_entries(ev))["ok"]


async def test_p5c29_event_entries_over_http(settings, tmp_path):
    import httpx
    from arena.crypto import Identity
    from arena.ledger import MemoryStore
    from arena.recorder.api import build_recorder_app
    from arena.recorder.client import RecorderClient
    from arena.recorder.service import RecorderService
    svc = RecorderService.build(settings, Identity.generate(), MemoryStore(), readers=[])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_recorder_app(svc)), base_url="http://rec") as hc:
        r = await RecorderClient("http://rec", settings, http_client=hc).event_entries("ev-x")
    assert r == {"ok": True, "event_id": "ev-x", "entries": []}


async def test_p5c30_the_assistant_sees_the_events_progress_with_handles_and_labels(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    a.llm.push("commit", label="m1-1", value="바위")
    await asst(a).feed(ctx(a), ev, "등록")
    await settle(a)
    st_b = asst(b).events[ev]
    out = await asst(b).tools["event_progress"].run(asst(b), ctx(b), st_b)
    text = json.dumps(out, ensure_ascii=False)
    assert a.pen in text and "m1-1" in text and "member" in text
    shown = asst(b).shorten(ctx(b), st_b, text)
    assert a.identity.pub not in shown  # roster members become handles, never 64-hex
    # the idle check carries the same progress, made by code, so a waiting agent can see that others have moved
    asst(b).s = dataclasses.replace(asst(b).s, assistant_idle_sec=0.0)
    st_b.last_input_at = 0
    await asst(b).idle_check(ctx(b))
    await settle(b)
    check = next(x for x in st_b.transcript if "[점검]" in x)
    assert "[진행 현황]" in check and a.pen in check and "m1-1" in check and a.identity.pub not in check


async def test_p5c31_verify_on_a_content_hash_names_the_entry_that_holds_it(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    a.llm.push("commit", label="m1-1", value="바위")
    await asst(a).feed(ctx(a), ev, "등록")
    await settle(a)
    s = asst(a).events[ev].secrets["m1-1"]
    out = await asst(b).tools["verify"].run(asst(b), ctx(b), asst(b).events[ev], hash=s["commit"])
    assert out["exists"] is False and out["content_of"]["hash"] == s["publish_hash"] and out["content_of"]["label"] == "m1-1"
    assert "내용 해시" in out["note"]


async def test_p5c31_wait_decisions_are_logged(eco):
    ev = await joined(eco)
    lines = []
    eco.log.emit = lambda kind, who, text: lines.append((kind, who, text))
    await asst(eco.a).feed(ctx(eco.a), ev, "아무 일 없음")
    await settle(eco.a)
    assert any(k == "assistant" and "기다림" in t for k, _, t in lines)
