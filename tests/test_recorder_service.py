"""R3: the recorder service object (no HTTP)."""
import asyncio

import pytest

from arena.recorder.service import RecorderService
from arena.crypto import Identity
from arena.ledger import MemoryStore
from tests.test_ledger import Cast


@pytest.fixture
def cast():
    return Cast()


@pytest.fixture
def reader():
    return Identity.generate()


@pytest.fixture
def svc(settings, clock, reader):
    return RecorderService.build(settings, identity=Identity.generate(), store=MemoryStore(), readers=[reader.pub], clock=clock)


async def test_r3_1_record_returns_seq_hash_seal(svc, cast):
    r = await svc.record(*cast.publish(ev=None))
    assert r["ok"] and r["seq"] == 0 and len(r["hash"]) == 64 and r["seal"]["pub"] == svc.identity.pub
    bad = await svc.record(*cast.publish(ev=None))
    assert bad == {"ok": False, "error": "content already published (first publisher wins)"}


async def test_r3_1_concurrent_records_are_serialized(svc, cast):
    entries = [cast.publish(content=f"doc {i}", ev=None) for i in range(20)]
    res = await asyncio.gather(*(svc.record(*e) for e in entries))
    assert all(r["ok"] for r in res)
    assert sorted(r["seq"] for r in res) == list(range(20))
    assert svc.audit()["status"] == "ok"



def meta(v: dict) -> dict:
    """the public view without where and when (seq, ts, ledger_id are checked in their own test)"""
    return {k: x for k, x in v.items() if k not in ("seq", "ts", "ledger_id")}


async def test_pa7_verify_reveals_only_public_metadata(svc, cast):
    ev = await svc.record(*cast.event(approvers=[cast.approver]))
    hidden = await svc.record(*cast.contract(role="judge"))
    shown = await svc.record(*cast.contract(role="keeper", contractor=cast.keeper, nonce="c2"))
    pb = await svc.record(*cast.publish())
    assert meta(svc.verify(ev["hash"])) == {"ok": True, "exists": True, "type": "event", "seal_ok": True, "event_id": cast.ev, "group_id": "g-test",
                                      "issuer": cast.issuer.pub, "kind": "test", "approvers": [cast.approver.pub]}
    assert meta(svc.verify(hidden["hash"])) == {"ok": True, "exists": True, "type": "contract", "seal_ok": True, "event_id": cast.ev, "group_id": "g-test",
                                          "role": "judge", "issuer": cast.issuer.pub, "contractor": None}  # hidden by policy
    assert meta(svc.verify(shown["hash"]))["contractor"] == cast.keeper.pub
    assert meta(svc.verify(pb["hash"])) == {"ok": True, "exists": True, "type": "publish", "seal_ok": True, "event_id": cast.ev, "group_id": "g-test",
                                      "author": cast.author.pub, "content_hash": pb_hash(cast)}


def pb_hash(cast):
    return cast.publish()[1]["content_hash"]


async def test_p5a7_verify_close_and_attest(svc, cast):
    await svc.record(*cast.event(policy={}))
    at = await svc.record(*cast.attest(value={"winner": "judge"}))
    cl = await svc.record(*cast.close(result_hash="r" * 64))
    assert meta(svc.verify(at["hash"])) == {"ok": True, "exists": True, "type": "attest", "seal_ok": True, "event_id": cast.ev, "group_id": "g-test", "kind": "match",
                                      "subject": "m1", "parties": [cast.judge.pub, cast.keeper.pub], "value": {"winner": "judge"}}
    assert meta(svc.verify(cl["hash"])) == {"ok": True, "exists": True, "type": "close", "seal_ok": True, "event_id": cast.ev, "group_id": "g-test",
                                      "issuer": cast.issuer.pub, "result_hash": "r" * 64}
    assert meta(svc.verify("0" * 64)) == {"ok": True, "exists": False, "type": None, "seal_ok": False, "event_id": None, "group_id": None}


async def test_r3_3_audit(svc, cast):
    assert svc.audit() == {"ok": True, "status": "ok", "length": 0, "head": "0" * 64}
    r = await svc.record(*cast.publish(ev=None))
    assert svc.audit() == {"ok": True, "status": "ok", "length": 1, "head": r["hash"]}


async def test_r3_4_chain_only_for_allow_listed_and_logged(svc, cast, reader, settings):
    await svc.record(*cast.publish(ev=None))
    assert svc.read_chain(reader.pub)["ok"] and len(svc.read_chain(reader.pub)["chain"]) == 1
    denied = svc.read_chain(cast.other.pub)
    assert denied == {"ok": False, "error": "not authorized"}
    log = svc.access_log
    assert [x["granted"] for x in log][-1] is False and log[-1]["reader"] == cast.other.pub
    for _ in range(settings.access_log_size + 3):
        svc.read_chain(reader.pub)
    assert len(svc.access_log) == settings.access_log_size


def test_r3_5_access_log_only_for_allow_listed(svc, reader):
    svc.read_chain(Identity.generate().pub)
    assert svc.read_access_log(reader.pub)["ok"] and len(svc.read_access_log(reader.pub)["log"]) >= 1
    assert svc.read_access_log(Identity.generate().pub) == {"ok": False, "error": "not authorized"}


async def test_r3_6_health(svc, cast, settings):
    await svc.record(*cast.publish(ev=None))
    hl = svc.health()
    assert hl["ok"] and hl["name"] == settings.recorder_name and hl["pub"] == svc.identity.pub
    assert hl["pen_name"].startswith(settings.pen_name_prefix) and hl["length"] == 1 and hl["head"] == svc.ledger.head()


def test_r3_7_readers_come_from_settings(tmp_path):
    from arena.config import Settings
    from tests.conftest import make_env
    r = Identity.generate()
    s = Settings.load(env=make_env(tmp_path, ARENA_RECORDER_READERS=r.pub), dotenv_path=None)
    svc = RecorderService.build(s, identity=Identity.generate(), store=MemoryStore())
    assert svc.read_chain(r.pub)["ok"]
    s2 = Settings.load(env=make_env(tmp_path), dotenv_path=None)
    svc2 = RecorderService.build(s2, identity=Identity.generate(), store=MemoryStore())
    assert not svc2.read_chain(r.pub)["ok"]


def test_r3_8_build_from_settings_uses_key_and_ledger_files(settings):
    a = RecorderService.from_settings(settings)
    b = RecorderService.from_settings(settings)
    assert a.identity.pub == b.identity.pub



async def test_p5a16_verify_group_declaration(svc, cast):
    from tests.test_ledger import group_decl
    b = Identity.generate()
    r = await svc.record(*group_decl(cast.issuer, gid="g-hr", closed=True, brokers=[b.pub]))
    assert meta(svc.verify(r["hash"])) == {"ok": True, "exists": True, "type": "group", "seal_ok": True, "event_id": None, "group_id": "g-hr",
                                     "founder": cast.issuer.pub, "closed": True, "brokers": [b.pub]}



async def test_p5a18_verify_genesis(svc):
    from tests.test_ledger import genesis_entry
    god = Identity.generate()
    r = await svc.record(*genesis_entry(god, broker_pub="b" * 64, recorder_pub=svc.identity.pub))
    assert meta(svc.verify(r["hash"])) == {"ok": True, "exists": True, "type": "genesis", "seal_ok": True, "event_id": None, "group_id": "public",
                                     "god": god.pub, "broker": "b" * 64, "recorder": svc.identity.pub}


async def test_p5a19_verify_returns_rules_hash(svc, cast):
    kind, p, _ = cast.event(policy={})
    p["rules_hash"] = "f" * 64
    ev = await svc.record(kind, p, {cast.issuer.pub: cast.issuer.sign(p)})
    kind, c, _ = cast.contract(role="judge")
    c["rules_hash"] = "f" * 64
    ct = await svc.record(kind, c, {cast.issuer.pub: cast.issuer.sign(c), cast.judge.pub: cast.judge.sign(c)})
    assert meta(svc.verify(ev["hash"]))["rules_hash"] == "f" * 64 and meta(svc.verify(ct["hash"]))["rules_hash"] == "f" * 64


async def test_pa7_verify_tells_where_and_when_so_a_book_can_point_back_to_the_ledger(svc, cast):
    """user 2026-11-02: a novel's hash is registered; the book prints the author's identity and how to reach the entry. From
    the book anyone finds the entry and sees which ledger holds it, its position, and the recorder's time (prior existence)."""
    await svc.record(*cast.event())
    pb = await svc.record(*cast.publish())
    v = svc.verify(pb["hash"])
    e = svc.ledger.find(pb["hash"])
    assert v["seq"] == e["seq"] and v["ts"] == e["ts"] and v["ledger_id"] == svc.ledger.chain[0]["hash"]
    assert v["content_hash"] == e["payload"]["content_hash"] and v["author"] == e["payload"]["author"]
