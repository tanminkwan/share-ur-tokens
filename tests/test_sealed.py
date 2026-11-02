"""P6-D1 ~ D3: sealed rounds. With the element on, the labels of an assigned subject S (S or S-<number>) are sealed: only
the parties assigned to S register them, a label opens (reveal) only after every assigned party registered it, and no
registration is taken once it opened. This closes the fairness gap of phase 5 (a player revealed before the opponent
registered) for every event that needs simultaneous moves: games, sealed bids, secret votes, blind scoring."""
import json

from arena.crypto import commit_hash
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

POL = {"roles": ["member"]}


async def setup(e, sealed=True):
    ev = await asst(e.host).host_event(ctx(e.host), title="봉인", kind="k", rules=RULES, policy=POL, instruction="기다려라",
                                       elements={"sealed": {}} if sealed else {})
    await settle(e.host)
    for p in (e.a, e.b):
        p.llm.push("join_event")
        await p.events.watch_once(p.ctx(p.events))
    await settle(e.a, e.b, e.host)
    for p in (e.a, e.b):
        e.host.llm.push("contract", role="member", peer=p.pen)
    e.host.llm.push("assign", subjects_json=json.dumps({"s1": [e.a.pen, e.b.pen]}))
    await asst(e.host).feed(ctx(e.host), ev, "계약과 배정")
    await settle(e.host)
    return ev


async def _reg(e, who, ev, label, value="v"):
    lid = e.svc.ledger.chain[0]["hash"]
    salt = "salt-" + label + who.pen
    p = {"author": who.identity.pub, "content_hash": commit_hash(label, value, salt, who.identity.pub), "event_id": ev, "group_id": "public",
         "label": label, "ledger_id": lid}
    r = await e.svc.record("publish", p, {who.identity.pub: who.identity.sign(p)})
    return r, salt


async def _open(e, who, ev, label, salt, commit, value="v"):
    lid = e.svc.ledger.chain[0]["hash"]
    p = {"author": who.identity.pub, "label": label, "value": value, "salt": salt, "commit": commit, "event_id": ev, "group_id": "public",
         "ledger_id": lid}
    return await e.svc.record("reveal", p, {who.identity.pub: who.identity.sign(p)})


def test_p6d1_the_sealed_setting_is_checked():
    from arena.ledger.elements import check_elements
    assert check_elements({"sealed": {}}) is None
    assert check_elements({"sealed": {"kinds": ["x"]}})


async def test_p6d2_a_label_opens_only_after_every_assigned_party_registered(eco):
    ev = await setup(eco)
    a, b = eco.a, eco.b
    ra, sa = await _reg(eco, a, ev, "s1-1")
    assert ra["ok"]
    early = await _open(eco, a, ev, "s1-1", sa, ra["hash"])
    assert not early["ok"] and "sealed" in early["error"]  # b has not registered yet
    rb, sb = await _reg(eco, b, ev, "s1-1")
    assert rb["ok"]
    assert (await _open(eco, a, ev, "s1-1", sa, ra["hash"]))["ok"]
    stranger = eco.peer("c")
    rc, _ = await _reg(eco, stranger, ev, "s1-2")
    assert not rc["ok"] and "assigned" in rc["error"]  # only the assigned parties register a sealed label
    rx, _ = await _reg(eco, a, ev, "free-label")  # labels outside the assigned subjects are not sealed
    assert rx["ok"]


async def test_p6d2_without_the_element_nothing_is_sealed(eco):
    ev = await setup(eco, sealed=False)
    ra, sa = await _reg(eco, eco.a, ev, "s1-1")
    assert (await _open(eco, eco.a, ev, "s1-1", sa, ra["hash"]))["ok"]  # the phase 5 gap: allowed when the event did not ask


async def test_p6d3_the_assistant_state_line_shows_the_sealed_rounds_progress(eco):
    ev = await setup(eco)
    a, b = eco.a, eco.b
    await _reg(eco, a, ev, "s1-1")
    st = asst(a).events[ev]
    await asst(a).progress_entries(ctx(a), st)
    assert "봉인 s1-1: 등록 1/2" in asst(a)._system(ctx(a), st)
    await _reg(eco, b, ev, "s1-1")
    await asst(a).progress_entries(ctx(a), st)
    assert "봉인 s1-1: 등록 2/2, 공개 가능" in asst(a)._system(ctx(a), st)


async def test_p6d2_in_a_sealed_event_a_label_cannot_open_before_it_is_assigned(eco):
    """live with-elements run 1: a player registered and opened m1 before the host assigned m1; once assigned, m1 was
    already open and the other player could not register. In a sealed event only assigned labels open."""
    ev = await asst(eco.host).host_event(ctx(eco.host), title="봉인", kind="k", rules=RULES, policy=POL, instruction="기다려라",
                                       elements={"sealed": {}})
    await settle(eco.host)
    a = eco.a
    ra, sa = await _reg(eco, a, ev, "m1")
    assert ra["ok"]  # registering early is harmless: the value stays sealed
    early = await _open(eco, a, ev, "m1", sa, ra["hash"])
    assert not early["ok"] and "assigned" in early["error"]
