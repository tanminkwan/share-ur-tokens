"""P5-C35 ~ C36: found by live run 8 (two matches finished, the third stalled: a player said "here is my reveal" but
attached nothing, believed it had sent it, and both sides waited for each other). Generic features:
- a reveal can be recorded on the ledger: the ledger checks it against the author's own registration (same event, same
  label, the sealed hash matches) and keeps one reveal per registration; its public view shows the revealed value
- the assistant reveals by label (the code fills value and salt), sees others' reveals in the event's progress, and
  "공개:<handle>:<label>" is filled from a ledger reveal without any message
- the assistant's state line says, from code, which of my labels are revealed on the ledger and to whom I sent reveals"""
from arena.crypto import commit_hash
from tests.fakes import ledger_id_of
from tests.test_assistant import asst, ctx, eco, joined, settle  # noqa: F401  (eco is a fixture)
from tests.test_reveal_carry import _commit


def _reveal(p, ev, label, value, salt, commit):
    payload = {"author": p.identity.pub, "label": label, "value": value, "salt": salt, "commit": commit, "event_id": ev, "group_id": "public",
               "ledger_id": ledger_id_of(p)}
    return payload, {p.identity.pub: p.identity.sign(payload)}


async def test_p5c35_the_ledger_checks_a_reveal_against_its_own_registration(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    s = await _commit(a, ev, "r-1", "바위")
    assert s["commit"] == commit_hash("r-1", "바위", s["salt"], a.identity.pub)
    rec = eco.svc.record
    assert "match" in (await rec("reveal", *_reveal(a, ev, "r-1", "보", s["salt"], s["publish_hash"])))["error"]       # wrong value
    assert "label" in (await rec("reveal", *_reveal(a, ev, "r-2", "바위", s["salt"], s["publish_hash"])))["error"]     # another label
    assert "author" in (await rec("reveal", *_reveal(b, ev, "r-1", "바위", s["salt"], s["publish_hash"])))["error"]    # not the author
    ok = await rec("reveal", *_reveal(a, ev, "r-1", "바위", s["salt"], s["publish_hash"]))
    assert ok["ok"]
    assert "already" in (await rec("reveal", *_reveal(a, ev, "r-1", "바위", s["salt"], s["publish_hash"])))["error"]  # once
    v = eco.svc.verify(ok["hash"])
    assert v["type"] == "reveal" and v["value"] == "바위" and v["label"] == "r-1" and v["commit"] == s["publish_hash"]


async def test_p5c36_the_assistant_reveals_by_label_and_uses_ledger_reveals(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    await _commit(a, ev, "r-1", "바위")
    await _commit(b, ev, "r-1", "보")
    a.llm.push("reveal", label="r-1")
    await asst(a).feed(ctx(a), ev, "공개하라")
    await settle(a)
    assert any(x["type"] == "reveal" and x["payload"]["author"] == a.identity.pub for x in eco.svc.ledger.chain)
    assert "원장에 공개한 내 라벨: r-1" in asst(a)._system(ctx(a), asst(a).events[ev])
    # b sees a's reveal in the progress, with no message at all
    st_b = asst(b).events[ev]
    lines = "\n".join(await asst(b).progress_lines(ctx(b), st_b))
    assert "reveal" in lines and a.pen in lines and "바위" in lines
    # b reveals too, then proposes with references only; the code fills both from the ledger
    b.llm.push("reveal", label="r-1")
    b.llm.push("propose_attest", kind="pair", subject="r", value={"a": f"공개:{a.pen}:r-1", "b": f"공개:{b.pen}:r-1"}, parties=[b.pen, a.pen])
    await asst(b).feed(ctx(b), ev, "공개하고 제안하라")
    await settle(a, b)
    rid = next(iter(asst(a).events[ev].pending))
    assert asst(a).events[ev].pending[rid]["reveals_ok"] is True
    filled = asst(a).events[ev].pending[rid]["payload"]["value"]
    assert filled["a"]["value"] == "바위" and filled["b"]["value"] == "보" and filled["a"]["author"] == a.identity.pub


async def test_p5c36_the_state_line_says_to_whom_i_sent_reveals(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    await _commit(a, ev, "r-1", "바위")
    a.llm.push("send", to=b.pen, text="공개", data={}, attach_reveals=["r-1"])
    await asst(a).feed(ctx(a), ev, "보내라")
    await settle(a, b)
    assert f"내가 보낸 공개값: r-1→{b.pen}" in asst(a)._system(ctx(a), asst(a).events[ev])


async def test_p5c44_a_hand_written_partial_reveal_record_is_completed_from_the_ledger_or_refused(eco):
    """run 13: a joint confirmation held reveal records written by hand without the salt; the code did not see them as
    reveal records (a field was missing), so nothing checked them"""
    ev = await joined(eco)
    a, b = eco.a, eco.b
    sa = await _commit(a, ev, "r-1", "바위")
    sb = await _commit(b, ev, "r-1", "보")
    for p in (a, b):
        p.llm.push("reveal", label="r-1")
        await asst(p).feed(ctx(p), ev, "공개하라")
        await settle(p)
    partial = {"author": a.pen, "label": "r-1", "value": "바위", "publish_hash": "#" + sa["publish_hash"][:10]}
    b_partial = {"author": b.pen, "label": "r-1", "value": "보", "publish_hash": "#" + sb["publish_hash"][:10]}
    a.llm.push("propose_attest", kind="pair", subject="r", value={"a": partial, "b": b_partial}, parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "제안")
    await settle(a, b)
    rid = next(iter(asst(b).events[ev].pending))
    filled = asst(b).events[ev].pending[rid]["payload"]["value"]
    assert filled["a"]["salt"] == sa["salt"] and filled["b"]["salt"] == sb["salt"]  # completed by code from the ledger reveals
    # a partial record whose registration was never revealed on the ledger is refused
    await _commit(a, ev, "r-2", "가위")
    s2 = asst(a).events[ev].secrets["r-2"]
    a.llm.push("propose_attest", kind="pair", subject="r2", value={"a": {"author": a.pen, "label": "r-2", "value": "가위", "publish_hash": "#" + s2["publish_hash"][:10]}},
               parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "제안")
    await settle(a, b)
    assert any("r-2" in x and "error" in x for x in asst(a).events[ev].transcript)
    # and one that reaches me anyway is flagged as incomplete
    checks = await asst(b).verify_reveals(ctx(b), asst(b).events[ev], {"a": {"author": a.identity.pub, "label": "r-2", "value": "가위", "publish_hash": s2["publish_hash"]}})
    assert checks and not checks[0][0] and "불완전" in checks[0][1]
