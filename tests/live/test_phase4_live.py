"""P4-E3: capability labels from the public area with the real LLM: only fields whose quoted evidence is really there."""
from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.events import EventLog
from arena.llm import build_llm
from arena.peer.area import LocalFolderArea
from arena.peer.node import Peer, PeerConfig
from arena.search import BM25Searcher
from tests.fakes import FakeOwner

NOTES = ["클라우드 비용 최적화 업무를 5년째 맡고 있다", "FinOps 도입으로 월 사용료를 30% 줄였다", "쿠버네티스 클러스터 운영과 장애 대응을 한다"]


async def test_p4e3_live_capability_labels_have_real_evidence(live, tmp_path):
    live.label_auto = True
    (tmp_path / "notes.md").write_text("".join(f"- {n}\n" for n in NOTES), encoding="utf-8")
    (tmp_path / "_owner_rules.md").write_text("- 사내 보안 등급 문서는 절대 공개하지 않는다\n", encoding="utf-8")
    broker = BrokerService(live, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])
    log = EventLog(echo=True)
    p = Peer(Identity.generate(), live, PeerConfig(url="mem://p", labels=["소속:삼성SDS"]), LocalFolderArea(str(tmp_path), live), FakeOwner(),
             build_llm(live), LocalTransport(), log, brokers={"b": InMemoryBrokerClient(broker)}, apps=[])
    prof = await p.advertise()
    area = [c for c in prof["capabilities"] if c["basis"] == "area"]
    print("\nlabels:", prof["labels"])
    print("evidence:", [(c["label"], c["evidence"]) for c in area])
    flat = " ".join(" ".join(NOTES).split())
    assert area, "the model should find at least one field with real evidence"
    assert all(c["label"].startswith(live.label_field_prefix) and c["evidence"] in flat for c in area)
    assert not any("보안 등급" in c["evidence"] for c in area)  # owner-only documents never become evidence
    assert prof["labels"][0] == "소속:삼성SDS" and len(area) <= live.label_field_max


async def test_p4e3_live_field_names_stay_in_the_area_language(live, tmp_path):
    live.label_auto = True
    (tmp_path / "notes.md").write_text("- 대표이사\n- 회사 전략과 인재 육성을 책임진다\n", encoding="utf-8")
    broker = BrokerService(live, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])
    p = Peer(Identity.generate(), live, PeerConfig(url="mem://ceo", labels=["소속:삼성SDS"]), LocalFolderArea(str(tmp_path), live), FakeOwner(),
             build_llm(live), LocalTransport(), EventLog(echo=False), brokers={"b": InMemoryBrokerClient(broker)}, apps=[])
    labels = [c["label"] for c in (await p.advertise())["capabilities"] if c["basis"] == "area"]
    print("\nlabels:", labels)
    assert labels and all(any("가" <= ch <= "힣" for ch in x[len(live.label_field_prefix):]) for x in labels)
