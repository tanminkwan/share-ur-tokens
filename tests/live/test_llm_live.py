"""Real LLM: the adapter returns schema-shaped JSON; a peer's profile summary comes from its public area."""
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

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["city", "count"],
          "properties": {"city": {"type": "string"}, "count": {"type": "integer"}}}


async def test_pe2_live_adapter_returns_schema_json(live):
    out = await build_llm(live).ask_json(system="JSON으로만 답하세요.", user="대한민국의 수도 이름을 한국어로, 그리고 그 이름의 글자 수를 알려 주세요.", schema=SCHEMA)
    assert set(out) == {"city", "count"} and ("서울" in out["city"] or "seoul" in out["city"].lower()) and isinstance(out["count"], int)


async def test_pe2_live_profile_summary_uses_public_area_only(live, tmp_path):
    (tmp_path / "notes.md").write_text("- 인프라 엔지니어 12년차\n- 사내 도구 도입과 장애 대응 경험이 많다\n", encoding="utf-8")
    (tmp_path / "_owner_rules.md").write_text("- 비밀코드 ZEBRA-77 은 절대 공개하지 말 것\n", encoding="utf-8")
    broker = BrokerService(live, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])
    log = EventLog(echo=False)
    p = Peer(Identity.generate(), live, PeerConfig(url="mem://p"), LocalFolderArea(str(tmp_path), live), FakeOwner(),
             build_llm(live), LocalTransport(), log, brokers={"main": InMemoryBrokerClient(broker)}, apps=[])
    prof = await p.advertise()
    assert not [e for e in log.tail(10) if e["kind"] == "llm"], log.tail(10)  # no fallback: the real LLM answered
    assert "인프라" in prof["summary"] and "ZEBRA" not in prof["summary"]
