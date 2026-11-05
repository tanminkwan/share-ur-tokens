"""P8-A2, A3, B1, B2, C1: ceremony run in one process, with a stand-in for the offline machine that signs each round's
request (the real offline machine is another process, see tests/test_ceremony_process.py)."""
import asyncio
import dataclasses
import glob
import json
import os

import pytest

from arena.ceremony import formats as F
from arena.ceremony import run as R
from arena.crypto import Identity
from arena.ledger import JsonlStore, audit_chain
from arena.ledger.types import current_keys
from arena.recorder.service import RecorderService


def fast(settings, **over):
    return dataclasses.replace(settings, **{"ceremony_poll_sec": 0.01, "ceremony_timeout_sec": 5.0, **over})


async def offline(folder, god, rounds=2, tamper=None):
    """sign each round's request as it appears (tamper: round -> a function changing the signature file first)"""
    done = 0
    while done < rounds:
        path = os.path.join(folder, R.ROUNDS, f"round-{done + 1}.request.json")
        if os.path.exists(path):
            req = json.load(open(path, encoding="utf-8"))
            sig = F.sign(req, god)
            if tamper and done + 1 in tamper:
                bad = tamper.pop(done + 1)(req, sig)
                json.dump(bad, open(path.replace("request", "signatures-bad"), "w"))
                await asyncio.sleep(0.05)
            json.dump(sig, open(path.replace("request", "signatures"), "w"))
            done += 1
        await asyncio.sleep(0.01)


@pytest.fixture
def captured(monkeypatch):
    """every key the ceremony makes, to look for its private half in the files afterwards"""
    made = []
    real = Identity.generate.__func__

    def gen(cls):
        k = real(cls)
        made.append(k)
        return k
    monkeypatch.setattr(R.Identity, "generate", classmethod(gen))
    return made


async def ceremony(settings, tmp_path, god, **kw):
    folder = str(tmp_path / "ceremony")
    w = [Identity.generate().pub, Identity.generate().pub]
    signer = asyncio.create_task(offline(folder, god, kw.pop("rounds", 2), kw.pop("tamper", None)))
    out = await R.run(fast(settings), god.pub, folder, w, say=lambda _: None, **kw)
    await signer
    return out, folder, w


def every_file(folder):
    return {p: open(p, "rb").read() for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True) if os.path.isfile(p)}


async def test_p8a2_the_first_recorder_key_never_touches_the_disk(settings, tmp_path, captured):
    god = Identity.generate()
    out, folder, _ = await ceremony(settings, tmp_path, god)
    first = next(k for k in captured if k.pub == out["first_recorder"])
    operating = next(k for k in captured if k.pub == out["recorder"])
    files = every_file(folder)
    assert not any(first.private_hex().encode() in b for b in files.values())  # in no file, under any name
    assert open(os.path.join(folder, R.RECORDER_KEY)).read().strip() == operating.private_hex()
    assert not glob.glob(os.path.join(folder, "*.retired*"))  # P8-B2: no handed-over key left as a file
    assert not os.path.exists(os.path.join(folder, "god.key")) and open(os.path.join(folder, "god.pub")).read().strip() == god.pub
    assert oct(os.stat(os.path.join(folder, R.RECORDER_KEY)).st_mode & 0o777) == "0o600"


async def test_p8b1_c1_the_ledger_shows_entry_0_and_the_handover_and_genesis_can_take_it_over(settings, tmp_path, captured):
    god = Identity.generate()
    out, folder, w = await ceremony(settings, tmp_path, god)
    raw = JsonlStore(os.path.join(folder, R.LEDGER)).load()
    assert [e["type"] for e in raw] == ["genesis", "key_rotate"] and audit_chain(raw) == "ok"
    assert raw[0]["payload"]["god"] == god.pub and raw[0]["payload"]["recorder"] == out["first_recorder"]
    assert raw[1]["payload"]["old"] == out["first_recorder"] and raw[1]["payload"]["new"] == out["recorder"] and god.pub in raw[1]["sigs"]
    assert current_keys(raw) == {"recorder": out["recorder"], "god": god.pub}
    operating = Identity.load(os.path.join(folder, R.RECORDER_KEY))
    RecorderService.build(fast(settings), operating, JsonlStore(os.path.join(folder, R.LEDGER)))  # the operating key opens it
    d = json.load(open(os.path.join(folder, R.DECLARATION)))
    b = d["body"]
    assert (b["key"], b["role"], b["ledger_id"], b["handover"], b["method"], b["witnesses"]) == \
        (out["first_recorder"], "recorder", out["ledger_id"], out["handover"], "memory-only", w)
    assert b["head"] == {"seq": 1, "hash": raw[1]["hash"]} and d["sigs"] == {}
    anchor = open(os.path.join(folder, R.ANCHOR)).read()
    assert f"ARENA_TRUST_GENESIS_HASH={out['ledger_id']}" in anchor and f"ARENA_TRUST_GOD_PUB={god.pub}" in anchor
    steps = [json.loads(x)["step"] for x in open(os.path.join(folder, R.LOG))]
    assert steps == ["keys-made", "request-written", "signatures-taken", "sealed", "request-written", "signatures-taken", "rotated",
                     "first-key-gone", "anchor-written", "declaration-drafted"]


async def test_p8e3_the_log_holds_public_values_only(settings, tmp_path, captured):
    out, folder, _ = await ceremony(settings, tmp_path, Identity.generate())
    log = open(os.path.join(folder, R.LOG), "rb").read()
    assert not any(k.private_hex().encode() in log for k in captured)


async def test_p8a3_a_wrong_signature_file_is_set_aside_and_nothing_is_written(settings, tmp_path, captured):
    god, other = Identity.generate(), Identity.generate()
    forged = lambda req, sig: dict(sig, sigs={"genesis": other.sign(req["items"][0]["payload"])})
    out, folder, _ = await ceremony(settings, tmp_path, god, tamper={1: forged})
    assert out["ok"] and glob.glob(os.path.join(folder, R.ROUNDS, "round-1.signatures-bad.json.refused"))
    steps = [json.loads(x)["step"] for x in open(os.path.join(folder, R.LOG))]
    assert steps[:4] == ["keys-made", "request-written", "signatures-refused", "signatures-taken"]
    assert [e["type"] for e in JsonlStore(os.path.join(folder, R.LEDGER)).load()] == ["genesis", "key_rotate"]


async def test_p8c1_a_round_never_signed_stops_the_ceremony_and_its_folder_is_thrown_away(settings, tmp_path, captured):
    god = Identity.generate()
    folder = str(tmp_path / "c")
    signer = asyncio.create_task(offline(folder, god, rounds=1))  # signs entry 0, never the handover
    with pytest.raises(R.Aborted, match="start again"):
        await R.run(fast(settings, ceremony_timeout_sec=0.3), god.pub, folder, [Identity.generate().pub, Identity.generate().pub],
                    say=lambda _: None)
    await signer
    assert [e["type"] for e in JsonlStore(os.path.join(folder, R.LEDGER)).load()] == ["genesis"]
    assert not os.path.exists(os.path.join(folder, R.RECORDER_KEY))  # no recorder key anywhere: nobody can seal on
    with pytest.raises(R.Aborted, match="one ceremony per folder"):
        await R.run(fast(settings), god.pub, folder, [Identity.generate().pub, Identity.generate().pub], say=lambda _: None)


async def test_the_witnesses_are_named_before_anything_happens(settings, tmp_path):
    with pytest.raises(R.Aborted, match="at least 2"):
        await R.run(fast(settings), Identity.generate().pub, str(tmp_path / "c"), [Identity.generate().pub], say=lambda _: None)
    assert not os.path.exists(tmp_path / "c" / R.LEDGER) and not os.path.exists(tmp_path / "c" / R.BROKER_KEY)


async def test_p8b3_the_god_key_handed_over_with_both_god_keys_signing_offline(settings, tmp_path, captured):
    from arena.ceremony import rotate
    god, new = Identity.generate(), Identity.generate()
    out, folder, _ = await ceremony(settings, tmp_path, god)
    r = rotate.god_request(fast(settings), folder, new.pub)
    req = json.load(open(r["request"]))
    assert req["round"] == 3 and req["items"][0]["signers"] == [god.pub, new.pub]
    assert "still needs" in (await rotate.god_apply(fast(settings), folder, req, [F.sign(req, god)]))["error"]
    done = await rotate.god_apply(fast(settings), folder, req, [F.sign(req, god), F.sign(req, new)])
    assert done["ok"] and open(os.path.join(folder, "god.pub")).read().strip() == new.pub
    raw = JsonlStore(os.path.join(folder, R.LEDGER)).load()
    assert current_keys(raw)["god"] == new.pub and audit_chain(raw) == "ok"


async def test_p8b1_the_operating_key_handed_over_later_leaves_no_old_key_file(settings, tmp_path, captured):
    from arena.ceremony import rotate
    god = Identity.generate()
    out, folder, _ = await ceremony(settings, tmp_path, god)
    r = rotate.recorder_request(fast(settings), folder)
    req = json.load(open(r["request"]))
    other = F.sign(dict(req, made_at=0.0), god)  # a signature for a different request
    assert "another request" in (await rotate.recorder_apply(fast(settings), folder, req, [other]))["error"]
    done = await rotate.recorder_apply(fast(settings), folder, req, [F.sign(req, god)])
    assert done["ok"] and done["old"] == out["recorder"] and done["new"] == r["new"]
    assert Identity.load(os.path.join(folder, R.RECORDER_KEY)).pub == r["new"]
    assert sorted(f for f in os.listdir(folder) if f.endswith(".key")) == [R.BROKER_KEY, R.OBSERVER_KEY, R.RECORDER_KEY]


async def test_p8d4_the_observer_key_approves_nothing(settings, tmp_path, captured):
    god = Identity.generate()
    out, folder, _ = await ceremony(settings, tmp_path, god)
    observer = Identity.load(os.path.join(folder, R.OBSERVER_KEY))
    svc = RecorderService.build(fast(settings), Identity.load(os.path.join(folder, R.RECORDER_KEY)), JsonlStore(os.path.join(folder, R.LEDGER)))
    nxt = Identity.generate()
    p = dict(svc.rotation_request("recorder", nxt.pub), god=observer.pub)
    r = await svc.rotate_key(nxt, p, observer.sign(p))
    assert not r["ok"] and "not the current god key" in r["error"]
    g = svc.rotation_request("god", observer.pub)
    r = await svc.record("key_rotate", dict(g, old=observer.pub), {observer.pub: observer.sign(dict(g, old=observer.pub))})
    assert not r["ok"]
    svc.readers = {observer.pub}  # what arena.genesis does with the observer key: it may read the whole ledger, nothing more
    assert svc.read_chain(observer.pub)["ok"] and not svc.read_chain(god.pub)["ok"]
