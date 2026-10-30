"""R2: ledger rules, chain, audit, contribution, persistence. Pure unit tests: no network."""
import json

import pytest

from arena.crypto import Identity, canon, h, verify
from arena.ledger import JsonlStore, Ledger, LedgerCorrupt, MemoryStore, audit_chain, contribution


class Cast:
    """author, event issuer, a contracted reviewer, a recorder-contractor; plus helpers to build signed entries"""

    def __init__(self):
        self.author, self.issuer, self.reviewer, self.recorder, self.other = (Identity.generate() for _ in range(5))
        self.call = "call-1"

    def publish(self, content="idea A", author=None, call=None):
        a = author or self.author
        p = {"author": a.pub, "content_hash": h(canon({"idea": content})), "call_id": call or self.call}
        return "publish", p, {a.pub: a.sign(p)}

    def share(self, content="idea A", provider=None, consumer=None, nonce="n1"):
        pr, co = provider or self.author, consumer or self.issuer
        p = {"provider": pr.pub, "consumer": co.pub, "content_hash": h(canon({"idea": content})), "terms": "t", "nonce": nonce}
        return "share", p, {pr.pub: pr.sign(p), co.pub: co.sign(p)}

    def contract(self, role="review", contractor=None, nonce="c1", call=None):
        c = contractor or self.reviewer
        p = {"call_id": call or self.call, "role": role, "issuer": self.issuer.pub, "contractor": c.pub, "nonce": nonce}
        return "contract", p, {self.issuer.pub: self.issuer.sign(p), c.pub: c.sign(p)}

    def feedback(self, verdict="review", evaluator=None, content="idea A", score=7.0):
        e = evaluator or self.reviewer
        p = {"evaluator": e.pub, "call_id": self.call, "content_hash": h(canon({"idea": content})), "verdict": verdict}
        if verdict == "review":
            p.update(score=score, comment_hash=h(b"c"))
        else:
            p.update(reason_hash=h(b"r"))
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


def test_r2_1_unknown_type_rejected(ledger, cast):
    _, err = ledger.propose("bogus", {}, {})
    assert err == "unknown type"


def test_r2_2_missing_or_wrong_signature_rejected(ledger, cast):
    kind, p, sigs = cast.publish()
    assert ledger.propose(kind, p, {})[1].startswith("missing/invalid signature")
    assert ledger.propose(kind, p, {cast.author.pub: cast.other.sign(p)})[1].startswith("missing/invalid signature")
    kind, p, sigs = cast.share()
    del sigs[cast.issuer.pub]  # share needs both provider and consumer
    ok(ledger, cast.publish())
    assert ledger.propose(kind, p, sigs)[1].startswith("missing/invalid signature")


def test_r2_3_chain_links_and_recorder_seal(ledger, cast):
    e0 = ok(ledger, cast.publish())
    e1 = ok(ledger, cast.share())
    assert e0["seq"] == 0 and e1["seq"] == 1
    assert e0["prev"] == "0" * 64 and e1["prev"] == e0["hash"]
    assert e1["hash"] == h(canon({k: e1[k] for k in ("type", "payload", "sigs", "prev", "ts")}))
    assert e1["seal"]["pub"] == ledger.identity.pub and verify(ledger.identity.pub, e1["hash"], e1["seal"]["sig"])
    assert ledger.head() == e1["hash"] and ledger.find(e0["hash"]) is e0 and ledger.find("nope") is None


def test_r2_4_timestamp_cannot_go_backwards(ledger, cast, clock):
    ok(ledger, cast.publish())
    clock.tick(-5)
    assert ledger.propose(*cast.share())[1] == "timestamp goes backwards"


def test_r2_5_first_publisher_wins(ledger, cast):
    ok(ledger, cast.publish())
    assert ledger.propose(*cast.publish(author=cast.other))[1] == "content already published (first publisher wins)"


def test_r2_6_contractor_cannot_submit_to_same_call(ledger, cast):
    ok(ledger, cast.contract())
    assert ledger.propose(*cast.publish(author=cast.reviewer))[1] == "a contracted recorder/reviewer cannot submit to the same call"
    ok(ledger, cast.publish(author=cast.reviewer, call="call-2"))  # another event is fine


def test_r2_7_share_needs_publish_and_nonce_is_single_use(ledger, cast):
    assert ledger.propose(*cast.share())[1] == "unknown content"
    ok(ledger, cast.publish())
    ok(ledger, cast.share(nonce="n1"))
    assert ledger.propose(*cast.share(nonce="n1", consumer=cast.other))[1] == "replay (nonce already used)"
    ok(ledger, cast.share(nonce="n2", consumer=cast.other))
    ok(ledger, cast.contract(nonce="c1"))
    assert ledger.propose(*cast.contract(nonce="c1", contractor=cast.other))[1] == "replay (nonce already used)"


def test_r2_8_contract_role_must_be_allowed(ledger, cast, settings):
    assert "review" in settings.contract_roles
    assert ledger.propose(*cast.contract(role="judge"))[1] == "unsupported role"
    ok(ledger, cast.contract(role="record", contractor=cast.recorder, nonce="c9"))


def test_r2_9_feedback_rules(ledger, cast):
    ok(ledger, cast.publish())
    # review without a contract
    ok(ledger, cast.share(consumer=cast.reviewer, nonce="s1"))
    assert ledger.propose(*cast.feedback("review"))[1] == "no review contract for this call"
    ok(ledger, cast.contract())
    # evaluator never received the content
    assert ledger.propose(*cast.feedback("adopt", evaluator=cast.other))[1] == "evaluator never received this content"
    ok(ledger, cast.feedback("review"))
    assert ledger.propose(*cast.feedback("review", score=3.0))[1] == "duplicate feedback (one verdict per evaluator per content)"
    ok(ledger, cast.share(consumer=cast.issuer, nonce="s2"))
    ok(ledger, cast.feedback("adopt", evaluator=cast.issuer))
    assert ledger.propose(*cast.feedback("adopt", evaluator=cast.issuer))[1].startswith("duplicate feedback")


def test_r2_10_audit_finds_first_tampered_entry(ledger, cast):
    ok(ledger, cast.publish())
    ok(ledger, cast.share())
    ok(ledger, cast.publish(content="idea B"))
    assert ledger.audit() == "ok" and audit_chain(ledger.chain) == "ok"
    tampered = json.loads(json.dumps(ledger.chain))
    tampered[1]["payload"]["terms"] = "changed"
    assert audit_chain(tampered) == "TAMPERED at seq 1 (hash chain)"
    tampered = json.loads(json.dumps(ledger.chain))
    tampered[2]["sigs"][cast.author.pub] = "00" * 64
    tampered[2]["hash"] = h(canon({k: tampered[2][k] for k in ("type", "payload", "sigs", "prev", "ts")}))
    assert audit_chain(tampered) == "TAMPERED at seq 2 (signature)"
    tampered = json.loads(json.dumps(ledger.chain))
    tampered[0]["seal"]["sig"] = "00" * 64
    assert audit_chain(tampered) == "TAMPERED at seq 0 (recorder seal)"


def test_r2_11_contribution_counts_distinct_consumers_adoptions_roles(ledger, cast):
    ok(ledger, cast.publish())
    ok(ledger, cast.share(consumer=cast.issuer, nonce="a"))
    ok(ledger, cast.share(consumer=cast.issuer, nonce="b"))  # same consumer twice counts once
    ok(ledger, cast.share(consumer=cast.author, nonce="c"))  # self-share does not count
    ok(ledger, cast.contract())
    ok(ledger, cast.feedback("adopt", evaluator=cast.issuer))
    c = contribution(ledger.chain)
    assert c[cast.author.pub] == {"received_by": 1, "adopted": 1, "roles": 0}
    assert c[cast.reviewer.pub] == {"received_by": 0, "adopted": 0, "roles": 1}


def test_r2_12_jsonl_store_persists_and_reloads(tmp_path, settings, clock, cast):
    path = tmp_path / "deep" / "ledger.jsonl"
    me = Identity.generate()
    a = Ledger(me, JsonlStore(str(path)), settings, clock=clock)
    ok(a, cast.publish())
    ok(a, cast.share())
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    b = Ledger(me, JsonlStore(str(path)), settings, clock=clock)
    assert [e["hash"] for e in b.chain] == [e["hash"] for e in a.chain]
    ok(b, cast.publish(content="idea B"))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3 and b.head() != a.head()


def test_r2_12_corrupt_file_refuses_to_start(tmp_path, settings, clock, cast):
    path = tmp_path / "ledger.jsonl"
    a = Ledger(Identity.generate(), JsonlStore(str(path)), settings, clock=clock)
    ok(a, cast.publish())
    ok(a, cast.share())
    lines = path.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[0])
    e["payload"]["call_id"] = "forged"
    path.write_text("\n".join([json.dumps(e, ensure_ascii=False)] + lines[1:]) + "\n", encoding="utf-8")
    with pytest.raises(LedgerCorrupt) as x:
        Ledger(Identity.generate(), JsonlStore(str(path)), settings, clock=clock)
    assert "seq 0" in str(x.value)
