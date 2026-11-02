"""P5-C45 ~ C46: found by live run 14 (the event closed in 1030 s, but):
- the host first sent the ranking to the three players to co-sign, although the policy says the issuer records it
  alone; the ledger would have refused it, yet three signature requests went out
- a garbled handle ("필명-d8다8f") and a mistyped one ("필명-52b8dc") were recorded inside joint confirmations
Generic features: before asking anyone to sign, the code checks a proposal against what the ledger will check (allowed
kinds, issuer-only kinds, roles, assignments); a handle in tool arguments that names nobody is refused."""
import json

from tests.test_assignments import opened
from tests.test_assistant import asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)


async def test_p5c45_a_proposal_the_ledger_would_refuse_is_refused_before_anyone_is_asked(eco):
    ev = await opened(eco)  # policy: pair needs member, summary issuer alone, assigned_kinds pair, attest_kinds pair/summary
    host, a, b = eco.host, eco.a, eco.b
    host.llm.push("assign", subjects_json=json.dumps({"s1": [a.pen, b.pen]}))
    await asst(host).feed(ctx(host), ev, "배정")
    await settle(host)
    sent = []
    orig = host.transport.call

    async def spy(url, msg, *args, **kw):
        sent.append(msg.get("op"))
        return await orig(url, msg, *args, **kw)
    host.transport.call = spy
    cases = [("summary", "final", [a.pen, b.pen, host.pen], "issuer"),       # issuer-only kind with others as parties
             ("chat", "x", [host.pen, a.pen], "kind"),                        # a kind the policy does not allow
             ("pair", "s1", [host.pen, a.pen], "role")]                       # parties without the required role
    for kind, subject, parties, word in cases:
        host.llm.push("propose_attest", kind=kind, subject=subject, value={}, parties=parties)
        await asst(host).feed(ctx(host), ev, "제안")
        await settle(host, a, b)
        last = [x for x in asst(host).events[ev].transcript if "propose_attest 결과" in x][-1]
        assert '"error"' in last and word in last, last
    assert "attest_request" not in sent
    for subject in ("s9", "s1"):  # a subject never assigned; then the assigned subject with the wrong pair (a alone)
        a.llm.push("propose_attest", kind="pair", subject=subject, value={}, parties=[a.pen] if subject == "s1" else [a.pen, b.pen])
        await asst(a).feed(ctx(a), ev, "제안")
        await settle(a)
        assert "assign" in [x for x in asst(a).events[ev].transcript if "propose_attest 결과" in x][-1]


async def test_p5c46_a_handle_that_names_nobody_is_refused(eco):
    ev = await opened(eco)
    host, a, b = eco.host, eco.a, eco.b
    garbled = a.pen[:-3] + "다" + a.pen[-2:]
    typo = b.pen[:-1] + ("0" if b.pen[-1] != "0" else "1")
    for bad in (garbled, typo):
        host.llm.push("propose_attest", kind="summary", subject="final" + bad[-1], value={"winner": bad}, parties=[host.pen])
        await asst(host).feed(ctx(host), ev, "제안")
        await settle(host)
        last = [x for x in asst(host).events[ev].transcript if "propose_attest 결과" in x][-1]
        assert '"error"' in last and "필명" in last, last
    assert not [x for x in eco.svc.ledger.chain if x["type"] == "attest"]
    host.llm.push("propose_attest", kind="summary", subject="final", value={"winner": a.pen}, parties=[host.pen])
    await asst(host).feed(ctx(host), ev, "제안")
    await settle(host)
    at = [x for x in eco.svc.ledger.chain if x["type"] == "attest"]
    assert at and at[0]["payload"]["value"]["winner"] == a.identity.pub
