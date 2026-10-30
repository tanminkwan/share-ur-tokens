"""R2 + P2-A: generic ledger rules, event declarations with policy and approvals, audit, contribution, persistence."""
import json

import pytest

from arena.crypto import Identity, canon, h, verify
from arena.ledger import JsonlStore, Ledger, LedgerCorrupt, MemoryStore, audit_chain, contribution

# an example policy; the platform only compares these strings, it does not know what they mean
POLICY = {"roles": ["keeper", "judge"], "conflict_roles": ["keeper", "judge"],
          "verdict_roles": {"score": "judge", "pick": "issuer"}, "hidden_roles": ["judge"]}


class Cast:
    """author, event issuer, a contracted judge, a keeper, an approver, a stranger; builders for signed entries"""

    def __init__(self):
        self.author, self.issuer, self.judge, self.keeper, self.approver, self.other = (Identity.generate() for _ in range(6))
        self.ev = "ev-1"

    def event(self, ev=None, policy=None, approvers=(), issuer=None, sign_by=None):
        i = issuer or self.issuer
        p = {"event_id": ev or self.ev, "issuer": i.pub, "kind": "test", "policy": POLICY if policy is None else policy,
             "approvers": [a.pub for a in approvers]}
        sigs = {i.pub: i.sign(p)}
        for a in (approvers if sign_by is None else sign_by):
            sigs[a.pub] = a.sign(p)
        return "event", p, sigs

    def publish(self, content="doc A", author=None, ev="__default__"):
        a = author or self.author
        p = {"author": a.pub, "content_hash": h(canon({"c": content}))}
        if ev is not None:
            p["event_id"] = self.ev if ev == "__default__" else ev
        return "publish", p, {a.pub: a.sign(p)}

    def share(self, content="doc A", provider=None, consumer=None, nonce="n1"):
        pr, co = provider or self.author, consumer or self.issuer
        p = {"provider": pr.pub, "consumer": co.pub, "content_hash": h(canon({"c": content})), "terms": "t", "nonce": nonce}
        return "share", p, {pr.pub: pr.sign(p), co.pub: co.sign(p)}

    def contract(self, role="judge", contractor=None, nonce="c1", ev=None, issuer=None):
        c, i = contractor or self.judge, issuer or self.issuer
        p = {"event_id": ev or self.ev, "role": role, "issuer": i.pub, "contractor": c.pub, "nonce": nonce}
        return "contract", p, {i.pub: i.sign(p), c.pub: c.sign(p)}

    def feedback(self, verdict="score", evaluator=None, content="doc A", ev="__default__", **extra):
        e = evaluator or self.judge
        p = {"evaluator": e.pub, "content_hash": h(canon({"c": content})), "verdict": verdict, **extra}
        if ev is not None:
            p["event_id"] = self.ev if ev == "__default__" else ev
        return "feedback", p, {e.pub: e.sign(p)}


@pytest.fixture
def cast():
    return Cast()


@pytest.fixture
def ledger(settings, clock):
    return Ledger(Identity.generate(), MemoryStore(), settings, clock=clock)


def ok(ledger, entry):
    e, err = ledger.propose(*entry)
    assert err is None, err
    return e


def err(ledger, entry):
    return ledger.propose(*entry)[1]


# ---------------- generic rules (R2) ----------------
def test_r2_1_unknown_type_rejected(ledger):
    assert err(ledger, ("bogus", {}, {})) == "unknown type"


def test_r2_2_missing_or_wrong_signature_rejected(ledger, cast):
    kind, p, sigs = cast.publish(ev=None)
    assert err(ledger, (kind, p, {})).startswith("missing/invalid signature")
    assert err(ledger, (kind, p, {cast.author.pub: cast.other.sign(p)})).startswith("missing/invalid signature")
    ok(ledger, cast.publish(ev=None))
    kind, p, sigs = cast.share()
    del sigs[cast.issuer.pub]
    assert err(ledger, (kind, p, sigs)).startswith("missing/invalid signature")


def test_r2_3_chain_links_and_recorder_seal(ledger, cast):
    e0 = ok(ledger, cast.publish(ev=None))
    e1 = ok(ledger, cast.share())
    assert (e0["seq"], e1["seq"]) == (0, 1) and e0["prev"] == "0" * 64 and e1["prev"] == e0["hash"]
    assert e1["hash"] == h(canon({k: e1[k] for k in ("type", "payload", "sigs", "prev", "ts")}))
    assert e1["seal"]["pub"] == ledger.identity.pub and verify(ledger.identity.pub, e1["hash"], e1["seal"]["sig"])
    assert ledger.head() == e1["hash"] and ledger.find(e0["hash"]) is e0 and ledger.find("nope") is None


def test_r2_4_timestamp_cannot_go_backwards(ledger, cast, clock):
    ok(ledger, cast.publish(ev=None))
    clock.tick(-5)
    assert err(ledger, cast.share()) == "timestamp goes backwards"


def test_r2_5_first_publisher_wins(ledger, cast):
    ok(ledger, cast.publish(ev=None))
    assert err(ledger, cast.publish(author=cast.other, ev=None)) == "content already published (first publisher wins)"


def test_r2_7_share_needs_publish_and_nonce_is_single_use(ledger, cast):
    assert err(ledger, cast.share()) == "unknown content"
    ok(ledger, cast.publish(ev=None))
    ok(ledger, cast.share(nonce="n1"))
    assert err(ledger, cast.share(nonce="n1", consumer=cast.other)) == "replay (nonce already used)"
    ok(ledger, cast.event())
    ok(ledger, cast.contract(nonce="c1"))
    assert err(ledger, cast.contract(nonce="c1", contractor=cast.other)) == "replay (nonce already used)"


def test_r2_9_generic_feedback_rules_without_event(ledger, cast):
    ok(ledger, cast.publish(ev=None))
    assert err(ledger, cast.feedback("like", evaluator=cast.other, ev=None)) == "evaluator never received this content"
    ok(ledger, cast.share(consumer=cast.other))
    ok(ledger, cast.feedback("like", evaluator=cast.other, ev=None))
    assert err(ledger, cast.feedback("like", evaluator=cast.other, ev=None)).startswith("duplicate feedback")
    ok(ledger, cast.feedback("dislike", evaluator=cast.other, ev=None))  # another verdict is a different feedback


# ---------------- events, policy, approvals (P2-A) ----------------
def test_pa2_event_declared_once_with_valid_policy(ledger, cast):
    ok(ledger, cast.event())
    assert err(ledger, cast.event()) == "event already declared"
    assert err(ledger, cast.event(ev="ev-2", policy={"roles": "keeper"})) == "bad policy"
    assert err(ledger, cast.event(ev="ev-3", policy={"verdict_roles": {"x": 1}})) == "bad policy"
    assert err(ledger, cast.event(ev="ev-4", policy={"surprise": []})) == "bad policy"
    ok(ledger, cast.event(ev="ev-5", policy={}))  # every key is optional


def test_pa9_event_needs_every_approver_signature(ledger, cast):
    second = Identity.generate()
    assert err(ledger, cast.event(approvers=[cast.approver, second], sign_by=[cast.approver])).startswith("missing/invalid signature")
    assert err(ledger, cast.event(approvers=[cast.issuer])) == "approver must differ from the issuer"
    e = ok(ledger, cast.event(approvers=[cast.approver, second]))
    assert set(e["sigs"]) == {cast.issuer.pub, cast.approver.pub, second.pub}


def test_pa4_contract_needs_declared_event_same_issuer_allowed_role(ledger, cast):
    assert err(ledger, cast.contract()) == "unknown event"
    ok(ledger, cast.event())
    assert err(ledger, cast.contract(role="cook")) == "role not allowed by the event policy"
    assert err(ledger, cast.contract(issuer=cast.other)) == "only the event issuer can contract roles"
    ok(ledger, cast.contract(role="judge"))
    ok(ledger, cast.event(ev="open", policy={}))
    ok(ledger, cast.contract(role="anything", ev="open", nonce="c2"))  # no roles list -> any role


def test_pa3_conflict_roles_cannot_publish_into_the_event(ledger, cast):
    ok(ledger, cast.event())
    ok(ledger, cast.contract(role="keeper", contractor=cast.keeper))
    assert err(ledger, cast.publish(author=cast.keeper)) == "a contractor in a conflicting role cannot publish into this event"
    ok(ledger, cast.publish(author=cast.keeper, ev=None))  # outside the event is fine
    ok(ledger, cast.event(ev="ev-2", policy={"roles": ["keeper"]}))
    ok(ledger, cast.contract(role="keeper", contractor=cast.author, ev="ev-2", nonce="c2"))
    ok(ledger, cast.publish(content="doc B", author=cast.author, ev="ev-2"))  # no conflict_roles there


def test_pa3_verdict_roles_restrict_who_may_judge(ledger, cast):
    ok(ledger, cast.event())
    ok(ledger, cast.publish())
    ok(ledger, cast.share(consumer=cast.judge, nonce="s1"))
    ok(ledger, cast.share(consumer=cast.other, nonce="s2"))
    ok(ledger, cast.share(consumer=cast.issuer, nonce="s3"))
    assert err(ledger, cast.feedback("score")) == "verdict 'score' requires the 'judge' role in this event"
    ok(ledger, cast.contract(role="judge"))
    ok(ledger, cast.feedback("score", score=7.0))
    assert err(ledger, cast.feedback("pick", evaluator=cast.other)) == "verdict 'pick' requires the event issuer"
    ok(ledger, cast.feedback("pick", evaluator=cast.issuer))
    ok(ledger, cast.feedback("comment", evaluator=cast.other))  # verdicts the policy does not mention are free


def test_pa5_unknown_event_is_rejected(ledger, cast):
    assert err(ledger, cast.publish(ev="ghost")) == "unknown event"
    ok(ledger, cast.publish(ev=None))
    ok(ledger, cast.share(consumer=cast.other))
    assert err(ledger, cast.feedback("x", evaluator=cast.other, ev="ghost")) == "unknown event"


def test_pa6_contribution_is_generic(ledger, cast):
    ok(ledger, cast.event(approvers=[cast.approver]))
    ok(ledger, cast.publish())
    ok(ledger, cast.share(consumer=cast.issuer, nonce="a"))
    ok(ledger, cast.share(consumer=cast.issuer, nonce="b"))
    ok(ledger, cast.share(consumer=cast.author, nonce="c"))  # self-share not counted
    ok(ledger, cast.share(consumer=cast.judge, nonce="d"))
    ok(ledger, cast.contract(role="judge"))
    ok(ledger, cast.feedback("score", score=8.0))
    ok(ledger, cast.feedback("pick", evaluator=cast.issuer))
    c = contribution(ledger.chain)
    assert c[cast.author.pub] == {"published": 1, "received_by": 2, "verdicts_received": {"score": 1, "pick": 1},
                                  "verdicts_given": {}, "roles": {}, "events": 0, "approvals": 0}
    assert c[cast.judge.pub]["roles"] == {"judge": 1} and c[cast.judge.pub]["verdicts_given"] == {"score": 1}
    assert c[cast.issuer.pub]["events"] == 1 and c[cast.issuer.pub]["verdicts_given"] == {"pick": 1}
    assert c[cast.approver.pub]["approvals"] == 1


# ---------------- audit, persistence ----------------
def test_r2_10_audit_finds_first_tampered_entry(ledger, cast):
    ok(ledger, cast.publish(ev=None))
    ok(ledger, cast.share())
    ok(ledger, cast.publish(content="doc B", ev=None))
    assert ledger.audit() == "ok" and audit_chain(ledger.chain) == "ok"
    t = json.loads(json.dumps(ledger.chain))
    t[1]["payload"]["terms"] = "changed"
    assert audit_chain(t) == "TAMPERED at seq 1 (hash chain)"
    t = json.loads(json.dumps(ledger.chain))
    t[2]["sigs"][cast.author.pub] = "00" * 64
    t[2]["hash"] = h(canon({k: t[2][k] for k in ("type", "payload", "sigs", "prev", "ts")}))
    assert audit_chain(t) == "TAMPERED at seq 2 (signature)"
    t = json.loads(json.dumps(ledger.chain))
    t[0]["seal"]["sig"] = "00" * 64
    assert audit_chain(t) == "TAMPERED at seq 0 (recorder seal)"


def test_pa9_audit_rechecks_approver_signatures(ledger, cast):
    ok(ledger, cast.event(approvers=[cast.approver]))
    t = json.loads(json.dumps(ledger.chain))
    t[0]["sigs"][cast.approver.pub] = "00" * 64
    t[0]["hash"] = h(canon({k: t[0][k] for k in ("type", "payload", "sigs", "prev", "ts")}))
    assert audit_chain(t) == "TAMPERED at seq 0 (signature)"


def test_r2_12_jsonl_store_persists_and_reloads(tmp_path, settings, clock, cast):
    path = tmp_path / "deep" / "ledger.jsonl"
    me = Identity.generate()
    a = Ledger(me, JsonlStore(str(path)), settings, clock=clock)
    ok(a, cast.event())
    ok(a, cast.publish())
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    b = Ledger(me, JsonlStore(str(path)), settings, clock=clock)
    assert [e["hash"] for e in b.chain] == [e["hash"] for e in a.chain]
    assert err(b, cast.event()) == "event already declared"  # rules see the reloaded chain
    ok(b, cast.publish(content="doc B"))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_r2_12_corrupt_file_refuses_to_start(tmp_path, settings, clock, cast):
    path = tmp_path / "ledger.jsonl"
    a = Ledger(Identity.generate(), JsonlStore(str(path)), settings, clock=clock)
    ok(a, cast.publish(ev=None))
    ok(a, cast.share())
    lines = path.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[0])
    e["payload"]["author"] = cast.other.pub
    path.write_text("\n".join([json.dumps(e, ensure_ascii=False)] + lines[1:]) + "\n", encoding="utf-8")
    with pytest.raises(LedgerCorrupt) as x:
        Ledger(Identity.generate(), JsonlStore(str(path)), settings, clock=clock)
    assert "seq 0" in str(x.value)
