"""P2-C7: the idea-contest motif with real processes and the real LLM.
brokers = separate `python -m arena.broker` processes; peers = A2A servers; the recorder peer opens the recorder API;
profiles, the CEO's approval, the reviewer's acceptance and scores, and the applicants' writing come from the real LLM."""
import time

import pytest

from arena.a2a import A2ATransport
from arena.broker.client import BrokerClient
from arena.crypto import Identity
from arena.events import EventLog
from arena.genesis import record_genesis
from arena.ledger import JsonlStore, audit_chain, contribution
from arena.llm import build_llm
from arena.peer.area import LocalFolderArea
from arena.peer.node import Peer, PeerConfig
from arena.peer.record_role import RecordRole
from arena.recorder.service import RecorderService
from arena.serve import serve_background
from tests.conftest import make_env
from tests.motif.doubles import APPROVER_LABEL, CONTENT_SCHEMA, OPEN, REVIEW, AcceptRole, ApproveByOwner, Judge, LLMOwner
from tests.motif.flow import CALL, apply, check_notice, found_group, open_event, review_and_adopt
from tests.test_processes import Proc, free_port

SDS = "소속:삼성SDS"
HOST = "127.0.0.1"


class LiveWorld:
    def __init__(self, tmp, settings, procs):
        self.tmp, self.s, self.procs, self.servers = tmp, settings, procs, []
        self.log, self.t, self.llm = EventLog(echo=True), A2ATransport(settings), build_llm(settings)
        self.org_id, self.god = Identity.generate(), Identity.generate()

    def start_brokers(self):
        self.urls = {}
        for group, owner in ((OPEN, None), (REVIEW, self.org_id.pub)):
            port = free_port()
            url = f"http://{HOST}:{port}"
            env = make_env(self.tmp, ARENA_BROKER_PORT=port, ARENA_BROKER_NAME=group,
                           ARENA_BROKER_KEY_FILE=str(self.tmp / f"{group}.key"),
                           **({"ARENA_BROKER_OWNER_PUB": owner, "ARENA_BROKER_GROUP_ID": "g-" + group} if owner else {}))
            p = Proc("arena.broker", env, self.tmp)
            self.procs.append(p)
            p.wait_up(url)
            self.urls[group] = url

    async def peer(self, name, apps, notes, persona=None, labels=(SDS,), groups=(OPEN,), identity=None, record=False):
        root = self.tmp / "areas" / name
        root.mkdir(parents=True)
        (root / "notes.md").write_text("".join(f"- {n}\n" for n in notes), encoding="utf-8")
        ident, apps, port = identity or Identity.generate(), list(apps), free_port()
        url = f"http://{HOST}:{port}"
        if record:
            svc = RecorderService.build(self.s, ident, JsonlStore(str(self.tmp / "ledger.jsonl")), readers=[self.god.pub])
            rport = free_port()
            role = RecordRole(svc, f"http://{HOST}:{rport}")
            apps.append(role)
            self.servers.append(await serve_background(role.api(), HOST, rport))
            self.ledger = svc.ledger
        owner = LLMOwner(self.llm, self.log, name, persona or f"당신은 {notes[0]}입니다.")
        p = Peer(ident, self.s, PeerConfig(url=url, labels=list(labels), element_apps=True), LocalFolderArea(str(root), self.s), owner, self.llm,
                 self.t, self.log, brokers={g: BrokerClient(self.urls[g], self.s) for g in groups}, apps=apps)
        self.servers.append(await serve_background(p.a2a_app(), HOST, port))
        return p

    async def boot(self):
        self.start_brokers()
        self.org = await self.peer("org", [], ["사내 행사 진행 담당"], groups=[OPEN, REVIEW], identity=self.org_id)  # IntakeDesk: built in
        self.rec = await self.peer("rec", [], ["정보보안·컴플라이언스 8년차", "감사 추적을 위한 기록 보관과 열람 통제를 맡아 왔다"], record=True)
        self.ceo = await self.peer("ceo", [ApproveByOwner()], ["대표이사", "회사 전략과 인재 육성을 책임진다"], labels=[SDS, APPROVER_LABEL],
                                   persona="당신은 이 회사의 대표이사입니다. 신입 사원 적응과 인재 육성은 회사의 중점 과제라서, 그와 관련된 사내 공모라면 결재합니다.")
        self.rev = await self.peer("rev", [AcceptRole("review"), Judge()], ["혁신 과제 심사 전문가 20년차", "사내 공모전 심사위원을 여러 번 맡았다"],
                                   groups=[REVIEW], persona="당신은 사내 공모 심사 전문가입니다. 심사 역할 요청은 이해 충돌이 없으면 수락하고, "
                                                            "참신성·실현 가능성·기대 효과로 1~10점을 변별력 있게 줍니다.")
        self.applicants = [await self.peer(n, [], notes) for n, notes in (
            ("hr", ["HR 담당 7년차", "신입 교육과 조직문화 프로그램을 운영했다", "온보딩은 첫 2주의 관계 형성이 가장 중요하다"]),
            ("ux", ["UX 디자이너 6년차", "첫인상과 첫 경험이 사용 여부를 좌우한다"]))]
        g = {"pub": self.rev.identity.pub, "until": time.time() + 3600}
        assert (await self.org.brokers[REVIEW].grant(self.org_id, g["pub"], g["until"]))["ok"]
        for p in [self.org, self.rec, self.ceo, self.rev, *self.applicants]:
            await p.advertise()
        R = self.org.recorder(self.rec.app(RecordRole).url)
        assert (await record_genesis(R, self.god, self.s, (await self.org.brokers[OPEN].health())["pub"], self.rec.identity.pub))["ok"]
        assert (await found_group(self.org, R, REVIEW, closed=True))["ok"]

    def stop(self):
        for s in self.servers:
            s.should_exit = True


@pytest.fixture
def procs():
    started = []
    yield started
    for p in started:
        p.stop()


async def test_pc7_live_motif_end_to_end(live, tmp_path, procs):
    w = LiveWorld(tmp_path, live, procs)
    try:
        await w.boot()
        fallbacks = [e for e in w.log.tail(200) if e["kind"] == "llm"]
        o = await open_event(w)
        assert o["approved"], o["approval"]  # the CEO persona (real LLM) approved
        assert [e["type"] for e in w.ledger.chain[:2]] == ["genesis", "group"] and set(w.ledger.chain[2]["sigs"]) == {w.org.identity.pub, w.ceo.identity.pub}
        assert {e["payload"]["group_id"] for e in w.ledger.chain} == {"public", "g-reviewers"}
        for p in w.applicants:
            ns = (await p.brokers[OPEN].list_notices(p.identity))["notices"]
            n = next(x for x in ns if x["notice_id"] == o["event_id"])
            chk = await check_notice(p, n)
            assert chk["event_ok"] and chk["approver_label_ok"] and chk["contracts_ok"], chk
            content = await p.owner.write(f"다음 공모에 낼 아이디어를 한 개 쓰세요. title은 한 줄, idea는 2~3문장.\n공모: {n['text']}",
                                          "\n".join(p.area.lines()), CONTENT_SCHEMA)
            r = await apply(p, n, content)
            assert r["ok"], r
        res = await review_and_adopt(w, o, top=1)
        assert len(res["scores"]) == 2 and len(res["adopted"]) == 1
        chain = w.ledger.chain
        assert audit_chain(chain) == "ok"
        assert [e["type"] for e in chain].count("feedback") == 3 and chain[1]["payload"]["founder"] == w.org.identity.pub
        c = contribution(chain)
        assert c[w.ceo.identity.pub]["approvals"] == 1
        profiles = (await w.org.brokers[OPEN].list_profiles(w.org.identity))["profiles"]
        assert all(p["summary"] for p in profiles) and len(profiles) == 5
        print("\nLLM fallbacks during boot:", len(fallbacks))
        print("scores:", {k[:8]: v for k, v in res["scores"].items()}, "adopted:", [k[:8] for k in res["adopted"]])
        print("ledger:", [e["type"] for e in chain])
    finally:
        w.stop()
