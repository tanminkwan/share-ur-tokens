"""R2 + P2-A: generic ledger rules, event declarations with policy and approvals, audit, contribution, persistence."""
import json

import pytest

from arena.crypto import Identity, canon, h, verify
from arena.ledger import JsonlStore, Ledger, LedgerCorrupt, MemoryStore, audit_chain, contribution

# an example policy; the platform only compares these strings, it does not know what they mean
POLICY = {"roles": ["keeper", "judge"], "conflict_roles": ["keeper", "judge"],
          "verdict_roles": {"score": "judge", "pick": "issuer"}, "hidden_roles": ["judge"],
          "attest_roles": {"match": "judge", "rank": "issuer"}}


GROUP = "g-test"  # broker group identifier every ledger entry carries (P5-A11)


class Cast:
    """author, event issuer, a contracted judge, a keeper, an approver, a stranger; builders for signed entries"""

    def __init__(self):
        self.author, self.issuer, self.judge, self.keeper, self.approver, self.other = (Identity.generate() for _ in range(6))
        self.ev, self.group = "ev-1", GROUP

    def event(self, ev=None, policy=None, approvers=(), issuer=None, sign_by=None):
        i = issuer or self.issuer
        p = {"event_id": ev or self.ev, "issuer": i.pub, "kind": "test", "policy": POLICY if policy is None else policy,
             "approvers": [a.pub for a in approvers], "group_id": self.group}
        sigs = {i.pub: i.sign(p)}
        for a in (approvers if sign_by is None else sign_by):
            sigs[a.pub] = a.sign(p)
        return "event", p, sigs

    def publish(self, content="doc A", author=None, ev="__default__"):
        a = author or self.author
        p = {"author": a.pub, "content_hash": h(canon({"c": content})), "group_id": self.group}
        if ev is not None:
            p["event_id"] = self.ev if ev == "__default__" else ev
        return "publish", p, {a.pub: a.sign(p)}

    def share(self, content="doc A", provider=None, consumer=None, nonce="n1"):
        pr, co = provider or self.author, consumer or self.issuer
        p = {"provider": pr.pub, "consumer": co.pub, "content_hash": h(canon({"c": content})), "terms": "t", "nonce": nonce,
             "group_id": self.group}
        return "share", p, {pr.pub: pr.sign(p), co.pub: co.sign(p)}

    def contract(self, role="judge", contractor=None, nonce="c1", ev=None, issuer=None):
        c, i = contractor or self.judge, issuer or self.issuer
        p = {"event_id": ev or self.ev, "role": role, "issuer": i.pub, "contractor": c.pub, "nonce": nonce, "group_id": self.group}
        return "contract", p, {i.pub: i.sign(p), c.pub: c.sign(p)}

    def close(self, ev=None, issuer=None, result_hash=None):
        i = issuer or self.issuer
        p = {"event_id": ev or self.ev, "issuer": i.pub, "group_id": self.group, **({"result_hash": result_hash} if result_hash else {})}
        return "close", p, {i.pub: i.sign(p)}

    def attest(self, kind="match", subject="m1", value=None, parties=None, nonce="a1", ev="__default__", sign_by=None):
        ps = parties if parties is not None else [self.judge, self.keeper]
        p = {"kind": kind, "subject": subject, "value": value if value is not None else {"winner": "x"},
             "parties": [x.pub for x in ps], "nonce": nonce, "group_id": self.group}
        if ev is not None:
            p["event_id"] = self.ev if ev == "__default__" else ev
        return "attest", p, {x.pub: x.sign(p) for x in (ps if sign_by is None else sign_by)}

    def feedback(self, verdict="score", evaluator=None, content="doc A", ev="__default__", **extra):
        e = evaluator or self.judge
        p = {"evaluator": e.pub, "content_hash": h(canon({"c": content})), "verdict": verdict, "group_id": self.group, **extra}
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
                                  "verdicts_given": {}, "roles": {}, "events": 0, "approvals": 0, "attested": {}, "closed": 0, "groups": 0}
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



# ---------------- close and attest (P5-A) ----------------
def test_p5a1_close_once_by_the_issuer(ledger, cast):
    assert err(ledger, cast.close()) == "unknown event"
    ok(ledger, cast.event())
    assert err(ledger, cast.close(issuer=cast.other)) == "only the event issuer can close it"
    e = ok(ledger, cast.close(result_hash="r" * 64))
    assert e["payload"]["result_hash"] == "r" * 64
    assert err(ledger, cast.close()) == "event closed"


def test_p5a2_nothing_enters_a_closed_event(ledger, cast):
    ok(ledger, cast.event())
    ok(ledger, cast.publish())
    ok(ledger, cast.share(consumer=cast.issuer))
    ok(ledger, cast.close())
    assert err(ledger, cast.contract()) == "event closed"
    assert err(ledger, cast.publish(content="late")) == "event closed"
    assert err(ledger, cast.feedback("pick", evaluator=cast.issuer)) == "event closed"
    assert err(ledger, cast.attest(kind="free", parties=[cast.other])) == "event closed"
    ok(ledger, cast.publish(content="outside", ev=None))  # outside any event is unaffected


def test_p5a3_attest_needs_every_party(ledger, cast):
    ok(ledger, cast.event(policy={}))
    assert err(ledger, cast.attest(sign_by=[cast.judge])).startswith("missing/invalid signature")
    assert err(ledger, cast.attest(parties=[])) == "attest needs at least one party"
    assert err(ledger, cast.attest(parties=[cast.judge, cast.judge])) == "duplicate parties"
    e = ok(ledger, cast.attest())
    assert set(e["sigs"]) == {cast.judge.pub, cast.keeper.pub}
    ok(ledger, cast.attest(kind="note", subject="x", parties=[cast.other], nonce="a9", ev=None))  # no event: generic rules only


def test_p5a4_one_attest_per_kind_and_subject_and_single_use_nonce(ledger, cast):
    ok(ledger, cast.event(policy={}))
    ok(ledger, cast.attest(subject="m1", nonce="a1"))
    assert err(ledger, cast.attest(subject="m1", nonce="a2")) == "already attested (kind, subject) in this event"
    assert err(ledger, cast.attest(subject="m2", nonce="a1")) == "replay (nonce already used)"
    ok(ledger, cast.attest(subject="m2", nonce="a2"))
    ok(ledger, cast.attest(kind="other", subject="m1", nonce="a3"))


def test_p5a5_attest_roles(ledger, cast):
    ok(ledger, cast.event())
    assert err(ledger, cast.attest(kind="match", parties=[cast.judge, cast.other])) == "attest 'match' requires every party to hold the 'judge' role in this event"
    ok(ledger, cast.contract(role="judge", contractor=cast.judge, nonce="c1"))
    ok(ledger, cast.contract(role="judge", contractor=cast.keeper, nonce="c2"))
    ok(ledger, cast.attest(kind="match", parties=[cast.judge, cast.keeper]))
    assert err(ledger, cast.attest(kind="rank", subject="final", parties=[cast.judge], nonce="a2")) == "attest 'rank' must be by the event issuer alone"
    ok(ledger, cast.attest(kind="rank", subject="final", parties=[cast.issuer], nonce="a3"))
    ok(ledger, cast.attest(kind="chat", subject="x", parties=[cast.other], nonce="a4"))  # kinds the policy does not name are free
    assert err(ledger, cast.event(ev="bad", policy={"attest_roles": {"x": 1}})) == "bad policy"


def test_p5a6_contribution_counts_attests_and_closes(ledger, cast):
    ok(ledger, cast.event(policy={}))
    ok(ledger, cast.attest())
    ok(ledger, cast.close())
    c = contribution(ledger.chain)
    assert c[cast.judge.pub]["attested"] == {"match": 1} and c[cast.keeper.pub]["attested"] == {"match": 1}
    assert c[cast.issuer.pub]["closed"] == 1 and c[cast.issuer.pub]["events"] == 1



def test_p5a11_every_entry_needs_a_group_id(ledger, cast):
    kind, p, _ = cast.publish(ev=None)
    del p["group_id"]
    assert err(ledger, (kind, p, {cast.author.pub: cast.author.sign(p)})) == "group_id required"
    p["group_id"] = ""
    assert err(ledger, (kind, p, {cast.author.pub: cast.author.sign(p)})) == "group_id required"


def group_decl(founder, gid="g-test", closed=False, brokers=()):
    p = {"group_id": gid, "founder": founder.pub, "closed": closed, "brokers": list(brokers)}
    return "group", p, {founder.pub: founder.sign(p)}


def genesis_entry(god, broker_pub="b" * 64, recorder_pub="r" * 64, gid="public"):
    p = {"group_id": gid, "god": god.pub, "broker": broker_pub, "recorder": recorder_pub}
    return "genesis", p, {god.pub: god.sign(p)}


@pytest.fixture
def god():
    return Identity.generate()


@pytest.fixture
def bare(tmp_path, clock):
    """a strict ledger before the genesis"""
    from arena.config import Settings
    from tests.conftest import make_env
    s = Settings.load(env=make_env(tmp_path, ARENA_RECORDER_REQUIRE_GROUP="true"), dotenv_path=None)
    return Ledger(Identity.generate(), MemoryStore(), s, clock=clock)


@pytest.fixture
def strict(bare, god):
    ok(bare, genesis_entry(god))
    return bare


def test_p5a14_group_declared_once_by_its_founder(strict, cast):
    b1 = Identity.generate()
    e = ok(strict, group_decl(cast.issuer, brokers=[b1.pub]))
    assert e["payload"]["founder"] == cast.issuer.pub and e["seq"] == 1
    assert err(strict, group_decl(cast.other)) == "group already declared"
    kind, p, _ = group_decl(cast.issuer, gid="g2")
    assert err(strict, (kind, p, {cast.issuer.pub: cast.other.sign(p)})).startswith("missing/invalid signature")
    assert err(strict, ("group", {"group_id": "g3", "founder": cast.issuer.pub, "closed": "yes", "brokers": []},
                        {cast.issuer.pub: cast.issuer.sign({"group_id": "g3", "founder": cast.issuer.pub, "closed": "yes", "brokers": []})})) == "bad group declaration"


def test_p5a15_entries_must_name_a_declared_group(strict, cast):
    assert err(strict, cast.publish(ev=None)) == "unknown group: g-test"
    ok(strict, group_decl(cast.issuer))
    ok(strict, cast.publish(ev=None))
    cast.group = "g-undeclared"
    assert err(strict, cast.event()) == "unknown group: g-undeclared"


def test_p5a16_contribution_counts_founded_groups(strict, cast):
    ok(strict, group_decl(cast.issuer))
    ok(strict, group_decl(cast.issuer, gid="g-2", closed=True))
    assert contribution(strict.chain)[cast.issuer.pub]["groups"] == 2



def test_p5a17_genesis_group_exists_from_the_beginning(strict, cast, settings):
    cast.group = settings.genesis_group_id
    ok(strict, cast.publish(ev=None))  # usable without any declaration
    assert err(strict, group_decl(cast.issuer, gid=settings.genesis_group_id)) == "the genesis group exists from the beginning and cannot be declared"



def test_p5a18_the_ledger_starts_with_the_genesis(bare, god, cast, settings):
    assert err(bare, cast.publish(ev=None)) == "the ledger starts with the genesis"
    assert err(bare, genesis_entry(god, gid="other")) == "the genesis creates the genesis group"
    e = ok(bare, genesis_entry(god))
    assert e["seq"] == 0 and e["payload"]["god"] == god.pub
    assert err(bare, genesis_entry(god)) == "the genesis happens once, as the first entry"
    cast.group = settings.genesis_group_id
    ok(bare, cast.publish(ev=None))  # after the genesis, the genesis group is usable without a declaration


def test_p5a18_genesis_is_signed_by_god(bare, god):
    kind, p, _ = genesis_entry(god)
    assert err(bare, (kind, p, {god.pub: Identity.generate().sign(p)})).startswith("missing/invalid signature")
