"""P8-C2 .. C5: witnesses sign the retirement declaration, one records its hash, anyone verifies it (in memory; the real
processes are in tests/test_ceremony_process.py)."""
import json
import os

import pytest

from arena.ceremony import formats as F
from arena.ceremony import retire
from arena.ceremony import run as R
from arena.crypto import Identity
from arena.ledger import JsonlStore
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from tests.test_ceremony_run import captured, ceremony  # noqa: F401  (captured is a fixture)


@pytest.fixture
async def done(settings, tmp_path, captured):
    god = Identity.generate()
    out, folder, _ = await ceremony(settings, tmp_path, god)
    d = json.load(open(os.path.join(folder, R.DECLARATION)))
    svc = RecorderService.build(settings, Identity.load(os.path.join(folder, R.RECORDER_KEY)), JsonlStore(os.path.join(folder, R.LEDGER)))
    return dict(out=out, decl=d, rec=InMemoryRecorderClient(svc), svc=svc, settings=settings)


def with_witnesses(d, n=2):
    keys = [Identity.generate() for _ in range(n)]
    d = dict(d, body=dict(d["body"], witnesses=[k.pub for k in keys]), sigs={})
    return d, keys


async def test_p8c3_c4_c5_two_witnesses_sign_one_records_anyone_verifies(done):
    d, (w1, w2) = with_witnesses(done["decl"])
    s, rec = done["settings"], done["rec"]
    assert "not signed yet" in (await retire.publish(F.witness_sign(d, w1), w1, rec, s))["error"]
    d = F.witness_sign(F.witness_sign(d, w1), w2)
    before = await retire.verify(d, rec, s)
    assert not before["ok"] and before["anchored"] is False and all(c["ok"] for c in before["checks"])  # right, but not fixed in time
    assert "one of its witnesses" in (await retire.publish(d, Identity.generate(), rec, s))["error"]
    r = await retire.publish(d, w1, rec, s)
    assert r["ok"] and done["svc"].verify(r["entry"])["purpose"] == "retirement"
    after = await retire.verify(d, rec, s)
    assert after["ok"] and after["anchored"] and [c["check"] for c in after["checks"]] == \
        ["shape and witnesses", "same ledger", "handed over before it went", "head on the ledger", "hash on the ledger"]
    assert "already published" in (await retire.publish(d, w2, rec, s))["error"]


async def test_p8c5_a_wrong_declaration_says_why(done):
    s, rec = done["settings"], done["rec"]
    signed = lambda d, ks: F.witness_sign(F.witness_sign(d, ks[0]), ks[1])

    def changed(**body):
        d, ks = with_witnesses(done["decl"])
        return signed(dict(d, body=dict(d["body"], **body)), ks)
    assert "not this ledger" not in str(await retire.verify(changed(), rec, s))
    cases = {"this recorder keeps ledger": changed(ledger_id="0" * 64),
             "no key_rotate with this hash": changed(handover="0" * 64),
             "did not hand this key over": changed(key=done["out"]["recorder"]),
             "not this ledger's entry": changed(head={"seq": 0, "hash": done["decl"]["body"]["head"]["hash"]})}
    for why, d in cases.items():
        v = await retire.verify(d, rec, s)
        assert not v["ok"] and any(why in c.get("why", "") for c in v["checks"] if not c["ok"]), (why, v)
    d, ks = with_witnesses(done["decl"], 1)
    assert "at least 2" in (await retire.verify(F.witness_sign(d, ks[0]), rec, s))["checks"][0]["why"]
    d, ks = with_witnesses(done["decl"])
    d = signed(d, ks)
    d["sigs"][Identity.generate().pub] = "00"
    assert "not a named witness" in (await retire.verify(d, rec, s))["checks"][0]["why"]


async def test_p8c4_the_ledger_takes_retirement_only_on_publish_and_without_a_label(done):
    me, s = Identity.generate(), done["settings"]
    p = {"author": me.pub, "content_hash": "e" * 64, "purpose": "retirement", "label": "x", "group_id": "public",
         "ledger_id": done["out"]["ledger_id"], "nonce": "n1"}
    assert "without a label" in (await done["rec"].record("publish", p, {me.pub: me.sign(p)}))["error"]
    s2 = dict(p, purpose="retirement", label=None)
    s2.pop("label")
    share = {"provider": me.pub, "consumer": Identity.generate().pub, "content_hash": "f" * 64, "purpose": "retirement",
             "group_id": "public", "ledger_id": done["out"]["ledger_id"], "nonce": "n2"}
    assert "not for share" in (await done["rec"].record("share", share, {me.pub: me.sign(share)}))["error"]
    assert (await done["rec"].record("publish", s2, {me.pub: me.sign(s2)}))["ok"]
