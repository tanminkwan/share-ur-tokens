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

    def wait_up(self, url, timeout=15, path="/health"):
        end = time.time() + timeout
        while time.time() < end:
            if self.p.poll() is not None:
                raise RuntimeError(self.p.stdout.read().decode())
            try:
                if httpx.get(url + path, timeout=1).status_code == 200:
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
    env = make_env(tmp_path, ARENA_BROKER_PORT=port, ARENA_BROKER_OWNER_PUB=owner.pub, ARENA_BROKER_NAME="D", ARENA_BROKER_GROUP_ID="g-closed")
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


async def test_p4e3_recorder_process_serves_track_records(tmp_path, procs):
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = make_env(tmp_path, ARENA_RECORDER_PORT=port)
    start(procs, "arena.recorder", env, tmp_path, url)
    R, cast = RecorderClient(url, Settings.load(env=env, dotenv_path=None)), Cast()
    for e in (cast.event(approvers=[cast.approver]), cast.contract(), cast.contract(role="keeper", contractor=cast.keeper, nonce="k")):
        assert (await R.record(*e))["ok"]
    t = await R.track(cast.judge.pub)
    assert t["ok"] and t["track"]["roles"] == {"judge": 1}
    assert (await R.track(cast.approver.pub))["track"]["approvals"] == 1


async def test_p5a18_genesis_process_god_creates_broker_and_recorder(tmp_path, procs):
    """python -m arena.genesis: god creates the genesis broker and recorder, signs entry 0; newcomers join; a restart continues"""
    from arena.a2a import A2ATransport
    from arena.signing import sign_message
    ports = {k: free_port() for k in ("broker", "rec", "api", "god")}
    viewer = Identity.generate()
    env = make_env(tmp_path, ARENA_GENESIS_DIR=str(tmp_path / "genesis"), ARENA_GENESIS_BROKER_PORT=ports["broker"],
                   ARENA_GENESIS_RECORDER_PORT=ports["rec"], ARENA_GENESIS_RECORDER_API_PORT=ports["api"], ARENA_GENESIS_GOD_PORT=ports["god"],
                   ARENA_GOD_VIEWERS=viewer.pub, ARENA_RECORDER_REQUIRE_GROUP="true", ARENA_GOD_CACHE_SEC="0")
    burl, gurl = f"http://127.0.0.1:{ports['broker']}", f"http://127.0.0.1:{ports['god']}"
    p = Proc("arena.genesis", env, tmp_path)
    procs.append(p)
    p.wait_up(burl)
    p.wait_up(gurl, path="/.well-known/agent-card.json")
    s = Settings.load(env=env, dotenv_path=None)
    B, t = BrokerClient(burl, s), A2ATransport(s)
    assert (await B.health())["group_id"] == "public" and (await B.health())["closed"] is False
    rec_hit = (await B.find("기록", role="record"))["peers"][0]
    R = RecorderClient(rec_hit["recorder_url"], s)
    snap = (await t.call(gurl, dict({"op": "god_snapshot"}, **sign_message(viewer, "god_snapshot"))))["snapshot"]
    god_pub = snap["stats"]["genesis"]["god"]
    assert snap["stats"]["entries"] == 1 and snap["stats"]["by_type"] == {"genesis": 1} and snap["integrity"]["agree"]
    assert snap["stats"]["genesis"]["recorder"] == rec_hit["pub"] and snap["stats"]["genesis"]["broker"] == (await B.health())["pub"]
    # a newcomer founds its own group and records in both groups
    me, cast = Identity.generate(), Cast()
    g = {"group_id": "g-new", "founder": me.pub, "closed": False, "brokers": []}
    assert (await R.record("group", g, {me.pub: me.sign(g)}))["ok"]
    cast.group = "public"
    assert (await R.record(*cast.publish(ev=None)))["ok"]
    cast.group = "g-new"
    assert (await R.record(*cast.publish(content="in my group", ev=None)))["ok"]
    cast.group = "g-nobody-founded"
    assert (await R.record(*cast.publish(content="nowhere", ev=None)))["error"] == "unknown group: g-nobody-founded"
    # restart: same god, same chain, no second genesis
    p.stop()
    p2 = Proc("arena.genesis", env, tmp_path)
    procs.append(p2)
    p2.wait_up(gurl, path="/.well-known/agent-card.json")
    snap = (await t.call(gurl, dict({"op": "god_snapshot"}, **sign_message(viewer, "god_snapshot"))))["snapshot"]
    assert snap["stats"]["genesis"]["god"] == god_pub and snap["stats"]["by_type"] == {"genesis": 1, "group": 1, "publish": 2}
    assert snap["stats"]["by_group"] == {"public": 2, "g-new": 2} and snap["integrity"]["agree"]
    assert [x["group_id"] for x in snap["stats"]["groups"]] == ["public", "g-new"]


async def test_p5c21_broker_process_keeps_state_across_restart(tmp_path, procs):
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = make_env(tmp_path, ARENA_BROKER_PORT=port, ARENA_BROKER_STATE_FILE=str(tmp_path / "broker-state.json"))
    start(procs, "arena.broker", env, tmp_path, url)
    s = Settings.load(env=env, dotenv_path=None)
    B, me, issuer = BrokerClient(url, s), Identity.generate(), Identity.generate()
    assert (await B.advertise(me, profile("http://me", "기록 보관", offers=["record"], now=time.time())))["ok"]
    assert (await B.post_notice(issuer, notice(issuer, "keep", now=time.time())))["ok"]
    pub_before = (await B.health())["pub"]
    procs[-1].stop()
    start(procs, "arena.broker", env, tmp_path, url)
    assert (await B.health())["pub"] == pub_before and (await B.health())["profiles"] == 1
    assert [p["pub"] for p in (await B.find("기록", role="record"))["peers"]] == [me.pub]
    assert [n["notice_id"] for n in (await B.list_notices(me))["notices"]] == ["keep"]
