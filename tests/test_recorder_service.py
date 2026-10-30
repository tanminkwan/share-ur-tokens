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


async def test_pa7_verify_reveals_only_public_metadata(svc, cast):
    ev = await svc.record(*cast.event(approvers=[cast.approver]))
    hidden = await svc.record(*cast.contract(role="judge"))
    shown = await svc.record(*cast.contract(role="keeper", contractor=cast.keeper, nonce="c2"))
    pb = await svc.record(*cast.publish())
    assert svc.verify(ev["hash"]) == {"ok": True, "exists": True, "type": "event", "seal_ok": True, "event_id": cast.ev,
                                      "issuer": cast.issuer.pub, "kind": "test", "approvers": [cast.approver.pub]}
    assert svc.verify(hidden["hash"]) == {"ok": True, "exists": True, "type": "contract", "seal_ok": True, "event_id": cast.ev,
                                          "role": "judge", "issuer": cast.issuer.pub, "contractor": None}  # hidden by policy
    assert svc.verify(shown["hash"])["contractor"] == cast.keeper.pub
    assert svc.verify(pb["hash"]) == {"ok": True, "exists": True, "type": "publish", "seal_ok": True, "event_id": cast.ev}
    assert svc.verify("0" * 64) == {"ok": True, "exists": False, "type": None, "seal_ok": False, "event_id": None}


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
