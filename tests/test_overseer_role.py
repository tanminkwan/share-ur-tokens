"""P3-C: the spectator overseer peer: reads the whole ledger with its allow-listed key, audits it, generic stats."""
import time

import pytest

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.events import EventLog
from arena.ledger import MemoryStore
from arena.llm import NoLLM
from arena.peer.area import LocalFolderArea
from arena.peer.node import Peer, PeerConfig
from arena.peer.overseer_role import OverseerRole
from arena.peer.owner import NoOwner
from arena.peer.record_role import RecordRole
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from arena.search import BM25Searcher
from arena.signing import sign_message
from arena.stats import ledger_stats
from tests.test_ledger import Cast


@pytest.fixture
async def setup(tmp_path, settings):
    viewer, ov_id, cast = Identity.generate(), Identity.generate(), Cast()
    broker = BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="open", neighbors=[])
    log, t = EventLog(echo=False), LocalTransport()
    svc = RecorderService.build(settings, cast.keeper, MemoryStore(), readers=[ov_id.pub])

    def make(name, ident, apps, summary):
        (tmp_path / name).mkdir()
        (tmp_path / name / "notes.md").write_text(f"- {summary}\n", encoding="utf-8")
        p = Peer(ident, settings, PeerConfig(url=f"mem://{name}"), LocalFolderArea(str(tmp_path / name), settings), NoOwner(), NoLLM(),
                 t, log, brokers={"open": InMemoryBrokerClient(broker)}, apps=apps)
        p.recorder_factory = lambda u: InMemoryRecorderClient(svc)
        return p
    rec = make("rec", cast.keeper, [RecordRole(svc, "mem://rec/recorder")], "기록 보관 담당")
    role = OverseerRole(settings, viewers=[viewer.pub])
    ov = make("ov", ov_id, [role], "관전 peer")
    judge = make("judge", cast.judge, [], "평가 전문가")
    for p in (rec, ov, judge):
        await p.advertise()
    # a small generic history: approved event, roles, a published doc, shares, a scored verdict and a pick
    for e in (cast.event(approvers=[cast.approver]), cast.contract(role="keeper", contractor=cast.keeper, nonce="k"), cast.contract(),
              cast.publish(), cast.share(consumer=cast.judge, nonce="s1"), cast.share(consumer=cast.issuer, nonce="s2"),
              cast.feedback("score", score=8.0), cast.feedback("pick", evaluator=cast.issuer)):
        assert (await svc.record(*e))["ok"]
    return dict(role=role, ov=ov, svc=svc, cast=cast, viewer=viewer, judge=judge, rec=rec)


async def test_p3c1_p3c2_locates_reads_and_audits(setup):
    s = setup
    snap = await s["role"].snapshot(s["ov"])
    assert [r["recorder_url"] for r in s["role"].recorders] == ["mem://rec/recorder"]
    assert snap["integrity"]["agree"] is True and snap["integrity"]["recorders"][0]["status"] == "ok"
    s["svc"].ledger.chain[3]["payload"]["author"] = s["cast"].other.pub  # tamper with history behind everyone's back
    s["role"].invalidate()
    snap = await s["role"].snapshot(s["ov"])
    assert snap["integrity"]["agree"] is False and "TAMPERED at seq 3" in snap["integrity"]["recorders"][0]["status"]
    assert sum("변조" in e["text"] for e in s["ov"].log.tail(20)) == 1


def test_p3c3_generic_stats(setup):
    st = ledger_stats(setup["svc"].ledger.chain, top_flows=5)
    c = setup["cast"]
    assert st["entries"] == 8 and st["by_type"] == {"event": 1, "contract": 2, "publish": 1, "share": 2, "feedback": 2}
    assert st["events"] == [{"event_id": c.ev, "kind": "test", "issuer": c.issuer.pub, "approvers": [c.approver.pub]}]
    assert st["verdicts"] == {"score": {"count": 1, "avg": {"score": 8.0}}, "pick": {"count": 1, "avg": {}}}
    assert st["roles"] == {"keeper": 1, "judge": 1}
    assert st["signers"] == 5 and len(st["top_flows"]) == 2 and st["span_sec"] >= 0


async def test_p3c4_p3c5_per_peer_and_access_log(setup):
    s = setup
    snap = await s["role"].snapshot(s["ov"])
    by = {x["pub"]: x for x in snap["peers"]}
    j = by[s["cast"].judge.pub]
    assert j["strengths"] == "평가 전문가" and j["roles"] == {"judge": 1} and j["verdicts_given"] == {"score": 1}
    assert by[s["cast"].keeper.pub]["roles"] == {"keeper": 1} and by[s["cast"].keeper.pub]["group"] == "open"
    assert s["cast"].approver.pub in by and by[s["cast"].approver.pub]["approvals"] == 1  # no profile, still on record
    assert snap["access"][0]["granted"] is True


async def test_p3c6_snapshot_op_only_for_viewers_and_cached(setup, settings):
    s = setup
    r = await s["ov"].handle(dict({"op": "overseer_snapshot"}, **sign_message(s["viewer"], "overseer_snapshot")))
    assert r["ok"] and r["snapshot"]["stats"]["entries"] == 8
    r = await s["ov"].handle(dict({"op": "overseer_snapshot"}, **sign_message(Identity.generate(), "overseer_snapshot")))
    assert r == {"ok": False, "error": "not a viewer"}
    assert (await s["ov"].handle({"op": "overseer_snapshot"}))["ok"] is False
    a = await s["role"].snapshot(s["ov"])
    b = await s["role"].snapshot(s["ov"])
    assert a is b  # cached within ARENA_OVERSEER_CACHE_SEC


def test_p3c7_overseer_has_no_write_or_content_ops(setup):
    assert set(setup["ov"].skills()) == {"engage", "approve", "solicit", "overseer_snapshot"}  # platform ops + read-only snapshot
    assert setup["ov"].offers() == []
