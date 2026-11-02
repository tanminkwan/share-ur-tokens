"""P4-C: public track records on the recorder; summing several recorders; checking a requirement."""
import httpx
import pytest

from arena.config import Settings
from arena.crypto import Identity
from arena.ledger import MemoryStore
from arena.peer.track import meets, track_of
from arena.recorder.api import build_recorder_app
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from tests.conftest import make_env
from tests.test_ledger import Cast


@pytest.fixture
async def recs(settings):
    out = []
    for _ in range(2):
        cast = Cast()
        svc = RecorderService.build(settings, Identity.generate(), MemoryStore(), readers=[])
        out.append((svc, cast))
    return out


async def history(svc, cast, judge=None):
    if judge:
        cast.judge = judge
    for e in (cast.event(approvers=[cast.approver]), cast.contract(), cast.publish(), cast.share(consumer=cast.judge, nonce="s"),
              cast.feedback("score", score=7.0)):
        assert (await svc.record(*e))["ok"]


async def test_p4c1_track_endpoint_and_switch(recs, settings, tmp_path):
    svc, cast = recs[0]
    await history(svc, cast)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_recorder_app(svc)), base_url="http://r")
    t = (await http.get(f"/track/{cast.judge.pub}")).json()
    assert t == {"ok": True, "pub": cast.judge.pub, "track": {"published": 0, "received_by": 0, "verdicts_received": {}, "verdicts_given": {"score": 1},
                                                                "roles": {"judge": 1}, "events": 0, "approvals": 0,
                                                                "attested": {}, "closed": 0, "groups": 0, "revealed": 0, "codebooks": 0, "codebook_followers": 0}}
    nobody = (await http.get(f"/track/{Identity.generate().pub}")).json()
    assert nobody["track"]["roles"] == {} and nobody["track"]["published"] == 0
    assert "chain" not in str(t) and cast.author.pub not in str(t)  # no counterparties, no hashes
    off = RecorderService.build(Settings.load(env=make_env(tmp_path, ARENA_RECORDER_PUBLIC_TRACK="false"), dotenv_path=None),
                                Identity.generate(), MemoryStore(), readers=[])
    http2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_recorder_app(off)), base_url="http://r")
    assert (await http2.get(f"/track/{cast.judge.pub}")).status_code == 404


async def test_p4c2_track_of_sums_recorders_and_marks_failures(recs):
    (s1, c1), (s2, c2) = recs
    judge = Identity.generate()
    await history(s1, c1, judge=judge)
    await history(s2, c2, judge=judge)
    clients = {"mem://r1": InMemoryRecorderClient(s1), "mem://r2": InMemoryRecorderClient(s2)}

    class P:
        def recorder(self, url):
            if url not in clients:
                raise ConnectionError(url)
            return clients[url]
    t = await track_of(P(), judge.pub, ["mem://r1", "mem://r2", "mem://down"])
    assert t["roles"] == {"judge": 2} and t["verdicts_given"] == {"score": 2}
    assert t["sources"] == {"mem://r1": "ok", "mem://r2": "ok", "mem://down": "ConnectionError: mem://down"}


def test_p4c3_meets_compares_mechanically():
    t = {"published": 0, "received_by": 3, "verdicts_received": {}, "verdicts_given": {"review": 4}, "roles": {"review": 2}, "events": 0, "approvals": 0}
    assert meets(t, {"roles": {"review": 1}, "received_by": 2}) == (True, [])
    ok, missing = meets(t, {"roles": {"review": 3, "record": 1}, "approvals": 1})
    assert not ok and missing == ["roles.review 2/3", "roles.record 0/1", "approvals 0/1"]


async def test_p4c4_peer_remembers_recorders(tmp_path, settings):
    from tests.test_peer import broker as _b, make_peer  # noqa
    from arena.broker.neighbors import NoNeighbors
    from arena.broker.service import BrokerService
    from arena.search import BM25Searcher
    b = BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])
    s = Settings.load(env=make_env(tmp_path, ARENA_PEER_TRACK_RECORDERS="http://fixed:1"), dotenv_path=None)
    p = make_peer(tmp_path, s, b)
    p.recorder("http://used:2")
    assert p.known_recorders == ["http://fixed:1", "http://used:2"]
