"""P8-A3, P8-C2: the files a root-key ceremony passes around (dev/phase8/design.md 3): requests, signatures, the
retirement declaration. Pure functions, no network."""
import pytest

from arena.ceremony import formats as F
from arena.crypto import Identity

GOD, OTHER = Identity.generate(), Identity.generate()


def req(**over):
    items = over.pop("items", [F.item("genesis", "genesis", {"group_id": "public", "god": GOD.pub}, [GOD.pub])])
    return F.request(over.pop("round_", 1), over.pop("chain", "trunk"), None, GOD.pub, items, 1.0)


def test_p8a3_a_request_is_signed_by_its_signers_and_the_signatures_are_checked():
    r = req()
    assert F.request_error(r) is None
    got, err = F.collect(r, [F.sign(r, GOD)])
    assert err is None and list(got["genesis"]) == [GOD.pub]
    with pytest.raises(ValueError):
        F.sign(r, OTHER)  # a key that signs nothing here


def test_p8a3_signatures_for_another_request_or_payload_or_key_are_refused():
    r, other = req(), req(items=[F.item("genesis", "genesis", {"group_id": "public", "god": OTHER.pub}, [GOD.pub])])
    assert "another request" in F.collect(r, [F.sign(other, GOD)])[1]
    forged = dict(F.sign(r, GOD), sigs={"genesis": OTHER.sign(r["items"][0]["payload"])})
    assert "bad signature" in F.collect(r, [forged])[1]
    stranger = dict(F.sign(r, GOD), signer=OTHER.pub, sigs={"genesis": OTHER.sign(r["items"][0]["payload"])})
    assert "does not sign" in F.collect(r, [stranger])[1]
    assert "still needs" in F.collect(r, [])[1]
    assert "known version" in F.collect(r, [{"format": "x"}])[1]


def test_p8b3_an_item_with_two_signers_needs_both_files():
    new = Identity.generate()
    r = req(items=[F.item("key_rotate", "key_rotate", {"role": "god", "old": GOD.pub, "new": new.pub}, [GOD.pub, new.pub])])
    assert "still needs" in F.collect(r, [F.sign(r, GOD)])[1]
    got, err = F.collect(r, [F.sign(r, GOD), F.sign(r, new)])
    assert err is None and set(got["key_rotate"]) == {GOD.pub, new.pub}


def test_requests_have_a_known_chain_and_named_items():
    with pytest.raises(ValueError):
        req(chain="side")
    with pytest.raises(ValueError):
        req(items=[])
    assert F.request_error({"format": F.REQUEST, "version": 1, "round": 1, "chain": "trunk", "god": GOD.pub, "items": [{"name": "x"}]})


def decl(witnesses, **over):
    b = dict(key="a" * 64, role="recorder", ledger_id="b" * 64, handover="c" * 64, head={"seq": 1, "hash": "d" * 64},
             method="memory-only", at=2.0, witnesses=witnesses, note="rehearsal")
    b.update(over)
    return F.declaration(**b)


def test_p8c2_c3_a_declaration_needs_its_named_witnesses_signatures():
    w1, w2 = Identity.generate(), Identity.generate()
    d = decl([w1.pub, w2.pub])
    assert "not signed yet" in F.declaration_error(d, 2, 256)
    d = F.witness_sign(F.witness_sign(d, w1), w2)
    assert F.declaration_error(d, 2, 256) is None
    assert F.declaration_hash(d) == F.declaration_hash(decl([w1.pub, w2.pub]))  # the signatures are not in the hash
    with pytest.raises(ValueError):
        F.witness_sign(d, Identity.generate())  # not a named witness
    d["sigs"][w1.pub] = w2.sign(d["body"])
    assert "bad signature" in F.declaration_error(d, 2, 256)


def test_p8c2_the_declaration_s_fields_are_checked():
    w1, w2 = Identity.generate(), Identity.generate()
    assert "at least 2" in F.declaration_error(decl([w1.pub]), 2, 256)
    assert "not the retired key" in F.declaration_error(decl([w1.pub, "a" * 64]), 2, 256)
    assert "method" in F.declaration_error(decl([w1.pub, w2.pub], method="burned"), 2, 256)
    assert "short text" in F.declaration_error(decl([w1.pub, w2.pub], note="x" * 300), 2, 256)
    assert "dedicated fields" in F.declaration_error(decl([w1.pub, w2.pub], handover="not a hash"), 2, 256)
    bad = decl([w1.pub, w2.pub])
    bad["body"]["extra"] = 1
    assert "exactly" in F.declaration_error(bad, 2, 256)
