"""P5-C37 ~ C39: found by live run 9 (ledger reveals worked, but the run was slow and stalled):
- a peer named first by a 64-hex key it did not know yet was shown as a hash ref (#9c7cb9..), later as a handle
  (필명-9c7cb9): two names for one person, so agents misread who had done what
- agents saw others' ledger moves only at idle checks with growing gaps
- moves came in mixed words ("rock", "바위", "scissors")
Generic features: unknown keys in an input are looked up (event ledger, broker) before the LLM sees them; the
assistant watches its event's ledger and is woken by new entries of others; an event may declare the allowed revealed
values (policy reveal_values), checked by code at commit and by the ledger at reveal."""
import dataclasses

from arena.crypto import commit_hash
from tests.test_assistant import POLICY, RULES, asst, ctx, eco, joined, settle  # noqa: F401  (eco is a fixture)
from tests.test_reveal_carry import _commit


async def test_p5c37_an_unknown_key_in_an_input_is_shown_as_a_handle(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    st = asst(a).events[ev]
    assert b.identity.pub not in asst(a)._known_pubs(ctx(a), st)
    await asst(a).feed(ctx(a), ev, f"대진표: m1 a={a.identity.pub} b={b.identity.pub}")
    await settle(a)
    line = next(x for x in st.transcript if "대진표" in x)
    assert b.pen in line and "#" + b.identity.pub[:10] not in line


async def test_p5c38_allowed_revealed_values_are_checked_by_code_and_ledger(eco):
    pol = dict(POLICY, reveal_values=["가위", "바위", "보"])
    ev = await asst(eco.host).host_event(ctx(eco.host), title="값 목록", kind="예시", rules=RULES, policy=pol, instruction="계약하라")
    await settle(eco.host)
    a = eco.a
    a.llm.push("join_event")
    await a.events.watch_once(a.ctx(a.events))
    await settle(a, eco.host)
    eco.host.llm.push("contract", role="member", peer=a.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "계약")
    await settle(eco.host)
    st = asst(a).events[ev]
    assert st.policy.get("reveal_values") == ["가위", "바위", "보"]
    assert "가위, 바위, 보" in asst(a)._system(ctx(a), st)
    out = await asst(a).tools["commit"].run(asst(a), ctx(a), st, label="v-1", value="rock")
    assert "error" in out and "바위" in out["error"] and "v-1" not in st.secrets
    assert (await asst(a).tools["commit"].run(asst(a), ctx(a), st, label="v-1", value="바위"))["ok"]
    # the ledger refuses a reveal outside the list even when the sealed hash matches
    salt = "s"
    pay = {"author": a.identity.pub, "content_hash": commit_hash("v-2", "rock", salt, a.identity.pub), "event_id": ev, "group_id": "public", "label": "v-2"}
    pub = await eco.svc.record("publish", pay, {a.identity.pub: a.identity.sign(pay)})
    rev = {"author": a.identity.pub, "label": "v-2", "value": "rock", "salt": salt, "commit": pub["hash"], "event_id": ev, "group_id": "public"}
    assert "allowed" in (await eco.svc.record("reveal", rev, {a.identity.pub: a.identity.sign(rev)}))["error"]


async def test_p5c39_the_assistant_is_woken_by_new_ledger_entries_of_others(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    for p in (a, b):
        asst(p).s = dataclasses.replace(asst(p).s, assistant_ledger_watch_sec=0.0)
        await asst(p).ledger_check(ctx(p))  # first look: remember where the ledger is, feed nothing
    st_a, st_b = asst(a).events[ev], asst(b).events[ev]
    n_b = len(st_b.transcript)
    await _commit(a, ev, "w-1", "바위")
    await asst(b).ledger_check(ctx(b))
    await settle(b)
    fed = [x for x in st_b.transcript[n_b:] if "[원장 새 기록]" in x]
    assert fed and a.pen in fed[0] and "w-1" in fed[0]
    n_a = len(st_a.transcript)
    await asst(a).ledger_check(ctx(a))
    await settle(a)
    assert not [x for x in st_a.transcript[n_a:] if "[원장 새 기록]" in x]  # my own registration does not wake me
    await asst(b).ledger_check(ctx(b))
    await settle(b)
    assert len([x for x in st_b.transcript if "[원장 새 기록]" in x]) == 1  # each entry once
