"""P5-E: events name the app that runs them and how; apps carry a unique id; the built-in router hands events over."""
import asyncio
import dataclasses

import pytest

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.events import EventLog
from arena.genesis import record_genesis
from arena.ledger import MemoryStore
from arena.llm import NoLLM
from arena.peer.area import LocalFolderArea
from arena.peer.assistant import EventAssistant
from arena.peer.events import announce_event
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.peer.plugin import BaseApp, app_fingerprint, app_ref, version_ok
from arena.peer.record_role import RecordRole
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from arena.search import BM25Searcher

RUNNER_ID = "3f2b6a1c-9d4e-4b8a-a6c1-0e7f5d2c9b31"
RULES = "[규칙] 이 이벤트는 runner 앱이 처리한다."


class Runner(BaseApp):
    name, version, app_id = "runner", "1.2", RUNNER_ID

    def __init__(self):
        self.got = []

    async def on_event(self, ctx, notice, change):
        self.got.append((notice["notice_id"], change))


class World:
    def __init__(self, tmp, settings):
        self.s = dataclasses.replace(settings, recorder_require_group=True)
        self.t, self.log, self.tmp = LocalTransport(), EventLog(echo=False), tmp
        self.public = BrokerService(self.s, Identity.generate(), BM25Searcher(), NoNeighbors(), name="genesis", neighbors=[])
        self.other = BrokerService(self.s, Identity.generate(), BM25Searcher(), NoNeighbors(), name="team", neighbors=[], group_id="g-team")
        self.god, rec = Identity.generate(), Identity.generate()
        self.svc = RecorderService.build(self.s, rec, MemoryStore(), readers=[])
        self.rec = self.peer("rec", [RecordRole(self.svc, "mem://rec/api")], identity=rec)

    def peer(self, name, apps, identity=None, groups=("public",)):
        (self.tmp / name).mkdir()
        (self.tmp / name / "notes.md").write_text(f"- {name}\n", encoding="utf-8")
        boards = {"public": self.public, "team": self.other}
        p = Peer(identity or Identity.generate(), self.s, PeerConfig(url=f"mem://{name}"), LocalFolderArea(str(self.tmp / name), self.s),
                 NoOwner(), NoLLM(), self.t, self.log, brokers={g: InMemoryBrokerClient(boards[g]) for g in groups}, apps=apps)
        p.recorder_factory = lambda u: InMemoryRecorderClient(self.svc)
        self.t.register(p.config.url, p.handle)
        return p

    async def boot(self, *peers):
        assert (await record_genesis(self.svc, self.god, self.s, self.public.identity.pub, self.rec.identity.pub))["ok"]
        g = {"group_id": "g-team", "founder": self.god.pub, "closed": False, "brokers": [self.other.identity.pub],
             "ledger_id": self.svc.ledger.chain[0]["hash"]}
        assert (await self.svc.record("group", g, {self.god.pub: self.god.sign(g)}))["ok"]
        for p in (self.rec, *peers):
            await p.advertise()


async def announce(host, mode, apps=(), group="public"):
    rec = (await host.brokers["public"].find("기록", role="record", identity=host.identity))["peers"][0]  # the recorder lives in the public group
    return await announce_event(host.ctx(host.events), group=group, title="t", kind="test", rules=RULES, policy={}, mode=mode,
                                apps=list(apps), recorder=rec)


async def route(*peers):
    for p in peers:
        await p.events.watch_once(p.ctx(p.events))
    await asyncio.sleep(0.02)


@pytest.fixture
async def w(tmp_path, settings):
    w = World(tmp_path, settings)
    w.host = w.peer("host", [Runner()])
    w.with_app, w.without, w.old = w.peer("with", [Runner()]), w.peer("without", []), w.peer("old", [])
    w.old_runner = Runner()
    w.old_runner.version = "1.0"
    await w.old.install(w.old_runner)
    await w.boot(w.host, w.with_app, w.without, w.old)
    return w


def test_p5e1_app_ids_fingerprints_and_versions(tmp_path, settings):
    assert version_ok("1.2", "1.0") and version_ok("1.2.3", "1.2") and not version_ok("1.0", "1.2") and not version_ok("2.0", "1.0")
    assert app_fingerprint(Runner()) == app_fingerprint(Runner()) and len(app_fingerprint(Runner())) == 64
    w = World(tmp_path, settings)

    class Bad(BaseApp):
        name, version, app_id = "bad", "1.0", "not-a-uuid"

        def ops(self):
            return {}

    class Twin(Runner):
        name = "twin"
    with pytest.raises(ValueError, match="UUID"):
        w.peer("a", [Bad()])
    with pytest.raises(ValueError, match="app_id .* registered twice"):
        w.peer("b", [Runner(), Twin()])


async def test_p5e2_p5e6_mode_and_app_list_are_separate_notarized_blocks(w):
    apps = [app_ref(Runner(), pin_code=True)]
    out = await announce(w.host, "app", apps)
    decl = next(e for e in w.svc.ledger.chain if e["type"] == "event")["payload"]
    assert decl["mode"] == "app" and decl["apps"] == apps and decl["rules_hash"] and "policy" in decl  # separate blocks
    assert out["notice"]["mode"] == "app" and out["notice"]["apps"] == apps and out["notice"]["rules"] == RULES
    v = await w.host.recorder("mem://rec/api").verify(out["event_hash"])
    assert v["mode"] == "app" and v["apps"] == apps
    with pytest.raises(ValueError):
        await announce(w.host, "sometimes", apps)
    with pytest.raises(ValueError):
        await announce(w.host, "app", [])  # an app mode needs a non-empty app list
    bad = {"event_id": "x", "issuer": w.host.identity.pub, "kind": "k", "policy": {}, "group_id": "public",
           "mode": "app", "apps": [{"id": "nope", "version": "1"}], "ledger_id": w.svc.ledger.chain[0]["hash"]}
    r = await w.svc.record("event", bad, {w.host.identity.pub: w.host.sign(bad)})
    assert r["error"] == "bad mode or app list"


async def test_p5e3_p5e4_mode_app_needs_the_installed_app_of_a_fitting_version(w):
    ev = (await announce(w.host, "app", [app_ref(Runner())]))["event_id"]
    await route(w.with_app, w.without, w.old)
    assert w.with_app.app(Runner).got == [(ev, "new")]
    assert w.old_runner.got == []  # installed 1.0, the event needs 1.2
    texts = [e["text"] for e in w.log.tail(50) if e["kind"] == "events"]
    assert any("설치되어 있지 않음" in t for t in texts) and any("요구 버전" in t for t in texts)


async def test_p5e4_pinned_code_hash_must_match(w):
    await announce(w.host, "app", [dict(app_ref(Runner()), hash="0" * 64)])
    await route(w.with_app)
    assert w.with_app.app(Runner).got == [] and any("코드가 이벤트가 지정한 코드와 다름" in e["text"] for e in w.log.tail(20))


async def test_p5e3_modes_assistant_and_app_or_assistant(tmp_path, settings):
    w = World(tmp_path, settings)
    host = w.peer("host", [Runner()])
    both = w.peer("both", [Runner(), EventAssistant(w.s)])
    only_assistant = w.peer("asst", [EventAssistant(w.s)])
    await w.boot(host, both, only_assistant)
    e1 = (await announce(host, "app_or_assistant", [app_ref(Runner())]))["event_id"]
    e2 = (await announce(host, "assistant"))["event_id"]
    await route(both, only_assistant)
    assert both.app(Runner).got == [(e1, "new")]  # has the app: the app runs it
    assert e1 in only_assistant.app(EventAssistant).events  # no app: the basic assistant runs it
    assert e2 in both.app(EventAssistant).events and e2 in only_assistant.app(EventAssistant).events


async def test_p5e4_a_notice_whose_app_differs_from_the_ledger_is_ignored(w):
    out = await announce(w.host, "app", [app_ref(Runner())])
    w.public.notices[out["event_id"]]["apps"] = [dict(out["notice"]["apps"][0], version="1.0")]  # someone edits the posted app list
    await route(w.with_app)
    assert w.with_app.app(Runner).got == [] and any("공증된 것과 다름" in e["text"] for e in w.log.tail(20))


async def test_p5e5_updates_and_closes_go_to_the_same_app_and_all_groups_are_read(tmp_path, settings):
    w = World(tmp_path, settings)
    host = w.peer("host", [Runner()], groups=("public", "team"))
    member = w.peer("member", [Runner()], groups=("public", "team"))
    await w.boot(host, member)
    a = await announce(host, "app", [app_ref(Runner())])
    b = await announce(host, "app", [app_ref(Runner())], group="team")
    await route(member)
    assert sorted(member.app(Runner).got) == sorted([(a["event_id"], "new"), (b["event_id"], "new")])  # both groups
    n2 = dict(a["notice"], ver=2, text="바뀜")
    assert (await host.brokers["public"].post_notice(host.identity, n2))["ok"]
    await host.brokers["team"].close_notice(host.identity, b["event_id"])
    await route(member)
    assert (a["event_id"], "updated") in member.app(Runner).got and (b["event_id"], "closed") in member.app(Runner).got



class Helper(BaseApp):
    name, version, app_id = "helper", "2.0", "8a1c2d3e-4f50-4a61-b7c8-d9e0f1a2b3c4"

    def __init__(self):
        self.got = []

    async def on_event(self, ctx, notice, change):
        self.got.append((notice["notice_id"], change))


async def test_p5e2_every_required_app_in_the_list_and_all_handlers_get_it(tmp_path, settings):
    w = World(tmp_path, settings)
    host = w.peer("host", [Runner()])
    both = w.peer("both", [Runner(), Helper()])
    runner_only = w.peer("runner", [Runner()])
    await w.boot(host, both, runner_only)
    e1 = (await announce(host, "app", [app_ref(Runner()), app_ref(Helper())]))["event_id"]
    e2 = (await announce(host, "app", [app_ref(Runner()), app_ref(Helper(), required=False)]))["event_id"]
    await route(both, runner_only)
    assert both.app(Runner).got == [(e1, "new"), (e2, "new")] and both.app(Helper).got == [(e1, "new"), (e2, "new")]  # every handler in the list
    assert runner_only.app(Runner).got == [(e2, "new")]  # e1 needs Helper too; in e2 Helper is optional
    assert any("helper" in e["text"] and "설치되어 있지 않음" in e["text"] for e in w.log.tail(30))
