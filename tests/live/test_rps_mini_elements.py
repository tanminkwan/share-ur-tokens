"""The same two-peer one-round game with built-in elements on (P6-V3): sealed rounds keep the reveal order by ledger rule,
and a judging API peer (event-specific code, outside the platform) computes and records the result. Compared with
test_rps_mini.py (no elements) by scripts/compare_elements.py: platform guarantees, completion, time, LLM calls and tokens."""
import asyncio
import dataclasses
import json
import pathlib
import time

from arena.crypto import Identity
from arena.events import EventLog
from arena.ledger import audit_chain
from arena.llm import NoLLM
from arena.peer.area import LocalFolderArea
from arena.peer.assistant import EventAssistant
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.peer.service import ServiceApp
from arena.recorder.client import RecorderClient
from arena.serve import serve_background
from tests.live.test_rps_acceptance import Counting, start_world
from tests.service_samples.rps_referee import BEATS
from tests.test_processes import free_port

ROOT = pathlib.Path(__file__).resolve().parents[2]
RULES = (ROOT / "dev" / "acceptance-rps-mini-elements-rules.md").read_text(encoding="utf-8")
POLICY = {"roles": ["player", "referee"], "attest_roles": {"match": "referee"}, "attest_kinds": ["match"], "reveal_values": ["가위", "바위", "보"]}
REFEREE = {"name": "rps-referee", "version": "1.0", "app_id": "7e1d4c2b-9a3f-4b6e-8d1c-5f2a0b9e3c47", "description": "가위바위보 판정 peer",
           "roles": ["referee"], "ops": {"judge": {"python": "tests.service_samples.rps_referee:judge", "description": "두 공개로 승패를 기록",
                                                    "record": {"kind": "match"}}}}
TIMEOUT = 600


async def test_rps_mini_with_elements(live, tmp_path):
    live = dataclasses.replace(live, assistant_idle_sec=30.0)
    procs, servers, msgs, peers, reader, log = await start_world(live, tmp_path, n_players=2)
    host, players = peers["host"], [peers[f"p{i}"] for i in range(3)]
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    (tmp_path / "referee").mkdir()
    (tmp_path / "referee" / "notes.md").write_text("- 가위바위보 판정 peer\n", encoding="utf-8")
    referee = Peer(Identity.generate(), live, PeerConfig(url=url), LocalFolderArea(str(tmp_path / "referee"), live), NoOwner(), NoLLM(),
                   Counting(host.transport.inner, url, msgs), log, brokers=host.brokers, apps=[ServiceApp(live, REFEREE)])
    servers.append(await serve_background(referee.a2a_app(), "127.0.0.1", port))
    await referee.advertise()
    try:
        t0 = time.time()
        ev = await host.app(EventAssistant).host_event(
            host.ctx(EventAssistant), title="peer 가위바위보 한 판(요소)", kind="가위바위보", rules=RULES, policy=POLICY, elements={"sealed": {}},
            instruction=f"규칙에 따라 이 한 판을 끝까지 진행하라. 판정 peer는 {referee.pen}이다. 선수 2명과 player 계약, 판정 peer와 referee 계약을 맺고 m1을 배정하라.")
        await host.start()
        for p in players:
            await p.start()
        R = RecorderClient(host.app(EventAssistant).events[ev].recorder_url, live)
        chain = []
        while time.time() - t0 < TIMEOUT:
            await asyncio.sleep(3)
            chain = (await R.read_chain(reader))["chain"]
            if any(e["type"] == "close" and e["payload"]["event_id"] == ev for e in chain):
                break
        elapsed = round(time.time() - t0, 1)
        mine = [e for e in chain if e["payload"].get("event_id") == ev]
        print(f"\nelapsed {elapsed}s, entries:", [e["type"] for e in mine])
        print("usage:", json.dumps(host.llm.meter.total()))
        close = [e for e in mine if e["type"] == "close"]
        assert close, "the event did not close in time"
        match = next(e for e in mine if e["type"] == "attest" and e["payload"]["kind"] == "match")
        assert match["payload"]["parties"] == [referee.identity.pub] and close[0]["payload"]["result_hash"] == match["hash"]
        r = match["payload"]["value"]["result"]
        right = "" if r["moves"]["a"] == r["moves"]["b"] else r["a"] if BEATS[r["moves"]["a"]] == r["moves"]["b"] else r["b"]
        assert r["winner"] == right
        # the sealed order held: every reveal came after both registrations of its label
        regs = [e["seq"] for e in mine if e["type"] == "publish" and e["payload"].get("label") == "m1"]
        reveals = [e["seq"] for e in mine if e["type"] == "reveal" and e["payload"].get("label") == "m1"]
        assert len(regs) == 2 and all(x > max(regs) for x in reveals)
        assert audit_chain(chain) == "ok"
        print(f"moves: a={r['moves']['a']} b={r['moves']['b']}; winner recorded by the referee {r['winner'][:6] or '(draw)'}; "
              f"LLM judgement error: no (the referee computes it); messages: {len(msgs)}")
    finally:
        for s in servers:
            s.should_exit = True
        for p in procs:
            p.stop()
