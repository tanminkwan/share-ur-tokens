"""P5-C10 ~ C13: the basic assistant (the primordial way to hold or join an event) and its generic tools.
LLM choices are scripted here so each tool is checked deterministically; the live acceptance test lets real agents choose."""
import asyncio
import json
import time

import pytest

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity, h
from arena.events import EventLog
from arena.genesis import record_genesis
from arena.ledger import MemoryStore, audit_chain
from arena.peer.area import LocalFolderArea
from arena.peer.assistant import EventAssistant
from arena.peer.node import Peer, PeerConfig
from arena.peer.record_role import RecordRole
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from arena.search import BM25Searcher
from tests.fakes import FakeOwner

RULES = "[예시 이벤트 규칙]\n1. 참가 신청을 하면 개최자가 member 역할 계약을 맺는다.\n2. 두 사람은 값을 먼저 등록하고 서로 공개한다."
POLICY = {"roles": ["member"], "attest_roles": {"pair": "member", "summary": "issuer"}}


class Steps:
    """an LLM stand-in for the two-step protocol: first the tool, then that tool's arguments; 'wait' when nothing is queued"""

    def __init__(self):
        self.queue, self.prompts, self.current = [], [], None

    def push(self, tool, **args):
        as_json = {"send": {"data"}, "solicit": {"data"}, "propose_attest": {"value"}}.get(tool, set())  # free-form JSON goes as *_json strings
        shaped = {(f"{k}_json" if k in as_json else k): (json.dumps(v, ensure_ascii=False) if k in as_json else v) for k, v in args.items()}
        self.queue.append((tool, shaped))

    async def ask_json(self, **kw):
        self.prompts.append(kw)
        key = kw["schema"]["required"][0] if kw["schema"].get("required") else None
        if key == "summary":
            return {"summary": "peer"}
        if key == "thought":
            self.current = self.queue.pop(0) if self.queue else ("wait", {})
            return {"thought": "", "tool": self.current[0]}
        return dict(self.current[1])  # the arguments of the tool chosen just before


class Eco:
    def __init__(self, tmp, settings):
        import dataclasses
        self.s = dataclasses.replace(settings, recorder_require_group=True)
        self.t, self.log = LocalTransport(), EventLog(echo=False)
        self.broker = BrokerService(self.s, Identity.generate(), BM25Searcher(), NoNeighbors(), name="genesis", neighbors=[])
        self.god, rec_id = Identity.generate(), Identity.generate()
        self.svc = RecorderService.build(self.s, rec_id, MemoryStore(), readers=[self.god.pub])
        self.tmp, self.peers = tmp, {}
        self.rec = self.peer("rec", identity=rec_id, apps=[RecordRole(self.svc, "mem://rec/api")])

    def peer(self, name, identity=None, apps=None, owner=None):
        (self.tmp / name).mkdir()
        (self.tmp / name / "notes.md").write_text(f"- {name}\n", encoding="utf-8")
        llm = Steps()
        asst = EventAssistant(self.s)
        p = Peer(identity or Identity.generate(), self.s, PeerConfig(url=f"mem://{name}", labels=["소속:예시"]), LocalFolderArea(str(self.tmp / name), self.s),
                 owner or FakeOwner(yes=True, why="좋다"), llm, self.t, self.log, brokers={"public": InMemoryBrokerClient(self.broker)},
                 apps=(apps if apps is not None else []) + [asst])
        p.recorder_factory = lambda u: InMemoryRecorderClient(self.svc)
        self.t.register(p.config.url, p.handle)
        self.peers[name] = p
        return p

    async def boot(self):
        assert (await record_genesis(self.svc, self.god, self.s, self.broker.identity.pub, self.rec.identity.pub))["ok"]
        for p in self.peers.values():
            await p.advertise()


def asst(p):
    return p.app(EventAssistant)


def ctx(p):
    """the context the platform injects into the assistant app"""
    return p.ctx(EventAssistant)


async def settle(*peers, rounds=50):
    """let the background agent turns finish"""
    for _ in range(rounds):
        await asyncio.sleep(0.01)
        if all(not asst(p).busy() for p in peers):
            return


@pytest.fixture
async def eco(tmp_path, settings):
    e = Eco(tmp_path, settings)
    e.host, e.a, e.b = e.peer("host"), e.peer("a"), e.peer("b")
    await e.boot()
    return e


async def open_event(e):
    return await asst(e.host).host_event(ctx(e.host), title="예시 이벤트", kind="예시", rules=RULES, policy=POLICY,
                                         instruction="참가 신청이 오면 member 계약을 맺어라.")


async def test_p5c10_host_declares_the_event_with_its_rules_and_posts_them(eco):
    ev = await open_event(eco)
    decl = next(x for x in eco.svc.ledger.chain if x["type"] == "event")["payload"]
    assert decl["event_id"] == ev and decl["rules_hash"] == h(RULES.encode()) and decl["policy"] == POLICY and decl["group_id"] == "public"
    n = eco.broker.notices[ev]
    assert n["rules"] == RULES and n["event_hash"] and n["recorder_url"] == "mem://rec/api"
    await settle(eco.host)
    assert "참가 신청이 오면" in json.dumps(eco.host.llm.prompts[-1]["messages"], ensure_ascii=False)  # the instruction reached the agent


async def test_p5c11_p5c13_participant_reads_rules_asks_owner_joins_and_gets_a_contract(eco):
    ev = await open_event(eco)
    eco.a.llm.push("ask_owner", question="이 이벤트에 참가할까요?")
    eco.a.llm.push("join_event")
    await eco.a.events.watch_once(eco.a.ctx(eco.a.events))
    await settle(eco.a, eco.host)
    st = asst(eco.a).events[ev]
    assert st.joined and st.rules == RULES and eco.a.owner.asked
    prompt = json.dumps(next(x for x in eco.a.llm.prompts if x["schema"]["required"][0] == "thought"), ensure_ascii=False)
    assert "예시 이벤트 규칙" in prompt and "join_event" in prompt  # the agent sees the rules and the tools
    # the host's agent gets the join message and contracts the applicant
    assert any("참가 신청" in line for line in asst(eco.host).events[ev].transcript)
    eco.host.llm.push("contract", role="member", peer=eco.a.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "계속")
    await settle(eco.host)
    c = [x for x in eco.svc.ledger.chain if x["type"] == "contract"]
    assert len(c) == 1 and c[0]["payload"]["contractor"] == eco.a.identity.pub and c[0]["payload"]["rules_hash"] == h(RULES.encode())
    # b never applied: its assistant refuses a contract for this event
    eco.host.llm.push("contract", role="member", peer=eco.b.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "계속")
    await settle(eco.host)
    assert len([x for x in eco.svc.ledger.chain if x["type"] == "contract"]) == 1


async def test_p5c11_rules_text_must_match_the_ledger(eco):
    ev = await open_event(eco)
    eco.broker.notices[ev]["rules"] = RULES + "\n3. 몰래 더한 규칙"
    await eco.a.events.watch_once(eco.a.ctx(eco.a.events))
    assert ev not in asst(eco.a).events and any("공증된 것과 다름" in x["text"] for x in eco.log.tail(20))


async def joined(eco):
    ev = await open_event(eco)
    for p in (eco.a, eco.b):
        p.llm.push("join_event")
        await p.events.watch_once(p.ctx(p.events))
    await settle(eco.a, eco.b, eco.host)
    for p in (eco.a, eco.b):
        eco.host.llm.push("contract", role="member", peer=p.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "계약하라")
    await settle(eco.host)
    return ev


async def test_p5c11_p5c12_commit_reveal_messages_and_co_signed_attest(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    # a commits a value and sends the publish hash to b
    a.llm.push("commit", label="x-1", value="hello")
    await asst(a).feed(ctx(a), ev, "시작")
    await settle(a)
    sec = asst(a).events[ev].secrets["x-1"]
    a.llm.push("send", to=b.pen, text="내 등록", data={"label": "x-1", "publish_hash": sec["publish_hash"]})
    await asst(a).feed(ctx(a), ev, "보내라")
    await settle(a, b)
    tb = "\n".join(asst(b).events[ev].transcript)
    assert ("#" + sec["publish_hash"][:10]) in tb and a.pen in tb  # the signed message reached b's agent (shown with short refs)
    a.llm.push("my_reveal", label="x-1")
    await asst(a).feed(ctx(a), ev, "공개값")
    await settle(a)
    rv = await asst(a).tools["my_reveal"].run(asst(a), ctx(a), asst(a).events[ev], label="x-1")  # the real values, as code sees them
    b.llm.push("check_reveal", publish_hash=sec["publish_hash"], author=a.pen, label="x-1", value=rv["value"], salt=rv["salt"])
    b.llm.push("check_reveal", publish_hash=sec["publish_hash"], author=a.pen, label="x-1", value="other", salt=rv["salt"])
    await asst(b).feed(ctx(b), ev, "확인")
    await settle(b)
    results = [line for line in asst(b).events[ev].transcript if "check_reveal" in line and "결과" in line]
    assert '"match": true' in results[0] and '"match": false' in results[1]
    # a proposes a two-party attest; b co-signs; it lands with both signatures
    a.llm.push("propose_attest", kind="pair", subject="x", value={"winner": ""},
               parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "확인 제안")
    await settle(a, b)
    rid = next(iter(asst(b).events[ev].pending))
    b.llm.push("cosign", request_id=rid)
    await asst(b).feed(ctx(b), ev, "서명")
    await settle(a, b)
    at = [x for x in eco.svc.ledger.chain if x["type"] == "attest"]
    assert len(at) == 1 and set(at[0]["sigs"]) == {a.identity.pub, b.identity.pub} and at[0]["payload"]["group_id"] == "public"
    assert any("공동 확인 기록됨" in line for line in asst(a).events[ev].transcript)


async def test_p5c12_unsigned_or_forged_messages_are_refused(eco):
    ev = await joined(eco)
    r = await eco.b.handle({"op": "event_message", "event_id": ev, "text": "가짜", "data": {}, "url": "mem://x"})
    assert r["ok"] is False
    from arena.signing import sign_message
    m = dict({"op": "event_message", "event_id": ev, "text": "t", "data": {}, "url": eco.a.config.url}, **sign_message(eco.a.identity, "event_message"))
    m["pub"] = Identity.generate().pub
    assert (await eco.b.handle(m))["ok"] is False
    assert (await eco.b.handle(dict(m, event_id="unknown")))["ok"] is False


async def test_p5c11_decline_and_issuer_attest_and_close(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    a.llm.push("propose_attest", kind="pair", subject="y", value={"winner": "a"},
               parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "제안")
    await settle(a, b)
    rid = next(iter(asst(b).events[ev].pending))
    b.llm.push("decline", request_id=rid, reason="내가 본 것과 다르다")
    await asst(b).feed(ctx(b), ev, "거절")
    await settle(a, b)
    assert not [x for x in eco.svc.ledger.chain if x["type"] == "attest"]
    assert any("거절" in line and "내가 본 것과 다르다" in line for line in asst(a).events[ev].transcript)
    host = eco.host
    host.llm.push("propose_attest", kind="summary", subject="final", value={"ranking": []}, parties=[host.pen])
    await asst(host).feed(ctx(host), ev, "요약")
    await settle(host)
    at = [x for x in eco.svc.ledger.chain if x["type"] == "attest"]
    assert len(at) == 1 and at[0]["payload"]["parties"] == [host.identity.pub]
    host.llm.push("close_event", result_hash="0" * 64)  # no such entry: refused by code
    host.llm.push("close_event", result_hash=at[0]["hash"])
    await asst(host).feed(ctx(host), ev, "닫아라")
    await settle(host)
    assert any("이 이벤트의 원장 항목이어야" in x for x in asst(host).events[ev].transcript)
    assert eco.svc.ledger.chain[-1]["type"] == "close" and eco.svc.ledger.chain[-1]["payload"]["result_hash"] == at[0]["hash"]
    assert (await host.brokers["public"].list_notices(host.identity))["notices"] == []
    assert audit_chain(eco.svc.ledger.chain) == "ok"


async def test_p5c10_step_limit_bad_args_unknown_tool_and_host_only_tools(eco):
    ev = await joined(eco)
    a = eco.a
    before = len([x for x in a.llm.prompts if x["schema"].get("required", [None])[0] == "thought"])
    a.llm.push("commit", label="only-label")  # a required argument is missing
    a.llm.push("teleport")
    a.llm.push("close_event", result_hash="x")
    for _ in range(eco.s.assistant_max_steps + 5):
        a.llm.push("note", text="생각 중")
    await asst(a).feed(ctx(a), ev, "해 봐")
    await settle(a)
    tr = "\n".join(asst(a).events[ev].transcript)
    assert "인자가 맞지 않음" in tr and "없는 도구" in tr and "개최자만" in tr
    assert len([x for x in a.llm.prompts if x["schema"].get("required", [None])[0] == "thought"]) - before == eco.s.assistant_max_steps


async def test_p5c19_tools_offered_by_role_and_typed_arguments(eco):
    ev = await joined(eco)
    choose = next(x for x in reversed(eco.a.llm.prompts) if x["schema"].get("required", [None])[0] == "thought")
    allowed = choose["schema"]["properties"]["tool"]["enum"]
    assert "close_event" not in allowed and "contract" not in allowed and "commit" in allowed  # a participant never sees host tools
    host_choose = next(x for x in reversed(eco.host.llm.prompts) if x["schema"].get("required", [None])[0] == "thought")
    assert "close_event" in host_choose["schema"]["properties"]["tool"]["enum"]
    eco.a.llm.push("commit", label="k-1", value="v")
    await asst(eco.a).feed(ctx(eco.a), ev, "등록")
    await settle(eco.a)
    args_prompt = next(x for x in reversed(eco.a.llm.prompts) if x["schema"].get("required") == ["label", "value"])
    assert args_prompt["schema"]["properties"]["label"]["type"] == "string"
    assert "한국어" in choose["system"]


async def test_p5c16_an_assistant_restarted_continues_its_events(eco, tmp_path):
    ev = await joined(eco)
    eco.a.llm.push("commit", label="r-1", value="keep me")
    await asst(eco.a).feed(ctx(eco.a), ev, "등록")
    await settle(eco.a)
    old = asst(eco.a).events[ev]
    fresh = EventAssistant(eco.s)
    await fresh.restore(ctx(eco.a))  # e.g. the peer process restarted
    st = fresh.events[ev]
    assert st.joined and st.rules == RULES and st.secrets["r-1"]["value"] == "keep me" and st.transcript == old.transcript


async def test_p5c18_messages_carry_and_check_group_and_event(eco):
    ev = await joined(eco)
    msgs = []
    inner = eco.a.transport

    class Spy:
        async def call(self, url, msg, timeout=None, meta=None):
            msgs.append((msg.get("op"), meta))
            return await inner.call(url, msg, timeout, meta)
    eco.a.transport = Spy()
    eco.a.llm.push("send", to=eco.b.pen, text="안녕", data={})
    await asst(eco.a).feed(ctx(eco.a), ev, "보내라")
    await settle(eco.a, eco.b)
    assert msgs[0] == ("event_message", {"group_id": "public", "event_id": ev})
    # the same signed message under another group's head is refused
    body = asst(eco.a).sign_body(ctx(eco.a), {"op": "event_message", "event_id": ev, "group_id": "public", "text": "t", "data": {}, "url": eco.a.config.url})
    assert (await eco.b.handle(body, meta={"group_id": "g-other", "event_id": ev}))["ok"] is False
    assert (await eco.b.handle(body, meta={"group_id": "public", "event_id": ev}))["ok"] is True
    forged = dict(body, group_id="g-other")
    assert (await eco.b.handle(forged))["ok"] is False  # group_id is inside the signature


async def test_p5c15_assistant_reads_only_changes_and_notices_updates_and_closes(eco):
    ev = await open_event(eco)
    await eco.a.events.watch_once(eco.a.ctx(eco.a.events))
    await settle(eco.a)
    assert ev in asst(eco.a).events
    n = dict(eco.broker.notices[ev])
    n.pop("updated_at", None)
    n.pop("closed", None)
    n2 = dict(n, ver=n.get("ver", 1) + 1, text="일정이 바뀌었다")
    assert (await eco.host.brokers["public"].post_notice(eco.host.identity, n2))["ok"]
    await eco.a.events.watch_once(eco.a.ctx(eco.a.events))
    await settle(eco.a)
    assert any("공지 수정" in x for x in asst(eco.a).events[ev].transcript)
    await eco.host.brokers["public"].close_notice(eco.host.identity, ev)
    await eco.a.events.watch_once(eco.a.ctx(eco.a.events))
    await settle(eco.a)
    assert any("공지 마감" in x for x in asst(eco.a).events[ev].transcript)


async def test_p5c23_an_idle_event_wakes_its_assistant_with_backoff(eco):
    import dataclasses
    a = asst(eco.host)
    a.s = dataclasses.replace(a.s, assistant_idle_sec=0.05, assistant_idle_max_checks=2)
    ev = await open_event(eco)
    await settle(eco.host)
    st = a.events[ev]
    await a.idle_check(ctx(eco.host))
    assert st.idle_checks == 0  # not idle long enough yet
    await asyncio.sleep(0.06)
    await a.idle_check(ctx(eco.host))
    await settle(eco.host)
    assert st.idle_checks == 1 and sum("[점검]" in x for x in st.transcript) == 1
    await asyncio.sleep(0.06)
    await a.idle_check(ctx(eco.host))  # the wait doubled (0.1s): not yet
    assert st.idle_checks == 1
    await asyncio.sleep(0.06)
    await a.idle_check(ctx(eco.host))
    await settle(eco.host)
    assert st.idle_checks == 2
    await asyncio.sleep(0.3)
    await a.idle_check(ctx(eco.host))
    assert st.idle_checks == 2  # the cap: no endless self-talk
    await a.feed(ctx(eco.host), ev, "새 메시지")  # a real input resets the backoff
    await settle(eco.host)
    assert st.idle_checks == 0


async def test_p5c25_the_llm_sees_handles_and_short_refs_code_expands_them(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    st = asst(a).events[ev]
    prompts_before = len(a.llm.prompts)
    a.llm.push("commit", label="x-1", value="hello")
    await asst(a).feed(ctx(a), ev, "등록")
    await settle(a)
    full = st.secrets["x-1"]["publish_hash"]
    seen = json.dumps(a.llm.prompts[prompts_before:], ensure_ascii=False)
    assert a.identity.pub not in seen and eco.host.identity.pub not in seen and full not in seen  # no 64-hex strings reach the LLM
    assert a.pen in seen and ("#" + full[:10]) in seen
    # the LLM writes a handle and a short ref; the code sends to b's address and the message carries the full hash
    a.llm.push("send", to=b.pen, text="내 등록", data={"label": "x-1", "publish_hash": "#" + full[:10]})
    await asst(a).feed(ctx(a), ev, "보내라")
    await settle(a, b)
    assert any(full in line or ("#" + full[:10]) in line for line in asst(b).events[ev].transcript)
    # a two-party attest written with handles lands on the ledger with full public keys
    a.llm.push("propose_attest", kind="pair", subject="h", value={"winner": b.pen}, parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "제안")
    await settle(a, b)
    rid = next(iter(asst(b).events[ev].pending))
    b.llm.push("cosign", request_id=rid)
    await asst(b).feed(ctx(b), ev, "서명")
    await settle(a, b)
    at = [x for x in eco.svc.ledger.chain if x["type"] == "attest"][-1]["payload"]
    assert at["parties"] == [a.identity.pub, b.identity.pub] and at["value"]["winner"] == b.identity.pub


async def test_p5c25_a_handle_not_yet_known_is_found_on_the_broker(eco):
    ev = await joined(eco)
    host = eco.host
    stranger = eco.peer("stranger")
    await stranger.advertise()
    host.llm.push("send", to=stranger.pen, text="안녕", data={})
    await asst(host).feed(ctx(host), ev, "인사")
    await settle(host)
    assert '"ok": false' not in asst(host).events[ev].transcript[-2] or "unknown event" in asst(host).events[ev].transcript[-2]


async def test_p5c26_repeated_identical_actions_and_participant_only_tools(eco):
    ev = await joined(eco)
    host = eco.host
    choose = next(x for x in reversed(host.llm.prompts) if x["schema"].get("required", [None])[0] == "thought")
    assert "join_event" not in choose["schema"]["properties"]["tool"]["enum"]  # the host never sees participant-only tools
    for _ in range(3):
        host.llm.push("ask_owner", question="계속할까요?")
    await asst(host).feed(ctx(host), ev, "반복")
    await settle(host)
    assert len(host.owner.asked) == 1  # the same call twice in a row is not run again
    assert sum("이미 했다" in line for line in asst(host).events[ev].transcript) == 2


async def test_p5c27_contracts_only_with_applicants_checked_by_code(eco):
    ev = await open_event(eco)
    await settle(eco.host)
    stranger = eco.peer("stranger2")
    await stranger.advertise()
    eco.a.llm.push("join_event")
    await eco.a.events.watch_once(eco.a.ctx(eco.a.events))
    await settle(eco.a, eco.host)
    st = asst(eco.host).events[ev]
    assert st.applicants == [eco.a.identity.pub]  # recorded by code from the signed join with the right rules hash
    assert any("[코드 확인] 참가 신청" in x for x in st.transcript)
    eco.host.llm.push("contract", role="member", peer=stranger.pen)  # never applied
    eco.host.llm.push("contract", role="member", peer=eco.a.pen)
    await asst(eco.host).feed(ctx(eco.host), ev, "계약")
    await settle(eco.host)
    contracts = [x["payload"]["contractor"] for x in eco.svc.ledger.chain if x["type"] == "contract"]
    assert contracts == [eco.a.identity.pub]
    assert any("참가 신청한 peer나 그 역할을 프로필에 내건 peer만" in x for x in st.transcript)


async def test_p5c27_reveal_records_are_checked_by_code_and_bad_ones_block_signing(eco):
    ev = await joined(eco)
    a, b = eco.a, eco.b
    a.llm.push("commit", label="r-1", value="바위")
    await asst(a).feed(ctx(a), ev, "등록")
    await settle(a)
    good = await asst(a).tools["my_reveal"].run(asst(a), ctx(a), asst(a).events[ev], label="r-1")
    assert set(good) >= {"author", "label", "value", "salt", "publish_hash"}
    bad = dict(good, value="보")  # a reveal that does not match its commit
    # a message carrying reveal records: the code checks them and says so in b's input
    a.llm.push("send", to=b.pen, text="공개", data={"mine": good})
    await asst(a).feed(ctx(a), ev, "공개")
    await settle(a, b)
    tb = "\n".join(asst(b).events[ev].transcript)
    assert "[코드 확인] 공개값 1건 모두 원장과 일치" in tb
    # a co-signed attest whose value holds a mismatching reveal: proposing is refused by code
    a.llm.push("propose_attest", kind="pair", subject="r", value={"a": bad}, parties=[a.pen, b.pen])
    await asst(a).feed(ctx(a), ev, "제안")
    await settle(a, b)
    assert any("공개값이 원장과 맞지 않" in x for x in asst(a).events[ev].transcript) and not asst(b).events[ev].pending
    # and if a forged request arrives anyway, cosign is refused by code
    st_b = asst(b).events[ev]
    p = {"event_id": ev, "kind": "pair", "subject": "r2", "value": {"a": bad}, "parties": [a.identity.pub, b.identity.pub], "nonce": "n", "group_id": "public"}
    req = asst(a).sign_body(ctx(a), {"op": "attest_request", "event_id": ev, "group_id": "public", "request_id": "forged", "payload": p, "url": a.config.url})
    assert (await b.handle(req))["ok"]
    await settle(b)
    assert "[코드 확인] 공개값 1건 중 원장과 맞지 않음" in "\n".join(st_b.transcript)
    b.llm.push("cosign", request_id="forged")
    await asst(b).feed(ctx(b), ev, "서명")
    await settle(a, b)
    assert any("서명할 수 없다" in x for x in st_b.transcript)
    assert not [x for x in eco.svc.ledger.chain if x["type"] == "attest" and x["payload"]["subject"] == "r2"]
