"""Platform acceptance (dev/acceptance-rps.md): app-free rock-paper-scissors. The ecosystem begins with god's genesis
(a separate process). The host gets only the natural-language rules and a one-line instruction; every peer's basic
assistant runs the event with generic tools. The test never steps in: it waits for the close and judges the ledger.
No game rules in this file except the checker (who should have won), which reads the ledger only."""
import asyncio
import pathlib
import time

import pytest

from arena.a2a import A2ATransport
from arena.broker.client import BrokerClient
from arena.crypto import Identity, h
from arena.events import EventLog
from arena.ledger import audit_chain
from arena.llm import build_llm
from arena.peer.area import LocalFolderArea
from arena.peer.assistant import EventAssistant, commit_hash
from arena.peer.node import Peer, PeerConfig
from arena.recorder.client import RecorderClient
from arena.serve import serve_background
from tests.conftest import make_env
from tests.fakes import FakeOwner
from tests.test_processes import Proc, free_port

ROOT = pathlib.Path(__file__).resolve().parents[2]
RULES = (ROOT / "dev" / "acceptance-rps-rules.md").read_text(encoding="utf-8")
POLICY = {"roles": ["player"], "attest_roles": {"match": "player", "forfeit": "issuer", "ranking": "issuer"},
          "reveal_values": ["가위", "바위", "보"],  # event data, like the roles: the values a move may take
          "assigned_kinds": ["match"], "attest_kinds": ["match", "forfeit", "ranking"]}  # matches only by the assigned pair
INSTRUCTION = "규칙에 따라 이 대회를 끝까지 진행하라. 참가 신청이 오면 player 계약을 맺고, 선수가 3명이 되면 대진표를 만들어 보내라."
N_PLAYERS, TIMEOUT = 3, 1500  # run 10: three matches with drawn rounds and busy-service pauses did not fit in 900s


class Counting:
    def __init__(self, inner, me, log):
        self.inner, self.me, self.log = inner, me, log

    async def call(self, url, msg, timeout=None, meta=None):
        self.log.append((self.me, url, msg.get("op"), (meta or {}).get("group_id"), (meta or {}).get("event_id")))
        return await self.inner.call(url, msg, timeout, meta)


# ---- the checker: judges only what is on the ledger ----
BEATS = {"가위": "보", "바위": "가위", "보": "바위"}


def expected_winner(r, a, b):
    ma, mb = r["a"]["value"], r["b"]["value"]
    if ma == mb:
        return ""
    return a if BEATS.get(ma) == mb else b


def pen(pub):
    from arena.config import Settings
    s = Settings.load(env={}, dotenv_path=None)
    return s.pen_name_prefix + pub[:s.pen_name_len]


def ranking_from_ledger(chain, ev, players):
    rec = {p: {"pub": p, "wins": 0, "games": 0} for p in players}
    for e in chain:
        p = e["payload"]
        if e["type"] == "attest" and p.get("event_id") == ev and p["kind"] in ("match", "forfeit"):
            for x in (p["value"]["a"], p["value"]["b"]):
                rec[x]["games"] += 1
            if p["value"]["winner"]:
                rec[p["value"]["winner"]]["wins"] += 1
    for r in rec.values():
        r["rate"] = round(r["wins"] / r["games"], 4) if r["games"] else 0.0
    return sorted(rec.values(), key=lambda r: (-r["rate"], -r["wins"], pen(r["pub"])))


async def start_world(live, tmp):
    procs, servers, msgs = [], [], []
    ports = {k: free_port() for k in ("broker", "rec", "api", "god")}
    reader = Identity.generate()
    genv = make_env(tmp, ARENA_GENESIS_DIR=str(tmp / "genesis"), ARENA_GENESIS_BROKER_PORT=ports["broker"], ARENA_GENESIS_RECORDER_PORT=ports["rec"],
                    ARENA_GENESIS_RECORDER_API_PORT=ports["api"], ARENA_GENESIS_GOD_PORT=ports["god"], ARENA_RECORDER_REQUIRE_GROUP="true",
                    ARENA_RECORDER_READERS=reader.pub)
    g = Proc("arena.genesis", genv, tmp)
    procs.append(g)
    g.wait_up(f"http://127.0.0.1:{ports['god']}", path="/.well-known/agent-card.json")
    burl = f"http://127.0.0.1:{ports['broker']}"
    log, llm, base = EventLog(echo=True), build_llm(live), A2ATransport(live)
    peers = {}
    for name, yes in [("host", True)] + [(f"p{i}", i < N_PLAYERS) for i in range(N_PLAYERS + 1)]:
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        (tmp / name).mkdir()
        (tmp / name / "notes.md").write_text(f"- {'대회를 여는 peer' if name == 'host' else '친선 대회를 좋아하는 사원'}\n", encoding="utf-8")
        owner = FakeOwner(yes=yes, why="친선 대회라 참가한다" if yes else "이번에는 쉬겠다")
        p = Peer(Identity.generate(), live, PeerConfig(url=url, labels=["소속:삼성SDS"]), LocalFolderArea(str(tmp / name), live), owner, llm,
                 Counting(base, url, msgs), log, brokers={"public": BrokerClient(burl, live)}, apps=[EventAssistant(live)])
        servers.append(await serve_background(p.a2a_app(), "127.0.0.1", port))
        await p.advertise()
        peers[name] = p
    return procs, servers, msgs, peers, reader, log


async def test_rps_app_free_acceptance(live, tmp_path):
    import dataclasses
    live = dataclasses.replace(live, assistant_idle_sec=30.0)  # a stalled agent is woken after 30s (then 60, 120, ...)
    procs, servers, msgs, peers, reader, log = await start_world(live, tmp_path)
    host, players = peers["host"], [peers[f"p{i}"] for i in range(N_PLAYERS + 1)]
    try:
        t0 = time.time()
        ev = await host.app(EventAssistant).host_event(host.ctx(EventAssistant), title="peer 가위바위보 대회", kind="가위바위보", rules=RULES, policy=POLICY,
                                                       instruction=INSTRUCTION)
        await host.start()  # the host's assistant checks itself when its event goes quiet
        for p in players:
            await p.start()  # each player's event router watches the board and hands the event to its assistant
        rec_url = host.app(EventAssistant).events[ev].recorder_url
        R = RecorderClient(rec_url, live)
        chain = []
        while time.time() - t0 < TIMEOUT:
            await asyncio.sleep(3)
            chain = (await R.read_chain(reader))["chain"]
            if any(e["type"] == "close" and e["payload"]["event_id"] == ev for e in chain):
                break
        elapsed = round(time.time() - t0, 1)
        mine = [e for e in chain if e["payload"].get("event_id") == ev]
        print(f"\nelapsed {elapsed}s, entries {len(chain)}:", [e["type"] for e in mine])
        # RPS-6 the event closed (everything else depends on this)
        close = [e for e in mine if e["type"] == "close"]
        assert close, "the event did not close in time"
        # genesis and rules
        assert chain[0]["type"] == "genesis"
        decl = next(e for e in mine if e["type"] == "event")["payload"]
        assert decl["rules_hash"] == h(RULES.encode())
        # RPS-1 people decided; contracts carry the rules hash; the decliner has none
        contracts = [e["payload"] for e in mine if e["type"] == "contract"]
        player_pubs = sorted(c["contractor"] for c in contracts)
        assert len(player_pubs) == N_PLAYERS and players[N_PLAYERS].identity.pub not in player_pubs
        assert all(c["rules_hash"] == decl["rules_hash"] and c["role"] == "player" for c in contracts)
        # RPS-3, RPS-4 every match co-signed; every move committed before it was shown; winner right
        published = {e["payload"]["content_hash"]: e for e in mine if e["type"] == "publish"}
        matches = [e for e in mine if e["type"] == "attest" and e["payload"]["kind"] == "match"]
        forfeits = [e for e in mine if e["type"] == "attest" and e["payload"]["kind"] == "forfeit"]
        assert len(matches) + len(forfeits) == N_PLAYERS * (N_PLAYERS - 1) // 2
        for m in matches:
            p, v = m["payload"], m["payload"]["value"]
            assert set(m["sigs"]) == set(p["parties"]) == {v["a"], v["b"]}
            for r in v["rounds"]:
                for side in ("a", "b"):
                    rec = r[side]  # the reveal record exactly as the platform produced it
                    pub_e = next(e for e in mine if e["hash"] == rec["publish_hash"])
                    assert pub_e["payload"]["author"] == rec["author"] == v[side]
                    assert pub_e["payload"]["content_hash"] == commit_hash(rec["label"], rec["value"], rec["salt"], rec["author"])
            assert v["winner"] == expected_winner(v["rounds"][-1], v["a"], v["b"])
        # RPS-2 games went between the players only
        player_urls = {pp.config.url for pp in players}
        game = [m for m in msgs if m[2] in ("event_message", "attest_request", "attest_signature") and m[0] in player_urls and m[1] in player_urls]
        assert len(game) >= 4 * len(matches)
        assert all(m[3] == "public" and m[4] == ev for m in game)  # every game message carried its group and event in the head
        assert not [m for m in msgs if m[0] == host.config.url and m[2] == "attest_request"]
        # RPS-5 the notarized ranking equals the ranking recomputed from the ledger
        ranking = next(e for e in mine if e["type"] == "attest" and e["payload"]["kind"] == "ranking")
        assert ranking["payload"]["parties"] == [host.identity.pub]
        mine_rank = ranking_from_ledger(chain, ev, player_pubs)
        print("notarized:", ranking["payload"]["value"]["ranking"])
        print("recomputed:", mine_rank)
        assert [r["pub"] for r in ranking["payload"]["value"]["ranking"]] == [r["pub"] for r in mine_rank]
        assert [(r["wins"], r["games"]) for r in ranking["payload"]["value"]["ranking"]] == [(r["wins"], r["games"]) for r in mine_rank]
        assert close[0]["payload"]["result_hash"] == ranking["hash"]
        assert audit_chain(chain) == "ok"
        assert (await host.brokers["public"].list_notices(host.identity))["notices"] == []
    finally:
        for s in servers:
            s.should_exit = True
        for p in procs:
            p.stop()
