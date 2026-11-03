"""P6-C1 ~ C4: the built-in evaluation element. The host hands submissions to a contracted reviewer (a `share` of kind evaluation,
co-signed), the reviewer's EvaluationDesk gets verdicts from an app with the EvaluationProvider capability (or the basic
assistant), signs them in code, and the host records them. The ledger checks who may hand over, who may judge, and how
many reviewers per item. What to adopt from the verdicts is not decided here (the event's own judgement)."""
import time

from arena.crypto import h
from arena.ledger import split_payload
from arena.peer.plugin import BaseApp
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

POL = {"roles": ["member", "reviewer"], "conflict_roles": ["reviewer"], "verdict_roles": {"review": "reviewer"}}
ELEMENTS = {"intake": {"deadline": time.time() + 3600, "max_per_author": 1, "receiver": "issuer"},
            "evaluation": {"evaluator_role": "reviewer", "verdict": "review", "per_item": 1}}


class Scorer(BaseApp):
    """a reviewer's app with the review capability (test double): score = length of the text, capped"""
    name, version, app_id = "scorer", "1.0", "1f2e3d4c-5b6a-4978-8a6b-5c4d3e2f1a0b"

    async def evaluate(self, ctx, items, request):
        return [{"content_hash": i["content_hash"], "score": float(min(10, len(i["content"]))), "comment": f"{len(i['content'])}자"} for i in items]


async def contest(e, reviewer_apps=()):
    rv = e.peer("rv", apps=list(reviewer_apps))
    await rv.advertise()
    ev = await asst(e.host).host_event(ctx(e.host), title="공모", kind="공모", rules=RULES, policy=POL, instruction="기다려라", elements=ELEMENTS)
    await settle(e.host)
    for p in (e.a, e.b, rv):
        await p.events.watch_once(p.ctx(p.events))
    await settle(e.a, e.b, rv, e.host)
    for p, text in ((e.a, "짝꿍 제도"), (e.b, "첫 주 점심 모임")):
        p.llm.push("submit", text=text)
        await asst(p).feed(ctx(p), ev, "제출")
        await settle(p, e.host)
    rv.llm.push("join_event")
    await asst(rv).feed(ctx(rv), ev, "참가")
    await settle(rv, e.host)
    e.host.llm.push("contract", role="reviewer", peer=rv.pen)
    await asst(e.host).feed(ctx(e.host), ev, "심사자와 계약")
    await settle(e.host)
    return ev, rv


def test_p6c1_the_review_setting_is_checked():
    from arena.ledger.elements import check_elements
    assert check_elements({"evaluation": {"evaluator_role": "r", "verdict": "review", "per_item": 1}}) is None
    for bad in ({"evaluator_role": "", "verdict": "review", "per_item": 1}, {"evaluator_role": "r", "verdict": "review", "per_item": 0}):
        assert check_elements({"evaluation": bad})


async def test_p6c2_c3_c4_items_go_to_the_contracted_reviewer_and_signed_verdicts_are_recorded(eco):
    ev, rv = await contest(eco, [Scorer()])
    eco.host.llm.push("request_evaluation", evaluator=rv.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "심사를 맡겨라")
    await settle(eco.host)
    chain = eco.svc.ledger.chain
    handed = [e for e in chain if e["type"] == "share" and e["payload"].get("purpose") == "evaluation"]
    verdicts = [e for e in chain if e["type"] == "feedback"]
    assert len(handed) == 2 and all(set(x["sigs"]) == {eco.host.identity.pub, rv.identity.pub} for x in handed)
    assert len(verdicts) == 2 and all(x["payload"]["evaluator"] == rv.identity.pub and x["payload"]["verdict"] == "review" for x in verdicts)
    assert sorted(x["payload"]["score"] for x in verdicts) == [5.0, 9.0]
    v = eco.svc.verify(verdicts[0]["hash"])
    assert v["evaluator"] == rv.identity.pub and v["score"] in (5.0, 9.0)  # the public view of a verdict
    eco.host.llm.push("verdicts")
    await asst(eco.host).feed(ctx(eco.host), ev, "판정을 보라")
    await settle(eco.host)
    line = [x for x in asst(eco.host).events[ev].transcript if "verdicts 결과" in x][-1]
    assert "9.0" in line and "5자" in line  # verdicts are shown; what to do with them is the event's own judgement


async def test_p6c2_the_ledger_checks_who_hands_over_who_judges_and_how_many(eco):
    ev, rv = await contest(eco, [Scorer()])
    lid = eco.svc.ledger.chain[0]["hash"]
    ch = h("짝꿍 제도".encode())

    async def hand(provider, consumer, nonce):
        full = {"provider": provider.identity.pub, "consumer": consumer.identity.pub, "content_hash": ch, "purpose": "evaluation", "nonce": nonce,
                "event_id": ev, "group_id": "public", "ledger_id": lid}
        p, private = split_payload("share", full)
        return await eco.svc.record("share", p, {provider.identity.pub: provider.identity.sign(p), consumer.identity.pub: consumer.identity.sign(p)}, private)
    assert "issuer" in (await hand(eco.a, rv, "n1"))["error"]          # only the host hands items over
    assert "reviewer" in (await hand(eco.host, eco.b, "n2"))["error"]  # only to the contracted reviewer
    assert (await hand(eco.host, rv, "n3"))["ok"]
    other = eco.peer("rv2")
    assert "reviewer" in (await hand(eco.host, other, "n4"))["error"]
    fb = {"evaluator": eco.b.identity.pub, "content_hash": ch, "verdict": "review", "score": 1.0, "event_id": ev, "group_id": "public", "ledger_id": lid}
    assert (await eco.svc.record("feedback", fb, {eco.b.identity.pub: eco.b.identity.sign(fb)}))["error"]  # not a reviewer


async def test_p6c4_without_a_review_app_the_basic_assistant_judges(eco):
    ev, rv = await contest(eco)

    class Judging:
        async def ask_json(self, **kw):
            if kw["schema"].get("required", [None])[0] == "verdicts":
                ids = [line.split(":")[0].strip("- ") for line in kw["messages"][-1]["content"].splitlines() if line.startswith("- ")]
                return {"verdicts": [{"id": i, "score": 7, "comment": "규칙에 맞다"} for i in ids]}
            return await rv_llm.ask_json(**kw)
    rv_llm, rv.llm = rv.llm, Judging()
    eco.host.llm.push("request_evaluation", evaluator=rv.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "심사를 맡겨라")
    await settle(eco.host)
    scores = [e["payload"]["score"] for e in eco.svc.ledger.chain if e["type"] == "feedback"]
    assert scores == [7.0, 7.0]
