"""R3-8, R4-11, R6-1: real processes over real HTTP. Two brokers that share notices + one recorder, restarted once."""
import os
import pathlib
import socket
import subprocess
import sys
import time

import httpx
import pytest

from arena.broker.client import BrokerClient
from arena.recorder.client import RecorderClient
from arena.config import Settings
from arena.crypto import Identity
from tests.conftest import make_env
from tests.test_broker_service import notice, profile
from tests.test_ledger import Cast

ROOT = pathlib.Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Proc:
    def __init__(self, module, env, cwd):
        full = dict(os.environ, PYTHONPATH=str(ROOT), **env)
        self.p = subprocess.Popen([sys.executable, "-m", module], env=full, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def wait_up(self, url, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if self.p.poll() is not None:
                raise RuntimeError(self.p.stdout.read().decode())
            try:
                if httpx.get(url + "/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.1)
        raise TimeoutError(url)

    def stop(self):
        self.p.terminate()
        try:
            self.p.wait(5)
        except subprocess.TimeoutExpired:
            self.p.kill()


@pytest.fixture
def procs():
    started = []
    yield started
    for p in started:
        p.stop()


def start(procs, module, env, cwd, url):
    p = Proc(module, env, cwd)
    procs.append(p)
    p.wait_up(url)
    return p


async def test_r4_11_two_broker_processes_share_notices(tmp_path, procs):
    pa, pb = free_port(), free_port()
    ua, ub = f"http://127.0.0.1:{pa}", f"http://127.0.0.1:{pb}"
    base = make_env(tmp_path)
    start(procs, "arena.broker", dict(base, ARENA_BROKER_PORT=str(pa), ARENA_BROKER_NAME="A", ARENA_BROKER_NEIGHBORS=ub,
                                       ARENA_BROKER_KEY_FILE=str(tmp_path / "a.key")), tmp_path, ua)
    start(procs, "arena.broker", dict(base, ARENA_BROKER_PORT=str(pb), ARENA_BROKER_NAME="B", ARENA_BROKER_NEIGHBORS=ua,
                                       ARENA_BROKER_KEY_FILE=str(tmp_path / "b.key")), tmp_path, ub)
    s = Settings.load(env=base, dotenv_path=None)
    A, B = BrokerClient(ua, s), BrokerClient(ub, s)
    issuer, viewer, rec = Identity.generate(), Identity.generate(), Identity.generate()
    now = time.time()
    assert (await B.advertise(viewer, profile("http://v", "신입 온보딩", now=now)))["ok"]
    assert (await A.advertise(rec, profile("http://r", "감사 기록 보관", offers=["record"], now=now)))["ok"]
    assert (await A.post_notice(issuer, notice(issuer, now=now)))["ok"]
    assert [n["notice_id"] for n in (await B.list_notices(viewer))["notices"]] == ["call-1"]  # shared A -> B over HTTP
    found = await B.find("기록 보관", role="record")
    assert [(p["pub"], p["broker"]) for p in found["peers"]] == [(rec.pub, "A")]  # B asked A
    assert {p["broker"] for p in (await A.list_profiles())["profiles"]} == {"A", "B"}
    assert (await A.close_notice(issuer, "call-1"))["ok"]
    assert (await B.list_notices(viewer))["notices"] == []
    assert (await A.health())["name"] == "A" and (await B.health())["neighbors"] == [ua]
    procs[1].stop()  # B goes down: A still answers
    assert (await A.find("기록", role="record"))["ok"]


async def test_r4_11_closed_group_owner_from_settings(tmp_path, procs):
    owner, member = Identity.generate(), Identity.generate()
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = make_env(tmp_path, ARENA_BROKER_PORT=port, ARENA_BROKER_OWNER_PUB=owner.pub, ARENA_BROKER_NAME="D")
    start(procs, "arena.broker", env, tmp_path, url)
    D = BrokerClient(url, Settings.load(env=env, dotenv_path=None))
    assert (await D.health())["closed"] is True
    assert (await D.advertise(member, profile("http://m", "심사", now=time.time())))["ok"] is False
    assert (await D.grant(owner, member.pub, time.time() + 60))["ok"]
    assert (await D.advertise(member, profile("http://m", "심사", now=time.time())))["ok"]
    assert (await D.find("심사"))["ok"] is False
    assert len((await D.find("심사", identity=member))["peers"]) == 1


async def test_r3_8_recorder_process_persists_across_restart(tmp_path, procs):
    reader, cast = Identity.generate(), Cast()
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = make_env(tmp_path, ARENA_RECORDER_PORT=port, ARENA_RECORDER_READERS=reader.pub, ARENA_RECORDER_NAME="rec-1")
    s = Settings.load(env=env, dotenv_path=None)
    start(procs, "arena.recorder", env, tmp_path, url)
    C = RecorderClient(url, s)
    first = await C.health()
    assert first["name"] == "rec-1" and first["length"] == 0
    a = await C.record(*cast.publish(ev=None))
    b = await C.record(*cast.share())
    assert a["ok"] and b["ok"]
    assert (await C.read_chain(Identity.generate()))["ok"] is False
    procs[0].stop()
    start(procs, "arena.recorder", env, tmp_path, url)
    again = await C.health()
    assert again["pub"] == first["pub"]  # same recorder key
    assert again["length"] == 2 and again["head"] == b["hash"]  # same chain
    assert (await C.audit())["status"] == "ok"
    c = await C.record(*cast.publish(content="doc B", ev=None))
    assert c["ok"] and c["seq"] == 2
    chain = (await C.read_chain(reader))["chain"]
    assert [e["seq"] for e in chain] == [0, 1, 2]
    assert (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").count("\n") == 3


async def test_r2_12_recorder_process_refuses_tampered_file(tmp_path, procs):
    import json
    cast, port = Cast(), free_port()
    url = f"http://127.0.0.1:{port}"
    env = make_env(tmp_path, ARENA_RECORDER_PORT=port)
    start(procs, "arena.recorder", env, tmp_path, url)
    C = RecorderClient(url, Settings.load(env=env, dotenv_path=None))
    await C.record(*cast.publish(ev=None))
    procs[0].stop()
    f = tmp_path / "ledger.jsonl"
    e = json.loads(f.read_text(encoding="utf-8"))
    e["payload"]["author"] = Identity.generate().pub
    f.write_text(json.dumps(e, ensure_ascii=False) + "\n", encoding="utf-8")
    p = Proc("arena.recorder", env, tmp_path)
    procs.append(p)
    assert p.p.wait(15) != 0
    assert "TAMPERED at seq 0" in p.p.stdout.read().decode()
