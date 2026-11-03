"""Every refusal of the basic assistant's tools and the element desks, called directly (the LLM never needs to make the
mistake for the code's answer to be tested). No real LLM."""
from arena.crypto import h
from arena.peer.assistant import tools as T
from arena.peer.elements import evaluation as EV
from arena.peer.elements import intake as IN
from arena.peer.service import ServiceApp
from tests.test_assistant import asst, ctx, eco, joined, open_event, settle  # noqa: F401  (eco is a fixture)
from tests.test_service_peer import spec


async def test_participation_and_contract_refusals(eco):
    ev = await joined(eco)
    host, a, b = eco.host, eco.a, eco.b
    H, sh = asst(host), asst(host).events[ev]
    assert "개최자는 참가 신청하지 않는다" in (await T.join_event(H, ctx(host), sh))["error"]
    garbled = "z" * 64
    assert "찾지 못했다" in (await T.contract(H, ctx(host), sh, "member", garbled))["error"]
    c = eco.peer("c")
    c.config.offers = ["member"]  # offers the role in its profile, but has not taken part: nobody decides for it
    await c.advertise()
    r = await T.contract(H, ctx(host), sh, "member", c.identity.pub)
    assert not r["ok"] and "no app decides" in r["error"]
    sa = asst(a).events[ev]
    assert "찾지 못했다" in (await T.send(asst(a), ctx(a), sa, garbled, "안녕"))["error"]
    assert "사람 연락처를 공개하지 않았다" in (await T.contact(asst(a), ctx(a), sa, host.identity.pub))["error"]
    assert "찾지 못했다" in (await T.call_service(asst(a), ctx(a), sa, garbled, "add"))["error"]


async def test_a_service_receipt_that_does_not_match_is_refused(eco):
    ev = await joined(eco)
    a = eco.a
    svc = eco.peer("svc", apps=[ServiceApp(eco.s, spec())])
    await svc.advertise()
    real = svc.handle

    async def forged(msg, *rest):
        out = await real(msg, *rest)
        if isinstance(out, dict) and out.get("receipt"):
            out = dict(out, result={"sum": 999})  # the answer was changed after the service signed it
        return out
    eco.t.register(svc.config.url, forged)
    r = await T.call_service(asst(a), ctx(a), asst(a).events[ev], svc.identity.pub, "add", {"a": 1, "b": 2})
    assert not r["ok"] and "영수증이 맞지 않는다" in r["error"]


async def test_registration_and_opening_refusals(eco):
    ev = await joined(eco)
    a = eco.a
    A, sa = asst(a), asst(a).events[ev]
    assert (await T.commit(A, ctx(a), sa, "m1", "가위"))["ok"]
    again = await T.commit(A, ctx(a), sa, "m1", "바위")
    assert "이미 먼저 등록했다" in again["error"]
    too_long = await T.commit(A, ctx(a), sa, "x" * (eco.s.ledger_label_max + 1), "가위")
    assert not too_long["ok"] and "label" in too_long["error"]
    assert (await T.reveal(A, ctx(a), sa, "m1"))["ok"]
    assert "이미 원장에 공개했다" in (await T.reveal(A, ctx(a), sa, "m1"))["note"]
    no = await T.check_reveal(A, ctx(a), sa, "0" * 64, eco.b.identity.pub, "m1", "가위", "s")
    assert no["match"] is False


async def test_joint_confirmation_and_assignment_refusals(eco):
    ev = await joined(eco)
    host, a, b = eco.host, eco.a, eco.b
    A, sa = asst(a), asst(a).events[ev]
    assert "찾지 못했다" in (await T.propose_attest(A, ctx(a), sa, "pair", "s1", {}, ["z" * 64]))["error"]
    assert "나도 당사자" in (await T.propose_attest(A, ctx(a), sa, "pair", "s1", {}, [b.identity.pub]))["error"]
    assert "없다" in (await T.cosign(A, ctx(a), sa, "nope"))["error"]
    assert "없다" in (await T.decline(A, ctx(a), sa, "nope", "왜"))["error"]
    H, sh = asst(host), asst(host).events[ev]
    assert "JSON 객체" in (await T.assign(H, ctx(host), sh, ["m1"]))["error"]
    assert "찾지 못했다" in (await T.assign(H, ctx(host), sh, {"m1": ["z" * 64]}))["error"]


async def test_element_desk_refusals(eco):
    from tests.test_evaluation import contest
    from tests.test_intake import opened
    ev = await opened(eco, receiver="judge")  # the receiver is a role nobody holds yet
    a = eco.a
    assert "받을 사람이 아직 없다" in (await IN.submit(asst(a), ctx(a), asst(a).events[ev], "아이디어"))["error"]
    desk = eco.host.app_by_id(IN.IntakeDesk.app_id)
    r = await desk._submit(eco.host.ctx(desk), {"event_id": ev, "content": "x", "share": {"consumer": eco.host.identity.pub,
                                                "purpose": "submission", "event_id": ev, "content_hash": h(b"x"),
                                                "provider": a.identity.pub, "group_id": "public"}, "sig": "00"}, None)
    assert not r["ok"] and "서명" in r["error"]
    ev2, rv = await contest(eco, [])
    H, sh = asst(eco.host), asst(eco.host).events[ev2]
    assert "역할로 계약한 peer가 아니다" in (await EV.request_evaluation(H, ctx(eco.host), sh, eco.b.identity.pub))["error"]
    edesk = rv.app_by_id(EV.EvaluationDesk.app_id)
    bad = await edesk._request(rv.ctx(edesk), {"event_id": ev2, "recorder_url": "mem://rec/api", "items": []}, None)
    assert not bad["ok"] and "항목" in bad["error"]
