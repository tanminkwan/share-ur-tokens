"""P2-B10: a peer takes the record role by hosting the recorder service and opening its API."""
import httpx

from arena.ledger import MemoryStore
from arena.peer.app import Decision
from arena.peer.record_role import RecordRole
from arena.recorder.service import RecorderService
from tests.test_peer import broker, make_peer  # noqa: F401  (fixture)


async def test_pb10_record_role_offers_api_and_accepts(tmp_path, settings, broker):  # noqa: F811
    p = make_peer(tmp_path, settings, broker)
    role = RecordRole(RecorderService.build(settings, p.identity, MemoryStore(), readers=[]), url="http://rec:1")
    assert role.offers() == ["record"] and role.profile_extra() == {"recorder_url": "http://rec:1"}
    assert (await role.accept_role(p, "record", {})).accept is True
    assert await role.accept_role(p, "other", {}) is None
    picky = RecordRole(role.service, url="http://rec:1", decide=lambda peer, req: Decision(False, "busy"))
    assert (await picky.accept_role(p, "record", {})).reason == "busy"
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=role.api()), base_url="http://rec")
    hl = (await http.get("/health")).json()
    assert hl["pub"] == p.identity.pub  # the recorder seals with the peer's own key
