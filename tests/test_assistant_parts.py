"""SOLID re-check (2026-11-03): the basic assistant's parts, each on its own, including the branches the flows rarely hit
(refusals and failures). No real LLM."""
import json
import time

import pytest

from arena.crypto import Identity, commit_hash
from arena.peer.assistant.drives import Drives
from arena.peer.assistant.messenger import Messenger
from arena.peer.assistant.state import EventState
from arena.peer.assistant.tools import S, Tool, _obj
from arena.peer.plugin import MessageHead
from tests.test_assistant import asst, ctx, eco, joined, open_event, settle  # noqa: F401  (eco is a fixture)


def state(**kw):
    base = dict(event_id="ev-x", role="participant", title="t", rules="r", rules_hash="h", group_id="public", recorder_url="mem://rec/api",
                recorder_pub="p", issuer_pub="i" * 64, issuer_url="mem://host")
    return EventState(**{**base, **kw})


# ---------------- Toolbox: every check code does before a tool runs ----------------
async def test_toolbox_refuses_before_running(eco):
    a = eco.a
    box, c = asst(a).toolbox, ctx(a)
    st = state()
    assert (await box.run(asst(a), c, st, "nope", {}))["error"].startswith("없는 도구")
    assert "개최자만" in (await box.run(asst(a), c, st, "contract", {"role": "x", "peer": "y"}))["error"]
    host_st = state(role="host")
    assert "참가자만" in (await box.run(asst(a), c, host_st, "join_event", {}))["error"]
    assert "닫힌 이벤트" in (await box.run(asst(a), c, state(closed=True), "send", {"to": "x", "text": "t"}))["error"]
    assert "없음" in (await box.run(asst(a), c, st, "send", {}))["error"]  # a required argument missing
    assert "JSON이 아님" in (await box.run(asst(a), c, st, "send", {"to": "x", "text": "t", "data_json": "{broken"}))["error"]
    garbled = c.settings.pen_name_prefix + "z" * c.settings.pen_name_len
    assert "아무도 가리키지 않는 필명" in (await box.run(asst(a), c, st, "contact", {"peer": garbled}))["error"]
    with pytest.raises(ValueError):
        box.add(box.tools["note"])  # a tool name is registered once


async def test_toolbox_reports_a_failing_tool_instead_of_raising(eco):
    a = eco.a

    async def boom(A, ctx, st, text):
        raise RuntimeError("broke")

    async def picky(A, ctx, st, text):
        return {"ok": True}
    asst(a).add_tool(Tool("boom", "{text}", _obj(text=S), boom))
    asst(a).add_tool(Tool("picky", "{text}", {"type": "object", "required": [], "properties": {}}, picky))
    st = state()
    assert (await asst(a).toolbox.run(asst(a), ctx(a), st, "boom", {"text": "x"}))["error"] == "RuntimeError: broke"
    assert "인자가 맞지 않음" in (await asst(a).toolbox.run(asst(a), ctx(a), st, "picky", {"text": "x", "extra": 1}))["error"]
    view = {t["name"]: t for t in asst(a).toolbox.owner_view(st)}
    assert "boom" in view and view["boom"]["label"] == "boom" and view["send"]["args"]["properties"]["to"]["title"] == "받는 이(필명)"


# ---------------- Drives ----------------
def test_drives_refuse_and_title_body(settings):
    d = Drives(settings)

    class C:  # a context with an LLM, on a human peer
        llm, operator, owner = object(), "human", object()
    assert d.allowed(C) == ("manual", "suggest") and d.initial(C) == "manual"
    assert "가운데 하나" in d.refuse(C, "turbo") and "사람 peer" in d.refuse(C, "auto") and d.refuse(C, "suggest") is None
    C.operator = "agent"
    assert d.allowed(C) == Drives.ALL and d.notifier(C) is None
    long = "가" * (settings.desk_title_chars + 5) + "\n둘째 줄"
    title, body = d.title_body(long)
    assert title.endswith("…") and body == long  # cut: the whole text goes in the body
    assert d.title_body("한 줄\n둘\n셋") == ("한 줄", "둘\n셋")


async def test_drives_approve_when_there_is_nobody_to_ask(settings):
    class C:
        owner = object()
    assert await Drives(settings).approved(C, state(), "send", {}, "생각", lambda t: t)


# ---------------- Messenger ----------------
def test_messenger_checks_signature_time_and_head(settings):
    me, other = Identity.generate(), Identity.generate()

    C = type("C", (), {"pub": me.pub, "settings": settings, "clock": staticmethod(time.time), "sign": staticmethod(me.sign)})
    body = Messenger.sign_body(C, {"op": "event_message", "event_id": "ev-x", "group_id": "public"})
    assert Messenger.check(C, body) == me.pub
    assert Messenger.check(C, dict(body, text="바뀜")) is None  # tampered
    assert Messenger.check(C, dict(body, sig=other.sign({k: v for k, v in body.items() if k != "sig"}))) is None
    old = Messenger.sign_body(type("Old", (), {"pub": me.pub, "clock": staticmethod(lambda: time.time() - 10 * settings.sig_window_sec),
                                               "sign": staticmethod(me.sign)}), {"op": "x"})
    assert Messenger.check(C, old) is None  # outside the time window
    st = state()
    assert Messenger.head_ok(st, body, MessageHead())
    assert not Messenger.head_ok(st, dict(body, group_id="other"), MessageHead())
    assert not Messenger.head_ok(st, body, MessageHead(group_id="other"))


# ---------------- Directory, Handles ----------------
async def test_directory_and_handles_when_the_broker_fails(eco):
    a = eco.a

    class Down:
        async def list_profiles(self, identity=None):
            raise ConnectionError("down")
    a.brokers["public"] = Down()
    A, c = asst(a), ctx(a)
    assert await A.directory.profiles(c) == [] and not await A.offers_role(c, "x" * 64, "member") and await A.offering_op(c, "x") == []
    st = state(peers={"b" * 64: "mem://b"})
    assert await A.resolve_peer(c, st, "mem://b") == ("b" * 64, "mem://b")
    assert await A.resolve_peer(c, st, "c" * 64, need_url=False) == ("c" * 64, None)
    assert await A.resolve_peer(c, st, a.pen) == (a.identity.pub, a.config.url)
    assert await A.resolve_peer(c, st, "d" * 64) == ("d" * 64, None)  # not known anywhere: no address


# ---------------- LedgerView ----------------
async def test_ledger_view_when_the_recorder_fails_and_who_an_entry_concerns(eco):
    a = eco.a
    A, c = asst(a), ctx(a)

    class Broken:
        async def event_entries(self, ev):
            raise ConnectionError("down")
    a.recorder_factory = lambda u: Broken()
    assert await A.progress_entries(c, state()) == []
    lv, me = A.ledger, a.identity.pub
    st = state(assignments={"m1": [me, "b" * 64]})
    assert lv.concerns_me(c, st, {"type": "publish", "author": "b" * 64})            # my match-mate
    assert not lv.concerns_me(c, st, {"type": "publish", "author": "z" * 64})        # someone else's match
    assert lv.concerns_me(c, st, {"type": "attest", "parties": [me]})                # names me
    assert lv.concerns_me(c, state(), {"type": "publish", "author": "z" * 64})       # no assignments: everything
    assert not lv.concerns_me(c, state(role="host"), {"type": "publish", "author": "z" * 64})
    assert lv.concerns_me(c, state(role="host"), {"type": "attest", "parties": ["z" * 64]})


# ---------------- Reveals ----------------
async def test_reveals_find_incomplete_and_mismatched_records(eco):
    ev = await joined(eco)
    a = eco.a
    A, c, st = asst(a), ctx(a), asst(eco.a).events[ev]
    assert A.reveal_records({"x": [{"label": "m1", "value": "가위", "publish_hash": "h"}]}) == [{"label": "m1", "value": "가위", "publish_hash": "h"}]
    bad = await A.verify_reveals(c, st, {"label": "m1", "value": "가위", "publish_hash": "h"})
    assert not bad[0][0] and "불완전" in bad[0][1]
    lid = eco.svc.ledger.chain[0]["hash"]
    p = {"author": a.identity.pub, "content_hash": commit_hash("m9", "보", "salt", a.identity.pub), "event_id": ev, "group_id": "public",
         "label": "m9", "ledger_id": lid}
    r = await eco.svc.record("publish", p, {a.identity.pub: a.identity.sign(p)})
    wrong = await A.verify_reveals(c, st, {"author": a.identity.pub, "label": "m9", "value": "가위", "salt": "salt", "publish_hash": r["hash"]})
    assert not wrong[0][0] and "맞지 않음" in wrong[0][1]
    elsewhere = await A.verify_reveals(c, st, {"author": eco.b.identity.pub, "label": "m9", "value": "보", "salt": "salt", "publish_hash": r["hash"]})
    assert not elsewhere[0][0] and "다른 사람" in elsewhere[0][1]
    filled, missing = await A.fill_reveals(c, st, {"v": f"공개:{eco.b.pen}:none"})
    assert missing == [f"공개:{eco.b.pen}:none"] and filled == {"v": f"공개:{eco.b.pen}:none"}
    _, missing = await A.fill_reveals(c, st, {"label": "zz", "value": "x", "publish_hash": "#abcdef0123"})
    assert missing and "원장 공개가 없다" in missing[0]
    assert A.reveals.summary(c, st, {}, []) == ""
