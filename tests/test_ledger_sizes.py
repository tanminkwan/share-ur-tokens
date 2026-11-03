"""The chain must not grow fat (user 2026-11-03: "free-form field 상한 타이트하게 고정하고, 원장 체인이 너무 커지면 안 되니까").
An entry is at most ARENA_LEDGER_ENTRY_MAX_BYTES; the fields its type does not know (free-form) at most
ARENA_LEDGER_FREE_MAX_BYTES together. Content stays off the ledger: its hash, a ref, a link peer."""
import dataclasses

from arena.crypto import Identity
from arena.ledger import ENTRY_TYPES, EntryType, register_entry_type
from tests.test_trust import Net, net  # noqa: F401  (net is a fixture)


async def _publish(net, me, **extra):
    import os
    ch = extra.pop("content_hash", None) or os.urandom(32).hex()  # one registration per content hash
    p = {"author": me.pub, "content_hash": ch, "group_id": "public", "ledger_id": net.ledger_id, **extra}
    return await net.svc.record("publish", p, {me.pub: me.sign(p)})


async def test_free_form_fields_are_capped_tightly(net, settings):
    me = Identity.generate()
    assert settings.ledger_free_max_bytes == 256 and settings.ledger_entry_max_bytes == 4096  # the defaults, tight on purpose
    r = await _publish(net, me, note="짧은 메모")
    assert r["ok"]  # a little free-form is fine
    big = await _publish(net, Identity.generate(), note="가" * 100, extra="x")  # 300 bytes of Korean
    assert "free-form fields too large (extra, note" in big["error"] and "off the ledger" in big["error"]
    # free-form is a short natural-language note: a value code would act on gets its own field
    coded = await _publish(net, Identity.generate(), extra={"link": "a" * 64})
    assert "short text only (extra is not text)" in coded["error"] and "its own field" in coded["error"]
    # the fields the type knows are not free-form: a long label is the label's own rule, not this cap
    known = await _publish(net, Identity.generate(), label="L" * settings.ledger_label_max)
    assert known["ok"]


async def test_one_entry_is_capped_and_types_without_declared_fields_only_by_that(net, settings):
    small = dataclasses.replace(settings, ledger_entry_max_bytes=400)
    net.svc.ledger.settings = small
    me = Identity.generate()
    assert "entry too large" in (await _publish(net, me, content_hash="c" * 64,
                                                ref={"content_hash": "c" * 64, "storage": [{"kind": "https", "location": "x" * 300}]}))["error"]
    if "sized" not in ENTRY_TYPES:
        register_entry_type(EntryType("sized", lambda p: [p.get("who")]))  # an app's type that declares no fields
    who = Identity.generate()
    p = {"who": who.pub, "group_id": "public", "ledger_id": net.ledger_id, "anything": "y" * 200}
    assert (await net.svc.record("sized", p, {who.pub: who.sign(p)}))["ok"]  # its fields are its own: only the entry cap
    p2 = dict(p, anything="y" * 400)
    assert "entry too large" in (await net.svc.record("sized", p2, {who.pub: who.sign(p2)}))["error"]


def test_every_built_in_type_declares_its_fields():
    builtin = {"genesis", "group", "event", "contract", "publish", "share", "feedback", "attest", "reveal", "assign", "close",
               "key_rotate", "chain_link", "parent_link", "codebook", "key_commit", "peer_rotate"}
    for name in builtin:
        f = ENTRY_TYPES[name].fields
        assert (f() if callable(f) else f), name
    assert {"elements", "schedule", "codebook"} <= ENTRY_TYPES["event"].fields()  # registered event columns are known
