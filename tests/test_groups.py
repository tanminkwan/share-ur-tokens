"""P6-N1..N3: a broker group without a ledger. The founder's declaration lives at the group's brokers; peers read it and
the code keeps what needs a ledger out of such a group; later the founder attaches a ledger and from then on events are
recorded (user 2026-11-02: "non-recorder 모드로 broker group 단위로 사용도 가능할 수 있겠다")."""
import asyncio
import dataclasses
import io
import json

import httpx
import pytest

from arena.a2a import LocalTransport
from arena.broker.api import build_broker_app
from arena.broker.client import BrokerClient, InMemoryBrokerClient
from arena.broker.neighbors import InMemoryNeighbors, NoNeighbors
from arena.broker.service import BrokerService
from arena.broker.store import FileBrokerStore
from arena.crypto import Identity
from arena.events import EventLog
from arena.genesis import record_genesis
from arena.groups.cli import parser, run
from arena.groups.decl import declaration_error, group_declaration, next_error
from arena.groups.flows import attach_ledger, declare_group
from arena.ledger import MemoryStore
from arena.llm import NoLLM
from arena.peer.area import LocalFolderArea
from arena.peer.assistant import EventAssistant
from arena.peer.events import announce_event
from arena.peer.home import PeerHome
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.peer.record_role import RecordRole
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from arena.search import BM25Searcher
from tests.test_event_apps import RULES, Runner, RUNNER_ID
from arena.peer.plugin import app_ref


def broker(s, gid="g-team", owner=None, neighbors=None, gw=None, store=None, ident=None):
    return BrokerService(s, ident or Identity.generate(), BM25Searcher(), gw or NoNeighbors(), name=gid, neighbors=neighbors or [],
                         group_id=gid, owner_pub=owner, store=store)


# ---------------- P6-N1: the declaration at the brokers ----------------
async def test_the_brokers_keep_the_founders_declaration_and_share_it(tmp_path, settings):
    founder, other = Identity.generate(), Identity.generate()
    s = dataclasses.replace(settings, broker_founder_pub=founder.pub)
    gw = InMemoryNeighbors()
    b2 = broker(s, gw=gw)
    b1 = broker(s, neighbors=["mem://b2"], gw=gw, store=FileBrokerStore(str(tmp_path / "b1.json")))
    gw.register("mem://b2", b2)
    d = group_declaration("g-team", founder.pub, False, [b1.identity.pub, b2.identity.pub])
    assert (await b1.declare(d, other.sign(d)))["error"] == "a group declaration is signed by the group's founder"
    assert (await b1.declare(dict(d, closed=True), founder.sign(dict(d, closed=True))))["error"] == "closed must say what this group is"
    lone = dict(d, brokers=[b2.identity.pub])
    assert (await b1.declare(lone, founder.sign(lone)))["error"] == "this broker is not one of the group's brokers"
    wrong = dict(d, group_id="g-x")
    assert (await b1.declare(wrong, founder.sign(wrong)))["error"] == "declaration of another group"
    assert "ver counts from 1" in (await b1.declare(dict(d, ver=0), founder.sign(dict(d, ver=0))))["error"]
    assert (await b1.declare(d, founder.sign(d))) == {"ok": True}
    assert b2.group()["declaration"] == d  # shared with the neighbor
    assert (await b1.declare(d, founder.sign(d)))["unchanged"]
    assert (await b1.declare(dict(d, brokers=[b1.identity.pub]), founder.sign(dict(d, brokers=[b1.identity.pub]))))["error"] == "older or same version"
    again = broker(s, store=FileBrokerStore(str(tmp_path / "b1.json")), ident=b1.identity)
    assert again.group()["declaration"] == d and again.group()["founder"] == founder.pub  # kept across a restart
    # the genesis group and a broker with no founder take no declaration; a closed group's owner is its founder
    gen = broker(s, gid=settings.genesis_group_id)
    assert "genesis group" in (await gen.declare(d, founder.sign(d)))["error"] and gen.group()["genesis"]
    nobody = broker(settings)
    assert "founder" in (await nobody.declare(d, founder.sign(d)))["error"]
    boss = Identity.generate()
    closed = broker(settings, owner=boss.pub)
    cd = group_declaration("g-team", boss.pub, True, [closed.identity.pub])
    assert (await closed.declare(cd, boss.sign(cd)))["ok"] and closed.group()["founder"] == boss.pub


def test_the_declaration_shape_and_its_next_version():
    f, b = "a" * 64, "b" * 64
    d = group_declaration("g", f, False, [b])
    assert declaration_error(d) is None
    assert declaration_error(dict(d, extra=1)) and declaration_error(dict(d, founder="x")) and declaration_error(dict(d, brokers=[]))
    assert declaration_error(dict(d, closed="no")) and declaration_error(dict(d, group_id=""))
    led = {"ledger_id": "c" * 64, "recorder_url": "http://rec", "recorder": "d" * 64, "entry": "e" * 64}
    assert declaration_error(dict(d, ledger=led)) is None
    assert "http" in declaration_error(dict(d, ledger=dict(led, recorder_url="ftp://x")))
    assert "hex64" in declaration_error(dict(d, ledger=dict(led, entry="z")))
    assert "{ledger_id" in declaration_error(dict(d, ledger={"ledger_id": "c" * 64}))
    v2 = dict(d, ver=2, ledger=led)
    assert next_error(d, v2) is None and next_error(None, d) is None
    assert next_error(d, dict(v2, founder="f" * 64)) == "the same group keeps its founder"
    assert next_error(v2, dict(v2, ver=3, ledger=None)) == "a ledger once attached stays (the same ledger_id)"
    assert next_error(v2, dict(v2, ver=3, ledger=dict(led, ledger_id="9" * 64))) == "a ledger once attached stays (the same ledger_id)"
    assert next_error(v2, dict(v2, ver=3, ledger=dict(led, recorder_url="http://moved"))) is None  # only the address moves


async def test_the_declaration_over_http(settings):
    founder = Identity.generate()
    svc = broker(dataclasses.replace(settings, broker_founder_pub=founder.pub))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_broker_app(svc)), base_url="http://broker") as hc:
        c = BrokerClient("http://broker", settings, http_client=hc)
        d = group_declaration("g-team", founder.pub, False, [svc.identity.pub])
        assert (await c.declare_group(Identity.generate(), d))["ok"] is False
        assert (await c.declare_group(founder, d))["ok"]
        g = await c.group()
        assert g["declaration"] == d and g["genesis"] is False and g["founder"] == founder.pub


# ---------------- a world: the genesis group with the recorder, and a team group ----------------
class World:
    def __init__(self, tmp, settings, founder=None):
        self.founder = founder or Identity.generate()
        self.s = dataclasses.replace(settings, recorder_require_group=True, broker_founder_pub=self.founder.pub, group_mode_ttl_sec=0.0)
        self.t, self.log, self.tmp = LocalTransport(), EventLog(echo=False), tmp
        self.public = BrokerService(self.s, Identity.generate(), BM25Searcher(), NoNeighbors(), name="genesis", neighbors=[])
        self.team = broker(self.s)
        self.god, rec = Identity.generate(), Identity.generate()
        self.svc = RecorderService.build(self.s, rec, MemoryStore(), readers=[])
        self.rec = self.peer("rec", [RecordRole(self.svc, "http://rec/api")], identity=rec, groups=("public",))

    def peer(self, name, apps, identity=None, groups=("public", "team")):
        (self.tmp / name).mkdir()
        (self.tmp / name / "notes.md").write_text(f"- {name}\n", encoding="utf-8")
        boards = {"public": self.public, "team": self.team}
        p = Peer(identity or Identity.generate(), self.s, PeerConfig(url=f"mem://{name}"), LocalFolderArea(str(self.tmp / name), self.s),
                 NoOwner(), NoLLM(), self.t, self.log, brokers={g: InMemoryBrokerClient(boards[g]) for g in groups}, apps=apps)
        p.recorder_factory = lambda u: InMemoryRecorderClient(self.svc)
        self.t.register(p.config.url, p.handle)
        return p

    async def boot(self, *peers):
        assert (await record_genesis(self.svc, self.god, self.s, self.public.identity.pub, self.rec.identity.pub))["ok"]
        for p in (self.rec, *peers):
            await p.advertise()

    async def declare(self):
        r = await declare_group(self.founder, InMemoryBrokerClient(self.team))
        assert r["ok"], r
        return r["declaration"]

    async def attach(self):
        return await attach_ledger(self.founder, InMemoryBrokerClient(self.team), InMemoryRecorderClient(self.svc), "http://rec/api")


async def route(*peers):
    for p in peers:
        await p.events.watch_once(p.ctx(p.events))
    await asyncio.sleep(0.02)


def entries_of(w, kind):
    return [e for e in w.svc.ledger.chain if e["type"] == kind]


# ---------------- P6-N2: reading the group's mode; what the code keeps out ----------------
async def test_a_peer_reads_whether_its_group_keeps_a_ledger(tmp_path, settings):
    w = World(tmp_path, settings)
    p = w.peer("p", [])
    await w.boot(p)
    assert (await p.group_mode("public"))["ledger"] is True  # the genesis group
    m = await p.group_mode("team")
    assert m["ledger"] and "no declaration" in m["why"]  # as before: the stricter way
    forged = group_declaration("g-team", w.founder.pub, False, [w.team.identity.pub])
    w.team.declaration = {"decl": forged, "sig": Identity.generate().sign(forged)}  # a broker cannot forge the founder's word
    m = await p.group_mode("team")
    assert m["ledger"] and "does not check out" in m["why"]
    w.team.declaration = None
    await w.declare()
    m = await p.group_mode("team")
    assert m["ledger"] is False and m["declaration"]["ledger"] is None
    # remembered for the TTL, read again when asked fresh
    q = w.peer("q", [])
    q.groups.settings = lambda: dataclasses.replace(w.s, group_mode_ttl_sec=60.0)
    assert (await q.group_mode("team"))["ledger"] is False
    assert (await w.attach())["ok"]
    assert (await q.group_mode("team"))["ledger"] is False and (await q.group_mode("team", fresh=True))["ledger"] is True
    q.brokers["team"] = None  # a broker that does not answer: the stricter way
    assert (await q.group_mode("team", fresh=True))["ledger"] is True


async def test_an_event_in_a_group_without_a_ledger_is_its_notice_alone(tmp_path, settings):
    w = World(tmp_path, settings)
    host, runner = w.peer("host", []), Runner()
    part = w.peer("part", [runner])
    await w.boot(host, part)
    await w.declare()
    before = len(w.svc.ledger.chain)
    out = await announce_event(host.ctx(host.events), group="team", title="t", kind="test", rules=RULES, policy={}, mode="app", apps=[app_ref(runner)])
    assert out["ledger"] is False and out["event_hash"] is None and "event_hash" not in out["notice"] and "recorder_url" not in out["notice"]
    assert len(w.svc.ledger.chain) == before  # nothing recorded
    await route(part)
    assert runner.got == [(out["event_id"], "new")]  # the issuer's signature is enough here
    with pytest.raises(ValueError, match="원장이 없다"):
        await announce_event(host.ctx(host.events), group="team", title="t", kind="test", rules=RULES, policy={}, mode="app",
                             apps=[app_ref(runner)], elements={"intake": {}})
    # a notice with elements posted straight to the board is not taken: the ledger would keep them, and there is none
    n = dict(out["notice"], notice_id="ev-elements", elements={"intake": {}})
    assert (await InMemoryBrokerClient(w.team).post_notice(host.identity, n))["ok"]
    # and in a ledger group (the genesis group), a notice without a declaration is not taken
    pn = dict(out["notice"], notice_id="ev-public", group_id=settings.genesis_group_id)
    assert (await InMemoryBrokerClient(w.public).post_notice(host.identity, pn))["ok"]
    await route(part)
    assert [x[0] for x in runner.got] == [out["event_id"]]
    lines = [x["text"] for x in w.log.items if x.get("actor") == part.pen]
    assert any("기본 요소나 코드표" in t for t in lines) and any("공지에 원장 선언이 없음" in t for t in lines)


async def test_the_assistant_offers_no_ledger_tools_where_there_is_no_ledger(tmp_path, settings):
    w = World(tmp_path, settings)
    ha, pa = EventAssistant(w.s, group="team"), EventAssistant(w.s, group="team")
    host, part = w.peer("host", [ha]), w.peer("part", [pa])
    await w.boot(host, part)
    await w.declare()
    hctx = host.ctx(ha)
    ev = await ha.host_event(hctx, title="말로만 하는 모임", kind="talk", rules="말로만 정한다", policy={}, instruction="시작")
    st = ha.events[ev]
    assert st.on_ledger is False and st.recorder_url == "" and st.event_hash == ""
    offered = ha.toolbox.offered(st)
    for name in ("contract", "publish_text", "commit", "reveal", "verify", "event_progress", "propose_attest", "assign", "close_event", "ask_endorsement"):
        assert name not in offered
    assert {"send", "solicit", "call_service", "ask_owner", "remind", "close_notice"} <= set(offered)
    assert "원장 없음" in ha._system(hctx, st)
    r = await ha.toolbox.run(ha, hctx, st, "contract", {"role": "x", "peer": part.pen})  # even by hand, refused by code
    assert "원장이 없어" in r["error"]
    r = await ha.toolbox.run(ha, hctx, st, "call_service", {"peer": part.pen, "op": "x", "input_json": "{}", "subject": "m1"})
    assert "subject" in r["error"]
    assert await ha.progress_entries(hctx, st) == []
    await route(part)
    pst = pa.events[ev]
    assert pst.on_ledger is False and "원장이 없다" in pst.transcript[-1]
    assert "close_notice" not in pa.toolbox.offered(pst)  # the host closes
    r = await ha.owner_run(hctx, ev, "close_notice", {})
    assert r["ok"] and st.closed and w.team.notice_meta[ev]["closed"]
    # in a ledger event the ledger-free tool is not offered, and refused by hand
    st2 = dataclasses.replace(st, recorder_url="http://rec/api", closed=False)
    assert "close_notice" not in ha.toolbox.offered(st2)
    assert "원장이 있는" in (await ha.toolbox.run(ha, hctx, st2, "close_notice", {}))["error"]


# ---------------- P6-N3: attaching a ledger later ----------------
async def test_attaching_a_ledger_later_records_from_then_on(tmp_path, settings):
    w = World(tmp_path, settings)
    host, runner, runner2 = w.peer("host", []), Runner(), Runner()
    part = w.peer("part", [runner])
    await w.boot(host, part)
    assert (await w.attach())["error"] == "declare the group first (declare)"
    await w.declare()
    old = await announce_event(host.ctx(host.events), group="team", title="before", kind="test", rules=RULES, policy={}, mode="app",
                               apps=[app_ref(runner)])
    await route(part)
    r = await w.attach()
    assert r["ok"] and r["declaration"]["ver"] == 2 and r["declaration"]["ledger"]["entry"] == r["entry"]
    g = entries_of(w, "group")
    assert len(g) == 1 and g[0]["payload"]["group_id"] == "g-team" and g[0]["payload"]["founder"] == w.founder.pub
    assert not any(e["payload"].get("event_id") == old["event_id"] for e in w.svc.ledger.chain)  # what was said before is not recorded
    m = await part.group_mode("team")
    assert m["ledger"] and m["proven"] and m["attached"]["ledger_id"] == w.svc.ledger.chain[0]["hash"]
    assert (await w.attach())["error"] == "this group already keeps a ledger"
    detach = dict(r["declaration"], ver=3, ledger=None)
    assert (await w.team.declare(detach, w.founder.sign(detach)))["error"] == "a ledger once attached stays (the same ledger_id)"
    # a new event is declared on the group's ledger, without being told where
    new = await announce_event(host.ctx(host.events), group="team", title="after", kind="test", rules=RULES, policy={}, mode="app",
                               apps=[app_ref(runner)])
    assert new["ledger"] and new["notice"]["recorder_url"] == "http://rec/api"
    assert any(e["type"] == "event" and e["payload"]["event_id"] == new["event_id"] and e["payload"]["group_id"] == "g-team" for e in w.svc.ledger.chain)
    # a notice without a declaration is no longer taken; the event already under way goes on (its updates still arrive)
    late = dict(old["notice"], notice_id="ev-late")
    assert (await InMemoryBrokerClient(w.team).post_notice(host.identity, late))["ok"]
    assert (await InMemoryBrokerClient(w.team).post_notice(host.identity, dict(old["notice"], ver=2)))["ok"]
    await route(part)
    assert runner.got == [(old["event_id"], "new"), (new["event_id"], "new"), (old["event_id"], "updated")]
    # a declaration naming a ledger the peer cannot prove keeps the group a ledger group, unproven
    w.team.declaration["decl"] = dict(r["declaration"], ledger=dict(r["declaration"]["ledger"], entry="0" * 64))
    w.team.declaration["sig"] = w.founder.sign(w.team.declaration["decl"])
    m = await part.group_mode("team")
    assert m["ledger"] and not m["proven"] and "no group entry" in m["why"]
    other = w.peer("other", [runner2], groups=("team",))
    await other.advertise()
    await route(other)
    assert runner2.got == [(new["event_id"], "new")]  # still checked on its own ledger declaration


async def test_an_event_on_another_ledger_than_the_groups_is_not_taken(tmp_path, settings):
    w = World(tmp_path, settings)
    host, runner = w.peer("host", []), Runner()
    part = w.peer("part", [runner])
    await w.boot(host, part)
    await w.declare()
    assert (await w.attach())["ok"]
    out = await announce_event(host.ctx(host.events), group="team", title="t", kind="test", rules=RULES, policy={}, mode="app", apps=[app_ref(runner)])
    real = part.ledger_id
    part.ledger_id = lambda url: _const("9" * 64)
    part.groups.ledger_id = real  # the group's ledger itself still proves out
    await route(part)
    assert runner.got == []
    assert any("그룹에 붙은 원장이 아닌 곳" in x["text"] for x in w.log.items if x.get("actor") == part.pen) and out["ledger"]


async def _const(v):
    return v


async def test_the_founder_runs_it_from_the_command_line(tmp_path, settings):
    home = PeerHome(str(tmp_path / "founder"), settings)
    w = World(tmp_path, settings, founder=home.identity())
    await w.boot()
    brokers = lambda url: InMemoryBrokerClient(w.team)
    recorders = lambda url: InMemoryRecorderClient(w.svc)

    async def cli(*args):
        out = io.StringIO()
        code = await run(parser().parse_args(list(args)), w.s, out=out, broker_of=brokers, recorder_of=recorders)
        return code, json.loads(out.getvalue())
    code, r = await cli("show", "--broker", "http://team")
    assert code == 0 and r["declaration"] is None
    code, r = await cli("declare", "--home", str(tmp_path / "founder"), "--broker", "http://team")
    assert code == 0 and r["declaration"]["brokers"] == [w.team.identity.pub] and r["declaration"]["ledger"] is None
    code, r = await cli("attach", "--home", str(tmp_path / "founder"), "--broker", "http://team")
    assert code == 1 and "--recorder" in r["error"]
    code, r = await cli("attach", "--home", str(tmp_path / "founder"), "--broker", "http://team", "--recorder", "http://rec")
    assert code == 0 and r["declaration"]["ver"] == 2 and "receipt" not in r
    code, r = await cli("declare", "--home", str(tmp_path / "founder"), "--broker", "http://team")
    assert code == 0 and r["declaration"]["ver"] == 3 and r["declaration"]["ledger"]  # a new version keeps the ledger
    out = io.StringIO()
    code = await run(parser().parse_args(["declare", "--home", str(tmp_path / "founder"), "--broker", "http://genesis"]), w.s,
                     out=out, broker_of=lambda url: InMemoryBrokerClient(w.public))
    assert code == 1 and "genesis group" in json.loads(out.getvalue())["error"]


async def test_attaching_stops_when_the_ledger_refuses(tmp_path, settings):
    w = World(tmp_path, settings)
    bare = RecorderService.build(w.s, Identity.generate(), MemoryStore(), readers=[])  # never begun by a genesis
    await w.declare()
    r = await attach_ledger(w.founder, InMemoryBrokerClient(w.team), InMemoryRecorderClient(bare), "http://bare")
    assert "cannot prove its ledger" in r["error"]
    await w.boot()
    p = {"group_id": "g-team", "founder": w.god.pub, "closed": False, "brokers": [], "ledger_id": w.svc.ledger.chain[0]["hash"]}
    assert (await w.svc.record("group", p, {w.god.pub: w.god.sign(p)}))["ok"]  # someone declared g-team on this ledger first
    r = await w.attach()
    assert "refused the group entry" in r["error"] and w.team.group()["declaration"]["ledger"] is None
