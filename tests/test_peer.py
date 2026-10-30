"""P2-B5, B8, B9, B11, B14: peer assembly, op dispatch, engage, approve, profile, receipts."""
import pytest

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.events import EventLog
from arena.peer.app import Decision, PeerApp
from arena.peer.area import LocalFolderArea
from arena.peer.node import Peer, PeerConfig
from arena.peer.receipts import Receipts
from arena.search import BM25Searcher
from tests.fakes import FakeOwner, ScriptedLLM


class EchoApp(PeerApp):
    name = "echo"

    def offers(self):
        return ["judge"]

    def ops(self):
        async def hello(peer, msg):
            return {"ok": True, "hello": msg.get("who")}
        return {"hello": hello}

    def profile_extra(self):
        return {"echo_url": "http://echo"}

    async def accept_role(self, peer, role, request):
        return Decision(request.get("fit", True), "fits" if request.get("fit", True) else "busy") if role == "judge" else None

    async def approve_event(self, peer, event, request):
        return Decision(event.get("kind") != "bad", "looks fine")


def area(tmp_path, settings):
    (tmp_path / "notes.md").write_text("- 혁신 과제 평가 20년\n- 기준표대로 본다\n", encoding="utf-8")
    (tmp_path / "_owner_rules.md").write_text("- 비밀 규칙\n", encoding="utf-8")
    return LocalFolderArea(str(tmp_path), settings)


@pytest.fixture
def broker(settings):
    return BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])


def make_peer(tmp_path, settings, broker, apps=(), llm=None, offers=("x",), labels=("소속:예시",)):
    return Peer(Identity.generate(), settings, PeerConfig(url="mem://p", offers=list(offers), labels=list(labels)),
                area(tmp_path, settings), FakeOwner(), llm or ScriptedLLM(), LocalTransport(), EventLog(echo=False),
                brokers={"main": InMemoryBrokerClient(broker)}, apps=list(apps))


async def test_pb8_ops_from_apps_and_unknown_op(tmp_path, settings, broker):
    p = make_peer(tmp_path, settings, broker, apps=[EchoApp()])
    assert await p.handle({"op": "hello", "who": "me"}) == {"ok": True, "hello": "me"}
    assert await p.handle({"op": "nope"}) == {"ok": False, "error": "unknown op: nope"}
    assert set(p.skills()) == {"engage", "approve", "hello"}
    assert p.offers() == ["x", "judge"]


def test_pb8_duplicate_op_is_an_assembly_error(tmp_path, settings, broker):
    with pytest.raises(ValueError):
        make_peer(tmp_path, settings, broker, apps=[EchoApp(), EchoApp()])


async def test_pb6_handler_exception_becomes_error_reply(tmp_path, settings, broker):
    class Boom(PeerApp):
        def ops(self):
            async def boom(peer, msg):
                raise KeyError("missing")
            return {"boom": boom}
    p = make_peer(tmp_path, settings, broker, apps=[Boom()])
    r = await p.handle({"op": "boom"})
    assert r["ok"] is False and "KeyError" in r["error"]


async def test_pb9_engage_rules(tmp_path, settings, broker):
    from arena.crypto import verify
    p = make_peer(tmp_path, settings, broker, apps=[EchoApp()])
    c = {"event_id": "e", "role": "judge", "issuer": "i", "contractor": p.identity.pub, "nonce": "n"}
    r = await p.handle({"op": "engage", "role": "judge", "contract": c, "request": {}})
    assert r["ok"] and verify(p.identity.pub, c, r["sig"])
    r = await p.handle({"op": "engage", "role": "judge", "contract": c, "request": {"fit": False}})
    assert r == {"ok": False, "error": "busy"}
    r = await p.handle({"op": "engage", "role": "cook", "contract": dict(c, role="cook"), "request": {}})
    assert r["ok"] is False and "not offered" in r["error"]
    r = await p.handle({"op": "engage", "role": "judge", "contract": dict(c, contractor="someone"), "request": {}})
    assert r["ok"] is False
    q = make_peer(tmp_path, settings, broker, offers=["x"])  # offers x but no app decides about it
    r = await q.handle({"op": "engage", "role": "x", "contract": dict(c, role="x", contractor=q.identity.pub), "request": {}})
    assert r == {"ok": False, "error": "no app decides about role x"}


async def test_pb14_approve_rules(tmp_path, settings, broker):
    from arena.crypto import verify
    p = make_peer(tmp_path, settings, broker, apps=[EchoApp()])
    ev = {"event_id": "e", "issuer": "i", "kind": "ok", "policy": {}, "approvers": [p.identity.pub]}
    r = await p.handle({"op": "approve", "event": ev, "request": {}})
    assert r["ok"] and verify(p.identity.pub, ev, r["sig"]) and r["reason"] == "looks fine"
    assert (await p.handle({"op": "approve", "event": dict(ev, kind="bad"), "request": {}}))["ok"] is False
    r = await p.handle({"op": "approve", "event": dict(ev, approvers=["other"]), "request": {}})
    assert r == {"ok": False, "error": "I am not an approver of this event"}
    q = make_peer(tmp_path, settings, broker)
    r = await q.handle({"op": "approve", "event": dict(ev, approvers=[q.identity.pub]), "request": {}})
    assert r == {"ok": False, "error": "no app approves events here"}


async def test_pb5_profile_summarizes_public_docs_and_bumps_version(tmp_path, settings, broker, clock):
    llm = ScriptedLLM({"summary": "평가 전문가"}, {"summary": "평가 전문가 v2"})
    p = make_peer(tmp_path, settings, broker, apps=[EchoApp()], llm=llm)
    p.clock = clock
    await p.advertise()
    prompt = llm.calls[0]["user"]
    assert "혁신 과제 평가 20년" in prompt and "비밀 규칙" not in prompt  # owner-only docs never leave
    prof = broker.profiles[p.identity.pub]
    assert prof["summary"] == "평가 전문가" and prof["ver"] == 1 and prof["offers"] == ["x", "judge"]
    assert prof["labels"] == ["소속:예시"] and prof["url"] == "mem://p" and prof["echo_url"] == "http://echo"
    assert prof["until"] == clock() + settings.profile_ttl_sec
    await p.add_experience("새 경험")
    assert broker.profiles[p.identity.pub]["ver"] == 2 and "새 경험" in p.area.lines()


async def test_pb5_profile_falls_back_when_llm_fails(tmp_path, settings, broker):
    from arena.llm import LLMError
    p = make_peer(tmp_path, settings, broker, llm=ScriptedLLM(LLMError("down")))
    await p.advertise()
    assert broker.profiles[p.identity.pub]["summary"] == "혁신 과제 평가 20년"
    assert any(e["kind"] == "llm" for e in p.log.tail(5))


async def test_pb11_receipts_check_the_recorder_seal():
    from arena.ledger import Ledger, MemoryStore
    from arena.config import Settings
    rec = Identity.generate()
    ledger = Ledger(rec, MemoryStore(), Settings.load(env={}, dotenv_path=None))
    me = Identity.generate()
    payload = {"author": me.pub, "content_hash": "c" * 64}
    e, _ = ledger.propose("publish", payload, {me.pub: me.sign(payload)})
    resp = {"ok": True, "seq": e["seq"], "hash": e["hash"], "seal": e["seal"]}
    r = Receipts()
    assert r.keep(resp, "publish", payload, expected_recorder=rec.pub)
    assert not r.keep(resp, "publish", payload, expected_recorder=Identity.generate().pub)
    forged = dict(resp, hash="0" * 64)
    assert not Receipts.sealed_by(forged, rec.pub)
    assert len(r.items) == 1 and r.items[0]["kind"] == "publish"


async def test_pb16_peer_builds_recorder_clients_by_url(tmp_path, settings, broker):
    from arena.recorder.client import RecorderClient
    p = make_peer(tmp_path, settings, broker)
    assert isinstance(p.recorder("http://rec:1"), RecorderClient)
    sentinel = object()
    p.recorder_factory = lambda url: sentinel
    assert p.recorder("http://x") is sentinel
