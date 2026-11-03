"""P6-B1 ~ B4: the built-in submission element (intake). An event switches it on with its setting (deadline, submissions
per author, who receives, who may submit). The ledger checks recipient, deadline, the per-author limit and conflicting
roles on `share` entries of kind submission; the receiving peer's IntakeDesk checks content, signatures and audience,
co-signs and records the share, and keeps the submission (after a restart too). The assistant gets submit/submissions."""
import dataclasses
import time

import pytest

from arena.crypto import h
from arena.ledger import split_payload
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

POL = {"roles": ["member", "review"], "conflict_roles": ["review"]}


async def opened(e, **intake):
    cfg = {"deadline": time.time() + 3600, "max_per_author": 1, "receiver": "issuer", **intake}
    ev = await asst(e.host).host_event(ctx(e.host), title="공모", kind="공모", rules=RULES, policy=POL, instruction="기다려라",
                                       elements={"intake": cfg})
    await settle(e.host)
    for p in (e.a, e.b):
        await p.events.watch_once(p.ctx(p.events))
    await settle(e.a, e.b, e.host)
    return ev


async def _submit(p, ev, text):
    p.llm.push("submit", text=text)
    await asst(p).feed(ctx(p), ev, "제출하라")
    await settle(p)
    return [x for x in asst(p).events[ev].transcript if "submit 결과" in x][-1]


def test_p6b1_the_intake_setting_is_checked():
    from arena.ledger.elements import check_elements
    assert check_elements({"intake": {"deadline": time.time(), "max_per_author": 1, "receiver": "issuer"}}) is None
    for bad in ({"max_per_author": 0, "receiver": "issuer"}, {"max_per_author": 1, "receiver": ""},
                {"max_per_author": 1, "receiver": "issuer", "audience": "x"}, {"max_per_author": 1, "receiver": "issuer", "deadline": "soon"}):
        assert check_elements({"intake": bad})


async def test_p6b2_b3_b4_submit_is_checked_co_signed_recorded_and_kept(eco):
    ev = await opened(eco)
    assert '"ok": true' in await _submit(eco.a, ev, "신입 적응을 돕는 짝꿍 제도")
    shares = [e for e in eco.svc.ledger.chain if e["type"] == "share"]
    assert len(shares) == 1 and set(shares[0]["sigs"]) == {eco.a.identity.pub, eco.host.identity.pub}
    assert shares[0]["payload"]["purpose"] == "submission" and shares[0]["payload"]["event_id"] == ev
    lst = await ctx(eco.host).submissions(ev)
    assert [(x["author"], x["content"]) for x in lst] == [(eco.a.identity.pub, "신입 적응을 돕는 짝꿍 제도")]
    second = await _submit(eco.a, ev, "두 번째 아이디어")
    assert '"ok": false' in second and "at most" in second  # the ledger's per-author limit, passed back by the desk
    eco.host.llm.push("submissions")
    await asst(eco.host).feed(ctx(eco.host), ev, "목록")
    await settle(eco.host)
    assert any("짝꿍 제도" in x and eco.a.pen in x for x in asst(eco.host).events[ev].transcript)
    # kept across a restart of the receiving peer's desk
    from arena.peer.elements.intake import IntakeDesk
    again = IntakeDesk(eco.s)
    again.load(eco.host.ctx(eco.host.app_by_id(IntakeDesk.app_id)))
    assert [x["content"] for x in again.list(ev)] == ["신입 적응을 돕는 짝꿍 제도"]


async def test_p6b2_the_ledger_checks_recipient_deadline_limit_and_conflicting_roles(eco):
    ev = await opened(eco, max_per_author=2)
    a, b = eco.a, eco.b
    lid = eco.svc.ledger.chain[0]["hash"]

    async def publish(provider, text):
        pub = {"author": provider.identity.pub, "content_hash": h(text.encode()), "event_id": ev, "group_id": "public", "ledger_id": lid}
        return await eco.svc.record("publish", pub, {provider.identity.pub: provider.identity.sign(pub)})

    async def share(provider, consumer, text, purpose="submission"):
        ch = h(text.encode())
        await publish(provider, text)
        full = {"provider": provider.identity.pub, "consumer": consumer.identity.pub, "content_hash": ch, "purpose": purpose, "nonce": text,
                "event_id": ev, "group_id": "public", "ledger_id": lid}
        p, private = split_payload("share", full)
        return await eco.svc.record("share", p, {provider.identity.pub: provider.identity.sign(p), consumer.identity.pub: consumer.identity.sign(p)}, private)
    assert "receiver" in (await share(a, b, "x1"))["error"]
    assert (await share(a, eco.host, "x2"))["ok"] and (await share(a, eco.host, "x3"))["ok"]
    assert "at most" in (await share(a, eco.host, "x4"))["error"]
    assert (await share(a, b, "x5", purpose="delivery"))["ok"]  # only submissions are governed by the element
    # a contracted reviewer may not submit (its content was registered before the contract)
    assert (await publish(b, "x6"))["ok"]
    eco.host.llm.push("contract", role="review", peer=b.pen)
    b.llm.push("join_event")
    await asst(b).feed(ctx(b), ev, "참가하라")
    await settle(b, eco.host)
    await asst(eco.host).feed(ctx(eco.host), ev, "계약")
    await settle(eco.host)
    assert "conflicting" in (await share(b, eco.host, "x6"))["error"]
    # after the deadline
    eco.svc.ledger.clock = lambda: time.time() + 7200
    assert "deadline" in (await share(a, eco.host, "x7"))["error"]


async def test_p6b2_the_desk_refuses_wrong_content_and_people_outside_the_audience(eco):
    ev = await opened(eco, audience=["소속:다른회사"])
    assert "응모 대상" in await _submit(eco.a, ev, "아이디어")
    from arena.peer.elements.intake import IntakeDesk
    desk_ctx = eco.host.ctx(eco.host.app_by_id(IntakeDesk.app_id))
    r = await eco.host.handle({"op": "intake.submit", "event_id": ev, "content": "다른 글", "share": {"content_hash": h(b"x")}, "sig": ""})
    assert not r["ok"] and desk_ctx is not None
