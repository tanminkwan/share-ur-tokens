"""P4-D: capability labels the agent attaches itself, only with evidence from the public area or the ledger."""
from arena.config import Settings
from arena.crypto import Identity
from arena.ledger import MemoryStore
from arena.llm import LLMError
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from tests.conftest import make_env
from tests.fakes import RoutedLLM
from tests.test_ledger import Cast
from tests.test_peer import make_peer


def on(tmp_path, **over):
    return Settings.load(env=make_env(tmp_path, ARENA_LABEL_AUTO="true", **over), dotenv_path=None)


async def setup(tmp_path, settings, fields=None, contracts=1):
    from arena.broker.neighbors import NoNeighbors
    from arena.broker.service import BrokerService
    from arena.search import BM25Searcher
    broker = BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])
    llm = RoutedLLM(summary={"summary": "평가 전문가"},
                    fields=fields if fields is not None else {"fields": [{"field": "혁신 과제 평가", "evidence": "혁신 과제 평가 20년"},
                                                                         {"field": "우주 항공", "evidence": "우주선을 설계했다"}]})
    p = make_peer(tmp_path, settings, broker, llm=llm, labels=["소속:예시", "역할:judge"] if contracts == "dup" else ["소속:예시"])
    svc = RecorderService.build(settings, Identity.generate(), MemoryStore(), readers=[])
    cast = Cast()
    cast.judge = p.identity
    if contracts:
        assert (await svc.record(*cast.event()))["ok"]
        assert (await svc.record(*cast.contract(role="judge")))["ok"]
    p.recorder_factory = lambda url: InMemoryRecorderClient(svc)
    p.recorder("mem://rec")
    return p, broker, llm


async def test_p4d1_d2_d3_labels_with_evidence_only(tmp_path):
    s = on(tmp_path)
    p, broker, llm = await setup(tmp_path, s)
    prof = await p.advertise()
    assert prof["labels"] == ["소속:예시", "역할:judge", "분야:혁신 과제 평가"]  # "우주 항공" has no evidence in the area
    caps = {c["label"]: c for c in prof["capabilities"]}
    assert caps["역할:judge"]["basis"] == "ledger" and caps["역할:judge"]["evidence"] == {"mem://rec": 1}
    assert caps["분야:혁신 과제 평가"]["basis"] == "area" and caps["분야:혁신 과제 평가"]["evidence"] == "혁신 과제 평가 20년"
    assert "비밀 규칙" not in llm.asked("fields")[0]["user"]  # owner-only documents never reach the labeler
    assert (await broker.find(__import__("arena.broker.neighbors", fromlist=["Caller"]).Caller.anonymous(), "평가", labels=["역할:judge"]))


async def test_p4d2_threshold_and_p4d4_labels_follow_evidence(tmp_path):
    s = on(tmp_path, ARENA_LABEL_ROLE_MIN="2")
    p, _, llm = await setup(tmp_path, s, fields={"fields": []})
    assert (await p.advertise())["labels"] == ["소속:예시"]  # one contract < threshold 2
    s2 = on(tmp_path / "x", ARENA_LABEL_ROLE_MIN="1")
    (tmp_path / "x").mkdir()
    p2, _, llm2 = await setup(tmp_path / "x", s2)
    assert "분야:혁신 과제 평가" in (await p2.advertise())["labels"]
    llm2.routes["fields"] = LLMError("down")  # the model fails: ledger labels stay, area labels drop
    assert (await p2.advertise())["labels"] == ["소속:예시", "역할:judge"]


async def test_p4d3_field_cap_and_p4d5_no_duplicates_and_switch(tmp_path):
    many = {"fields": [{"field": f"평가{i}", "evidence": "혁신 과제 평가 20년"} for i in range(9)]}
    s = on(tmp_path, ARENA_LABEL_FIELD_MAX="2")
    p, _, _ = await setup(tmp_path, s, fields=many, contracts="dup")
    labels = (await p.advertise())["labels"]
    assert labels.count("역할:judge") == 1 and sum(x.startswith("분야:") for x in labels) == 2
    off = Settings.load(env=make_env(tmp_path / "o"), dotenv_path=None)  # ARENA_LABEL_AUTO=false in tests
    (tmp_path / "o").mkdir()
    q, _, llm = await setup(tmp_path / "o", off)
    prof = await q.advertise()
    assert prof["labels"] == ["소속:예시"] and prof["capabilities"] == [] and llm.asked("fields") == []
