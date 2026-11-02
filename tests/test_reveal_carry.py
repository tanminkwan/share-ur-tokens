"""P5-C32 ~ C33: found by live run 7 (passed, but an honest player lost a match: its agent retyped its own reveal
by hand and pasted the salt of another round). Generic features, no event kind is known here:
- reveal records travel by code: send attaches my reveal records by label, a hand-typed reveal of mine that differs
  from my record is refused, and verified reveals I received are kept
- in a joint-confirmation value, "공개:<handle>:<label>" is replaced by code with that reveal record
- tool arguments wrapped as {"tool": ..., "arguments": {...}} are unwrapped"""
from tests.test_assistant import asst, ctx, eco, joined, settle  # noqa: F401  (eco is a fixture)


async def _commit(p, ev, label, value):
    p.llm.push("commit", label=label, value=value)
    await asst(p).feed(ctx(p), ev, "등록")
    await settle(p)
    return asst(p).events[ev].secrets[label]


async def test_p5c32_send_attaches_my_reveal_records_by_label(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    s = await _commit(a, ev, "r-1", "바위")
    a.llm.push("send", to=b.pen, text="공개", data={}, attach_reveals=["r-1"])
    await asst(a).feed(ctx(a), ev, "공개하라")
    await settle(a, b)
    st_b = asst(b).events[ev]
    assert st_b.reveals[f"{a.identity.pub}|r-1"]["salt"] == s["salt"]  # kept by code, exactly as committed
    last = next(x for x in reversed(st_b.transcript) if "[메시지]" in x)
    assert "[코드 확인] 공개값 1건 모두 원장과 일치" in last and f"공개:{a.pen}:r-1" in last
    # an unknown label is refused before anything is sent
    a.llm.push("send", to=b.pen, text="없는 것", data={}, attach_reveals=["r-9"])
    await asst(a).feed(ctx(a), ev, "공개하라")
    await settle(a, b)
    assert any("r-9" in x and "error" in x for x in asst(a).events[ev].transcript)


async def test_p5c32_a_hand_typed_reveal_of_mine_that_differs_from_my_record_is_refused(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    await _commit(a, ev, "r-1", "바위")
    other = await _commit(a, ev, "r-2", "보")
    real = await asst(a).tools["my_reveal"].run(asst(a), ctx(a), asst(a).events[ev], label="r-1")
    mixed = dict(real, author=a.pen, publish_hash="#" + real["publish_hash"][:10], salt=other["salt"])  # the run-7 mistake
    before = len(asst(b).events[ev].transcript)
    a.llm.push("send", to=b.pen, text="공개", data={"mine": mixed}, attach_reveals=[])
    await asst(a).feed(ctx(a), ev, "공개하라")
    await settle(a, b)
    assert any("attach_reveals" in x for x in asst(a).events[ev].transcript)
    assert len(asst(b).events[ev].transcript) == before  # nothing was delivered


async def test_p5c33_reveal_references_in_a_joint_confirmation_are_filled_by_code(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    await _commit(a, ev, "r-1", "바위")
    sb = await _commit(b, ev, "r-1", "보")
    b.llm.push("send", to=a.pen, text="내 공개", data={}, attach_reveals=["r-1"])
    await asst(b).feed(ctx(b), ev, "공개하라")
    await settle(a, b)
    a.llm.push("propose_attest", kind="pair", subject="r", value={"a": f"공개:{a.pen}:r-1", "b": f"공개:{b.pen}:r-1", "winner": b.pen},
               parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "제안")
    await settle(a, b)
    rid = next(iter(asst(b).events[ev].pending))
    assert asst(b).events[ev].pending[rid]["reveals_ok"] is True
    b.llm.push("cosign", request_id=rid)
    await asst(b).feed(ctx(b), ev, "서명")
    await settle(a, b)
    at = [x for x in eco.svc.ledger.chain if x["type"] == "attest"][-1]["payload"]
    assert at["value"]["a"]["author"] == a.identity.pub and at["value"]["a"]["value"] == "바위"
    assert at["value"]["b"]["salt"] == sb["salt"] and at["value"]["winner"] == b.identity.pub
    # a reference to a reveal nobody has is refused by code
    a.llm.push("propose_attest", kind="pair", subject="r2", value={"a": f"공개:{a.pen}:r-7"}, parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "제안")
    await settle(a, b)
    assert any("공개:" in x and "r-7" in x and "error" in x for x in asst(a).events[ev].transcript)


async def test_p5c33_wrapped_tool_arguments_are_unwrapped(eco):
    ev = await joined(eco)
    a = eco.a
    a.llm.queue.append(("commit", {"tool": "commit", "arguments": {"label": "w-1", "value": "x"}}))  # what run 7's LLM sometimes sent
    await asst(a).feed(ctx(a), ev, "등록")
    await settle(a)
    assert "w-1" in asst(a).events[ev].secrets
