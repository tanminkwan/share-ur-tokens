"""P3-D3, P3-D4: the advanced search peer with the real bge-m3 service."""
import time

from arena.a2a import A2ATransport
from arena.broker.client import BrokerClient
from arena.crypto import Identity
from arena.embedding import HttpEmbedder
from arena.search import BM25Searcher
from arena.signing import sign_message
from tests.conftest import make_env
from tests.test_processes import Proc, free_port

SDS = "소속:삼성SDS"
# the usual case: the target says what the query means in other words; no shared words with any document
QUERY = "새로 입사한 동료의 적응을 도와줄 사람"
TARGET = "신입 사원 온보딩 프로그램을 운영해 왔다"
DOCS = [TARGET, "서버 장애 복구와 운영 자동화 담당", "행사 예산과 공간을 잡는 총무 담당", "고객 제안과 수주 협상"]
# the trap: distractors share almost every surface word with the query (a known limit of dense vectors alone)
TRAP_QUERY = "새로 입사한 동료가 회사에 빨리 녹아들게 돕는 사람"
TRAP_DOCS = [TARGET, "회사 서버 장애가 나면 빨리 복구하는 사람", "회사 행사 예산과 공간을 빨리 잡아 주는 총무 담당", "고객 제안과 수주 협상"]


async def rank_both(settings, query, docs):
    bm25 = BM25Searcher().rank(query, docs)
    vec = await HttpEmbedder(settings).embed([query] + docs)
    cos = sorted(((i, sum(a * b for a, b in zip(vec[0], d))) for i, d in enumerate(vec[1:])), key=lambda x: -x[1])
    print("\nBM25:", [(docs[i][:12], s) for i, s in bm25])
    print("bge-m3:", [(docs[i][:12], round(s, 3)) for i, s in cos])
    return bm25, cos


async def test_p3d3_meaning_finds_the_paraphrase(live_embed):
    bm25, cos = await rank_both(live_embed, QUERY, DOCS)
    assert dict(bm25)[0] == 0  # BM25 cannot see the target at all
    assert cos[0][0] == 0  # the embedding puts it first


async def test_p3d3_known_limit_shared_words_trap(live_embed):
    """recorded limit: with distractors built from the query's own words, the target is near the top but not first.
    A reranker (bge-reranker-v2-m3) is the follow-up."""
    bm25, cos = await rank_both(live_embed, TRAP_QUERY, TRAP_DOCS)
    assert dict(bm25)[0] == 0
    assert 0 in [i for i, _ in cos[:2]]


async def test_p3d4_search_peer_process_answers_over_a2a(live_embed, tmp_path):
    procs = []
    try:
        bport, sport = free_port(), free_port()
        burl, surl = f"http://127.0.0.1:{bport}", f"http://127.0.0.1:{sport}"
        base = make_env(tmp_path, ARENA_EMBED_URL=live_embed.embed_url)
        b = Proc("arena.broker", dict(base, ARENA_BROKER_PORT=str(bport)), tmp_path)
        procs.append(b)
        b.wait_up(burl)
        from arena.config import Settings
        s = Settings.load(env=base, dotenv_path=None)
        B = BrokerClient(burl, s)
        people = {name: Identity.generate() for name in ("hr", "infra", "ga", "sales")}
        for (name, who), summary in zip(people.items(), DOCS):
            p = {"url": f"http://{name}", "summary": summary, "offers": [], "labels": [SDS], "until": time.time() + 3600, "ver": 1}
            assert (await B.advertise(who, p))["ok"]
        issuer = Identity.generate()
        for nid, text in (("n1", "새로 온 동료의 첫 달 적응을 돕는 방법 모집"), ("n2", "서버 비용 절감 아이디어 모집")):
            n = {"notice_id": nid, "issuer_pub": issuer.pub, "until": time.time() + 600, "title": text, "text": text, "audience": {"소속": "삼성SDS"}}
            assert (await B.post_notice(issuer, n))["ok"]
        sp = Proc("arena.peers.search", dict(base, ARENA_SEARCH_PEER_PORT=str(sport), ARENA_SEARCH_PEER_KEY_FILE=str(tmp_path / "s.key"),
                                             ARENA_SEARCH_PEER_AREA=str(tmp_path / "s-area"), ARENA_SEARCH_PEER_LABELS=SDS,
                                             ARENA_SEARCH_PEER_BROKERS=f"open={burl}", ARENA_SEARCH_SYNC_SEC="0.5"), tmp_path)
        procs.append(sp)
        sp.wait_up(surl, path="/.well-known/agent-card.json")
        t = A2ATransport(s)
        for _ in range(40):  # wait for the first sync
            st = await t.call(surl, {"op": "search_status"})
            if st["groups"]["open"]["profiles"] >= 5 and st["groups"]["open"]["notices"] == 2:
                break
            time.sleep(0.25)
        assert st["dim"] == 1024, st
        r = await t.call(surl, {"op": "search_profiles", "q": QUERY, "k": 3})
        assert r["ok"] and r["hits"][0]["pub"] == people["hr"].pub, r
        asker = people["sales"]
        r = await t.call(surl, dict({"op": "search_notices", "q": "신입 사원 온보딩"}, **sign_message(asker, "search_notices")))
        assert r["ok"] and r["hits"][0]["notice_id"] == "n1", r
        found = await B.find("search", role="search")
        assert found["peers"] and found["peers"][0]["url"] == surl  # other peers discover the search peer on the broker
        print("\nprofiles:", [(x["summary"][:14], x["score"]) for x in (await t.call(surl, {"op": "search_profiles", "q": QUERY, "k": 3}))["hits"]])
        print("notices:", [(x["notice_id"], x["score"]) for x in r["hits"]])
    finally:
        for p in procs:
            p.stop()
