"""P2-C1~C6: the idea-contest motif in one process (LocalTransport, in-memory brokers and recorder, scripted owners)."""
import time

import pytest

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import InMemoryNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity, canon, h
from arena.events import EventLog
from arena.genesis import record_genesis
from arena.ledger import MemoryStore, audit_chain, contribution
from arena.peer.area import LocalFolderArea
from arena.peer.node import Peer, PeerConfig
from arena.peer.record_role import RecordRole
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from arena.search import BM25Searcher
from tests.fakes import FakeOwner, RoutedLLM
from tests.motif.doubles import ENDORSER_LABEL, OPEN, REVIEW, AcceptRole, EndorseByOwner, Judge
from tests.motif.flow import apply, check_notice, found_group, open_event, review_and_adopt, submissions

SDS = "소속:삼성SDS"


class MemoryWorld:
    def __init__(self, tmp, settings, ceo_yes=True):
        import dataclasses
        settings = dataclasses.replace(settings, recorder_require_group=True)  # every record must trace to a group
        self.tmp, self.settings, self.log, self.t = tmp, settings, EventLog(echo=False), LocalTransport()
        self.org_id, self.god = Identity.generate(), Identity.generate()
        gw = InMemoryNeighbors()
        self.brokers = {OPEN: BrokerService(settings, Identity.generate(), BM25Searcher(), gw, name="A", neighbors=[]),
                        REVIEW: BrokerService(settings, Identity.generate(), BM25Searcher(), gw, name="D", neighbors=[], owner_pub=self.org_id.pub,
                                              group_id="g-review")}
        self.recorders = {}
        self.org = self.peer("org", [], ["사내 행사 진행"], groups=[OPEN, REVIEW], identity=self.org_id)  # IntakeDesk: built in
        self.rec = self.peer("rec", [], ["감사 기록 보관과 열람 통제 담당"], record=True)
        self.ceo = self.peer("ceo", [EndorseByOwner()], ["대표이사"], labels=[SDS, ENDORSER_LABEL],
                             owner=FakeOwner(yes=ceo_yes, why="회사 전략에 맞다" if ceo_yes else "보류"))
        self.rev = self.peer("rev", [AcceptRole("review"), Judge()], ["공모 심사 평가 기준 심사위원 20년"], groups=[REVIEW],
                             owner=FakeOwner(writes=[lambda task, ctx: {"reviews": [
                                 {"id": line[2:10], "score": 9.0 - i, "comment": f"의견 {i}"} for i, line in enumerate(ctx.splitlines())]}]))
        self.applicants = [self.peer(f"a{i}", [], [f"HR 담당 {i}", "신입 온보딩 프로그램 운영"]) for i in range(3)]
        self.outsider = self.peer("x", [], ["협력사 분석가"], labels=["소속:협력사"])

    def peer(self, name, apps, notes, labels=(SDS,), groups=(OPEN,), owner=None, identity=None, record=False):
        root = self.tmp / name
        root.mkdir()
        (root / "notes.md").write_text("".join(f"- {n}\n" for n in notes), encoding="utf-8")
        ident, apps = identity or Identity.generate(), list(apps)
        if record:
            svc = RecorderService.build(self.settings, ident, MemoryStore(), readers=[self.god.pub])
            self.recorders[f"mem://{name}/recorder"] = svc
            apps.append(RecordRole(svc, f"mem://{name}/recorder"))
        p = Peer(ident, self.settings, PeerConfig(url=f"mem://{name}", labels=list(labels), element_apps=True), LocalFolderArea(str(root), self.settings),
                 owner or FakeOwner(), RoutedLLM(summary={"summary": " ".join(notes)}), self.t, self.log,
                 brokers={g: InMemoryBrokerClient(self.brokers[g]) for g in groups}, apps=apps)
        p.recorder_factory = lambda u: InMemoryRecorderClient(self.recorders[u])
        self.t.register(p.config.url, p.handle)
        return p

    async def boot(self):
        r = await record_genesis(self.rec.recorder("mem://rec/recorder"), self.god, self.settings,
                                 self.brokers[OPEN].identity.pub, self.rec.identity.pub)  # god's first act
        assert r["ok"] and r["seq"] == 0, r
        g = {"pub": self.rev.identity.pub, "until": time.time() + 3600}
        await self.brokers[REVIEW].grant(g, self.org_id.sign(g))
        for p in [self.org, self.rec, self.ceo, self.rev, *self.applicants, self.outsider]:
            await p.advertise()
        r = await found_group(self.org, self.org.recorder("mem://rec/recorder"), REVIEW, closed=True)
        assert r["ok"], r

    @property
    def ledger(self):
        return next(iter(self.recorders.values())).ledger


@pytest.fixture
async def world(tmp_path, settings):
    w = MemoryWorld(tmp_path, settings)
    await w.boot()
    return w


async def test_pc2_pc3_event_is_endorsed_by_the_ceo_and_noticed(world):
    o = await open_event(world)
    assert o["endorsed"] and o["ceo"]["pub"] == world.ceo.identity.pub
    chain = world.ledger.chain
    assert [e["type"] for e in chain] == ["genesis", "group", "event", "endorse", "contract", "contract"]
    assert chain[0]["payload"]["god"] == world.god.pub and chain[0]["payload"]["group_id"] == "public"  # god's genesis is entry 0
    assert chain[1]["payload"] == {"group_id": "g-review", "founder": world.org.identity.pub, "closed": True,
                                   "brokers": [world.brokers[REVIEW].identity.pub], "ledger_id": chain[0]["hash"]}  # the review group's founding is notarized
    assert set(chain[2]["sigs"]) == {world.org.identity.pub}  # declared by the org alone
    assert set(chain[3]["sigs"]) == {world.org.identity.pub, world.ceo.identity.pub} and chain[3]["payload"]["event_hash"] == chain[2]["hash"]
    assert [e["payload"]["group_id"] for e in chain[2:]] == ["public", "public", "public", "g-review"]  # where each thing happened
    assert world.rev.identity.pub not in str(o["notice"])  # the reviewer stays unnamed to applicants
    assert o["posted"]["visible_to"] == 6  # every 삼성SDS profile on the open board, not the partner
    assert audit_chain(chain) == "ok"


async def test_pc2_without_the_ceos_endorsement_the_org_does_not_open_the_contest(tmp_path, settings):
    """the event is declared; the CEO declines to put the company's name on it; the org (its own choice) posts no notice"""
    w = MemoryWorld(tmp_path, settings, ceo_yes=False)
    await w.boot()
    o = await open_event(w)
    assert not o["endorsed"] and o["endorsement"] == {"ok": False, "error": "보류"}
    assert [e["type"] for e in w.ledger.chain] == ["genesis", "group", "event"] and w.brokers[OPEN].notices == {}


async def test_pc4_applicants_verify_then_apply_and_contest_completes(world):
    o = await open_event(world)
    for i, p in enumerate(world.applicants):
        ns = (await p.brokers[OPEN].list_notices(p.identity))["notices"]
        assert [n["notice_id"] for n in ns] == [o["event_id"]]
        chk = await check_notice(p, ns[0])
        assert chk["event_ok"] and chk["endorsed_ok"] and chk["endorser_label_ok"] and chk["contracts_ok"]
        assert [c["contractor"] for c in chk["contracts"]] == [world.rec.identity.pub, None]  # policy hides the reviewer
        r = await apply(p, ns[0], {"title": f"버디 매칭 {i}", "idea": "첫 주 선배 버디"})
        assert r["ok"], r
        assert [x["kind"] for x in p.receipts.items] == ["publish", "share"]
    assert (await world.outsider.brokers[OPEN].list_notices(world.outsider.identity))["notices"] == []
    res = await review_and_adopt(world, o, top=1)
    assert len(res["scores"]) == 3 and len(res["adopted"]) == 1
    c = contribution(world.ledger.chain)
    assert c[world.ceo.identity.pub]["endorsements"] == 1 and c[world.org.identity.pub]["events"] == 1 and c[world.org.identity.pub]["endorsed"] == 1
    assert c[world.rev.identity.pub]["roles"] == {"review": 1} and c[world.rev.identity.pub]["verdicts_given"] == {"review": 3}
    assert c[world.rec.identity.pub]["roles"] == {"record": 1}
    winner = submissions(world, o["event_id"])[res["adopted"][0]]["author"]
    assert c[winner]["verdicts_received"] == {"review": 1, "adopt": 1} and c[winner]["received_by"] == 2
    assert audit_chain(world.ledger.chain) == "ok"


async def test_pc5_policy_is_enforced(world):
    o = await open_event(world)
    n, R = o["notice"], o["R"]
    a = world.applicants[0]
    await apply(a, n, {"title": "t", "idea": "i"})
    ch = next(iter(submissions(world, o["event_id"])))
    # a review by someone without the review contract
    p = {"evaluator": a.identity.pub, "event_id": o["event_id"], "content_hash": ch, "verdict": "review", "score": 10.0, "comment_hash": "0" * 64,
         "group_id": "public", "ledger_id": world.ledger.chain[0]["hash"]}
    assert (await R.record("feedback", p, {a.identity.pub: a.sign(p)}))["error"] == "verdict 'review' requires the 'review' role in this event"
    # an adoption by someone other than the issuer
    q = {"evaluator": a.identity.pub, "event_id": o["event_id"], "content_hash": ch, "verdict": "adopt", "group_id": "public", "ledger_id": world.ledger.chain[0]["hash"]}
    assert (await R.record("feedback", q, {a.identity.pub: a.sign(q)}))["error"] == "verdict 'adopt' requires the event issuer"
    # the contracted recorder cannot publish into the event; submitting is refused too (ledger: conflicting role)
    rp = {"author": world.rec.identity.pub, "content_hash": h(canon({"x": 1})), "event_id": o["event_id"], "group_id": "public",
          "ledger_id": world.ledger.chain[0]["hash"]}
    assert (await R.record("publish", rp, {world.rec.identity.pub: world.rec.sign(rp)}))["error"].startswith("a contractor in a conflicting role")
    assert (await apply(world.rec, n, {"title": "x", "idea": "y"}))["ok"] is False
    # one submission per peer
    assert (await apply(a, n, {"title": "t2", "idea": "i2"}))["error"] == "intake: at most 1 submissions per author"  # now enforced by the ledger (intake element)


async def test_pc6_audit_tamper_and_read_control(world):
    o = await open_event(world)
    await apply(world.applicants[0], o["notice"], {"title": "t", "idea": "i"})
    R = o["R"]
    assert (await R.read_chain(world.god))["ok"]
    assert (await R.read_chain(Identity.generate()))["ok"] is False
    world.ledger.chain[3]["payload"]["endorser"] = Identity.generate().pub  # someone swaps the CEO's endorsement afterwards
    assert (await R.audit())["status"] == "TAMPERED at seq 3 (hash chain)"
