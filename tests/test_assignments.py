"""P5-C40 ~ C41: found by live run 10 (every reveal matched, but the bookkeeping of several matches went wrong: a player
played match m2 against someone not in m2, the other side co-signed it, and another recorded a joint confirmation of
kind "propose_attest"). Generic features, no event kind is known here:
- assignments: the event issuer records on the ledger which parties take which subject; for kinds the policy lists in
  assigned_kinds, the ledger accepts a joint confirmation only from exactly the assigned parties
- the ledger accepts only the joint-confirmation kinds the policy lists in attest_kinds, when it lists any (opt-in)
- the assistant assigns with handles (tool assign), and its state line shows the assignments and mine, from the ledger"""
import json

from tests.test_assistant import POLICY, RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

PO = dict(POLICY, assigned_kinds=["pair"], attest_kinds=["pair", "summary"])


async def opened(e):
    ev = await asst(e.host).host_event(ctx(e.host), title="배정", kind="예시", rules=RULES, policy=PO, instruction="계약하라")
    await settle(e.host)
    for p in (e.a, e.b):
        p.llm.push("join_event")
        await p.events.watch_once(p.ctx(p.events))
    await settle(e.a, e.b, e.host)
    for p in (e.a, e.b):
        e.host.llm.push("contract", role="member", peer=p.pen)
    await asst(e.host).feed(ctx(e.host), ev, "계약")
    await settle(e.host)
    return ev


def _attest(e, ev, kind, subject, signers):
    p = {"event_id": ev, "kind": kind, "subject": subject, "value": {}, "parties": [x.identity.pub for x in signers], "nonce": subject + kind,
         "group_id": "public"}
    return p, {x.identity.pub: x.identity.sign(p) for x in signers}


async def test_p5c40_joint_confirmations_of_assigned_kinds_need_exactly_the_assigned_parties(eco):
    ev = await opened(eco)
    host, a, b = eco.host, eco.a, eco.b
    stranger = eco.peer("x")
    host.llm.push("assign", subjects_json=json.dumps({"s1": [a.pen, b.pen]}))
    await asst(host).feed(ctx(host), ev, "배정하라")
    await settle(host)
    asg = [x for x in eco.svc.ledger.chain if x["type"] == "assign"]
    assert asg and asg[0]["payload"]["subjects"] == {"s1": [a.identity.pub, b.identity.pub]}
    rec = eco.svc.record
    assert "assigned" in (await rec("attest", *_attest(eco, ev, "pair", "s2", [a, b])))["error"]          # subject never assigned
    assert (await rec("attest", *_attest(eco, ev, "pair", "s1", [b, a])))["ok"]                            # the assigned pair, any order
    # only the issuer assigns, a subject once, and only to contractors of the event
    p = {"event_id": ev, "issuer": a.identity.pub, "subjects": {"s3": [a.identity.pub]}, "group_id": "public"}
    assert "issuer" in (await rec("assign", p, {a.identity.pub: a.identity.sign(p)}))["error"]
    for subjects, word in (({"s1": [a.identity.pub, b.identity.pub]}, "already"), ({"s4": [stranger.identity.pub]}, "contract")):
        p = {"event_id": ev, "issuer": host.identity.pub, "subjects": subjects, "group_id": "public"}
        assert word in (await rec("assign", p, {host.identity.pub: host.identity.sign(p)}))["error"]


async def test_p5c40_only_the_policys_kinds_are_accepted(eco):
    ev = await opened(eco)
    assert "kind" in (await eco.svc.record("attest", *_attest(eco, ev, "propose_attest", "m2", [eco.a, eco.b])))["error"]


async def test_p5c41_the_state_line_shows_assignments_and_mine(eco):
    ev = await opened(eco)
    host, a, b = eco.host, eco.a, eco.b
    host.llm.push("assign", subjects_json=json.dumps({"s1": [a.pen, b.pen], "s2": [a.pen]}))
    await asst(host).feed(ctx(host), ev, "배정하라")
    await settle(host)
    st_b = asst(b).events[ev]
    await asst(b).progress_entries(ctx(b), st_b)
    line = asst(b)._system(ctx(b), st_b)
    assert f"s1={a.pen}·{b.pen}" in line and "내 배정: s1" in line and "s2" in line.split("내 배정:")[0]
    assert "내 배정: s1 /" in line or line.split("내 배정: ")[1].startswith("s1")


async def test_p5c42_ledger_wake_ups_only_for_what_concerns_me(eco):
    """run 11: 142 of 232 turns were waits, many on ledger entries of matches the agent was not in"""
    import dataclasses
    from tests.test_reveal_carry import _commit
    ev = await opened(eco)
    host, a, b = eco.host, eco.a, eco.b
    host.llm.push("assign", subjects_json=json.dumps({"s1": [a.pen], "s2": [b.pen]}))
    await asst(host).feed(ctx(host), ev, "배정하라")
    await settle(host)
    for p in (host, a, b):
        asst(p).s = dataclasses.replace(asst(p).s, assistant_ledger_watch_sec=0.0)
        await asst(p).ledger_check(ctx(p))
    n_a, n_h = len(asst(a).events[ev].transcript), len(asst(host).events[ev].transcript)
    await _commit(b, ev, "s2-1", "x")  # b's own subject: neither a nor the host needs to wake up
    for p in (a, host):
        await asst(p).ledger_check(ctx(p))
    await settle(a, host)
    assert not [x for x in asst(a).events[ev].transcript[n_a:] if "[원장 새 기록]" in x]
    assert not [x for x in asst(host).events[ev].transcript[n_h:] if "[원장 새 기록]" in x]
    # a joint confirmation wakes the host (results are what the host collects)
    p = {"event_id": ev, "kind": "pair", "subject": "s2", "value": {}, "parties": [b.identity.pub], "nonce": "n", "group_id": "public"}
    assert (await eco.svc.record("attest", p, {b.identity.pub: b.identity.sign(p)}))["ok"]
    await asst(host).ledger_check(ctx(host))
    await settle(host)
    assert [x for x in asst(host).events[ev].transcript[n_h:] if "[원장 새 기록]" in x]
