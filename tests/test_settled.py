"""P5-C43: found by live run 12 (all three matches were on the ledger in about 4 minutes, then the host believed match
m1 still lacked a co-signature and delayed the ranking). A ledger entry is only ever recorded with every signature it
needs, so the code says so instead of leaving the LLM to guess:
- the progress view and the new-entry wake-ups mark joint confirmations and contracts as signed by everyone, settled
- once a joint confirmation is on the ledger, signature requests and proposals I still hold for the same kind and
  subject are cleared by code (they can no longer be signed or recorded)"""
from tests.test_assistant import asst, ctx, eco, joined, settle  # noqa: F401  (eco is a fixture)


async def test_p5c43_settled_entries_are_marked_and_stale_requests_cleared(eco):
    ev = await joined(eco)
    a, b, host = eco.a, eco.b, eco.host
    a.llm.push("propose_attest", kind="pair", subject="s1", value={"x": 1}, parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "제안")
    await settle(a, b)
    st_a, st_b = asst(a).events[ev], asst(b).events[ev]
    rid = next(iter(st_b.pending))
    b.llm.push("cosign", request_id=rid)
    await asst(b).feed(ctx(b), ev, "서명")
    await settle(a, b)
    assert [x for x in eco.svc.ledger.chain if x["type"] == "attest"]
    st_b.pending[rid] = {"payload": {"kind": "pair", "subject": "s1", "event_id": ev}, "from_pub": a.identity.pub}  # a stale copy
    st_a.proposals["old"] = {"payload": {"kind": "pair", "subject": "s1", "event_id": ev}, "sigs": {}}
    st_h = asst(host).events[ev]
    lines = await asst(host).progress_lines(ctx(host), st_h)
    att = next(x for x in lines if " attest " in x)
    con = next(x for x in lines if " contract " in x)
    assert "서명 완료" in att and "서명 완료" in con
    out = await asst(host).tools["event_progress"].run(asst(host), ctx(host), st_h)
    assert "필요한 서명이 모두" in out["note"]
    for p, st in ((a, st_a), (b, st_b)):
        await asst(p).progress_entries(ctx(p), st)
    assert rid not in st_b.pending and "old" not in st_a.proposals


async def test_p5c47_the_host_state_line_names_applicants_not_yet_contracted(eco):
    """run 15: the host thought it had to apply itself, contracted one of three applicants and waited 1500 s"""
    from tests.test_assistant import open_event
    ev = await open_event(eco)
    await settle(eco.host)
    for p in (eco.a, eco.b):
        p.llm.push("join_event")
        await p.events.watch_once(p.ctx(p.events))
    await settle(eco.a, eco.b, eco.host)
    eco.host.llm.push("contract", role="member", peer=eco.a.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "계약")
    await settle(eco.host)
    line = asst(eco.host)._system(ctx(eco.host), asst(eco.host).events[ev])
    assert f"아직 계약하지 않은 신청자: {eco.b.pen}" in line and "나는 개최자다" in line
