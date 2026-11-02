"""Small-scale acceptance (user 2026-11-02: when errors keep coming, check the game procedure and observe from the
smallest scale): two peers, one round, app-free. The rules text (dev/acceptance-rps-mini-rules.md) drops what the full
league's procedure made the agents stumble on: no message steps (the ledger is the only truth), no fixed order between
the two players, no replay on a draw. Like the full test, the test never steps in and judges the ledger only; a wrong
win/loss call is reported as an LLM judgement error, not a platform failure (user 2026-10-31)."""
import asyncio
import dataclasses
import json
import pathlib
import time

from arena.ledger import audit_chain
from arena.peer.assistant import EventAssistant, commit_hash
from arena.recorder.client import RecorderClient
from tests.live.test_rps_acceptance import expected_winner, start_world

ROOT = pathlib.Path(__file__).resolve().parents[2]
RULES = (ROOT / "dev" / "acceptance-rps-mini-rules.md").read_text(encoding="utf-8")
POLICY = {"roles": ["player"], "attest_roles": {"match": "player"}, "attest_kinds": ["match"], "assigned_kinds": ["match"],
          "reveal_values": ["가위", "바위", "보"]}
INSTRUCTION = "규칙에 따라 이 한 판을 끝까지 진행하라. 참가 신청이 오면 player 계약을 맺고, 선수가 2명이 되면 m1을 배정하라."
TIMEOUT = 600


async def test_rps_mini_two_peers_one_round(live, tmp_path):
    live = dataclasses.replace(live, assistant_idle_sec=30.0)
    procs, servers, msgs, peers, reader, log = await start_world(live, tmp_path, n_players=2, decliner=False)
    host, players = peers["host"], [peers[f"p{i}"] for i in range(2)]  # the fewest peers: a host and two players
    try:
        t0 = time.time()
        ev = await host.app(EventAssistant).host_event(host.ctx(EventAssistant), title="peer 가위바위보 한 판", kind="가위바위보", rules=RULES,
                                                       policy=POLICY, instruction=INSTRUCTION)
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
        close = [e for e in mine if e["type"] == "close"]
        assert close, "the event did not close in time"
        contracts = [e["payload"] for e in mine if e["type"] == "contract"]
        assert len(contracts) == 2
        asg = [e["payload"] for e in mine if e["type"] == "assign"]
        assert len(asg) == 1 and sorted(asg[0]["subjects"]["m1"]) == sorted(c["contractor"] for c in contracts)
        matches = [e for e in mine if e["type"] == "attest" and e["payload"]["kind"] == "match"]
        assert len(matches) == 1
        m = matches[0]
        p, v = m["payload"], m["payload"]["value"]
        assert set(m["sigs"]) == set(p["parties"]) == {v["a"], v["b"]} == set(asg[0]["subjects"]["m1"])
        for side in ("a", "b"):
            rec = v["rounds"][-1][side]
            assert isinstance(rec, dict) and {"author", "label", "value", "salt", "publish_hash"} <= set(rec), "incomplete reveal record"
            reg = next(e for e in mine if e["hash"] == rec["publish_hash"])
            assert reg["payload"]["author"] == rec["author"] == v[side]
            assert reg["payload"]["content_hash"] == commit_hash(rec["label"], rec["value"], rec["salt"], rec["author"])
        assert close[0]["payload"]["result_hash"] == m["hash"]
        assert not [x for x in msgs if x[0] == host.config.url and x[2] == "attest_request"]
        assert audit_chain(chain) == "ok"
        right = expected_winner(v["rounds"][-1], v["a"], v["b"])
        print(f"moves: a={v['rounds'][-1]['a']['value']} b={v['rounds'][-1]['b']['value']}; winner recorded "
              f"{v['winner'][:6] or '(draw)'}, by the rules {right[:6] or '(draw)'}; "
              f"LLM judgement error: {'yes' if v['winner'] != right else 'no'}; messages: {len(msgs)}")
        print("usage:", json.dumps(host.llm.meter.total()))
    finally:
        for s in servers:
            s.should_exit = True
        for p in procs:
            p.stop()
