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
