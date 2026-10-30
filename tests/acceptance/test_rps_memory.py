"""P5-C1 ~ C6 (RPS-1 ~ RPS-6) in one process: the ecosystem begins with god's genesis, then a peer holds a
rock-paper-scissors event purely over A2A, the ranking is notarized and the event closes."""
import pytest

from arena.ledger import audit_chain
from tests.acceptance.rps import KIND, RpsPlayer, ranking_from_chain
from tests.acceptance.world import MemoryEcosystem


async def run(eco):
    await eco.genesis()
    rec_hit = (await eco.host.brokers["public"].find("기록자", role="record", identity=eco.host.identity))["peers"][0]
    ev = await eco.host_app.open(eco.host, rec_hit)
    for p in eco.players:
        await p.app(RpsPlayer).consider_notices(p)
    acks = await eco.host_app.schedule(eco.host)
    out = await eco.host_app.finish(eco.host, timeout=10)
    return ev, acks, out


@pytest.fixture
async def done(tmp_path, settings):
    eco = MemoryEcosystem(tmp_path, settings, n_players=4, declining=1)
    ev, acks, out = await run(eco)
    return eco, ev, acks, out


def entries(eco, ev, kind=None):
    return [e for e in eco.svc.ledger.chain if e["payload"].get("event_id") == ev and (kind is None or e["type"] == kind)]


async def test_rps1_people_decide_participation(done):
    eco, ev, acks, out = done
    players = [e["payload"]["contractor"] for e in entries(eco, ev, "contract")]
    assert len(players) == 4 and eco.players[4].identity.pub not in players  # the one whose person declined has no contract
    decisions = [e["text"] for e in eco.log.tail(500) if e["kind"] == "decide"]
    assert sum("참가 -" in d for d in decisions) == 4 and sum("불참" in d for d in decisions) == 1
    assert eco.svc.ledger.chain[0]["type"] == "genesis" and eco.svc.ledger.chain[0]["payload"]["god"] == eco.god_id.pub


async def test_rps2_games_go_only_between_the_two_players(done):
    eco, ev, acks, out = done
    game = [(f, to, op) for f, to, op in eco.msgs if op and op.startswith("rps_")]
    assert game and all(f not in ("mem://host",) and to not in ("mem://host",) for f, to, _ in game)
    assert {op for _, _, op in game} == {"rps_challenge", "rps_reveal", "rps_sign"}
    assert len(out["ranking"]) == 4 and len(eco.host_app.results) == 6  # round robin of four: six matches


async def test_rps3_every_move_was_committed_before_it_was_shown(done):
    eco, ev, acks, out = done
    from tests.acceptance.rps import commit_of
    published = {e["payload"]["content_hash"]: e["payload"]["author"] for e in entries(eco, ev, "publish")}
    for e in entries(eco, ev, "attest"):
        if e["payload"]["kind"] != "match":
            continue
        v, mid = e["payload"]["value"], e["payload"]["subject"]
        for r in v["rounds"]:
            assert published[r["commit_a"]] == v["a"] and published[r["commit_b"]] == v["b"]
            assert commit_of(mid, r["round"], r["move_a"], r["salt_a"], v["a"]) == r["commit_a"]
            assert commit_of(mid, r["round"], r["move_b"], r["salt_b"], v["b"]) == r["commit_b"]


async def test_rps4_results_are_co_signed_and_one_sided_ones_refused(done):
    eco, ev, acks, out = done
    for e in entries(eco, ev, "attest"):
        if e["payload"]["kind"] == "match":
            assert set(e["sigs"]) == set(e["payload"]["parties"]) and len(e["payload"]["parties"]) == 2
    a, b = eco.players[0], eco.players[1]
    p = {"event_id": "other", "kind": "match", "subject": "x", "value": {}, "parties": [a.identity.pub, b.identity.pub], "nonce": "n", "group_id": "public"}
    r = await eco.svc.record("attest", p, {a.identity.pub: a.sign(p)})
    assert r["ok"] is False and r["error"].startswith("missing/invalid signature")


async def test_rps5_god_recomputes_the_same_ranking_from_the_ledger_alone(done):
    eco, ev, acks, out = done
    from arena.peer.god_role import GodRole
    chain = (await eco.god.recorder("mem://recorder/api").read_chain(eco.god.identity))["chain"]
    assert ranking_from_chain(chain, ev) == out["ranking"]
    notarized = next(e for e in entries(eco, ev, "attest") if e["payload"]["kind"] == "ranking")
    assert notarized["payload"]["value"]["ranking"] == out["ranking"] and notarized["payload"]["parties"] == [eco.host.identity.pub]
    snap = await eco.god.app(GodRole).snapshot(eco.god)
    assert snap["integrity"]["agree"] and snap["stats"]["attests"]["match"] == 6 and snap["stats"]["closed"][0]["event_id"] == ev
    assert audit_chain(chain) == "ok"


async def test_rps6_the_event_is_closed_and_nothing_more_enters(done):
    eco, ev, acks, out = done
    close = entries(eco, ev, "close")
    assert len(close) == 1 and close[0]["payload"]["result_hash"] == out["ranking_hash"]
    a = eco.players[0]
    p = {"event_id": ev, "kind": "match", "subject": "late", "value": {}, "parties": [a.identity.pub], "nonce": "late", "group_id": "public"}
    assert (await eco.svc.record("attest", p, {a.identity.pub: a.sign(p)}))["error"] == "event closed"
    assert (await a.brokers["public"].list_notices(a.identity))["notices"] == []  # the notice is closed too


async def test_rps3_a_cheater_forfeits(tmp_path, settings):
    eco = MemoryEcosystem(tmp_path, settings, n_players=3, declining=0, cheaters=(0,))
    ev, acks, out = await run(eco)
    cheater = eco.players[0].identity.pub
    forfeits = [e for e in entries(eco, ev, "attest") if e["payload"]["kind"] == "forfeit"]
    assert forfeits and all(f["payload"]["value"]["offender"] == cheater and f["payload"]["parties"] == [eco.host.identity.pub] for f in forfeits)
    games = [m for m in eco.host_app.matches if cheater in (m["a"], m["b"])]
    assert len(forfeits) == len(games) == 2
    row = next(r for r in out["ranking"] if r["pub"] == cheater)
    assert row["wins"] == 0 and out["ranking"][-1]["pub"] == cheater
    chain = (await eco.god.recorder("mem://recorder/api").read_chain(eco.god.identity))["chain"]
    assert ranking_from_chain(chain, ev) == out["ranking"]
