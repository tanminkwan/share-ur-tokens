"""The sphinx (dev/founding/requirements.md, user 2026-11-04): applications come in signed by the founder key, the person
behind the sphinx meets the applicant and says yes or no on the desk, yes gives a founding pass bound to that key."""
import asyncio
import dataclasses
import io
import json
import time

import pytest

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.config import ConfigError, Settings
from arena.crypto import Identity
from arena.events import EventLog
from arena.groups.cli import parser, run as cli_run
from arena.groups.flows import application, apply_to_sphinx, founding_pass
from arena.ledger.founding import make_pass, pass_body, pass_error
from arena.llm import NoLLM
from arena.peer.desk import DeskOwner, OwnerDesk
from arena.peer.home import PeerHome
from arena.peer.node import Peer, PeerConfig
from arena.peer.sphinx_role import SphinxRole
from tests.conftest import make_env
from tests.fakes import FakeOwner

DAY = 86400.0


# ---------------- the pass ----------------
def test_a_pass_is_signed_by_its_sphinx_and_bound_to_one_founder():
    sphinx, founder, other = Identity.generate(), Identity.generate(), Identity.generate()
    body = pass_body(founder.pub, sphinx.pub, 100.0, 200.0, "n1")
    p = make_pass(body, sphinx.sign(body))
    assert pass_error(p) is None and pass_error(p, founder=founder.pub, now=150, sphinxes={sphinx.pub}) is None
    assert "another founder" in pass_error(p, founder=other.pub)  # cannot be handed on
    assert "not valid now" in pass_error(p, now=250) and "not valid now" in pass_error(p, now=50)
    assert "not a sphinx here" in pass_error(p, sphinxes={other.pub})
    forged = make_pass(dict(body, founder=other.pub), p["sig"])
    assert "signature" in pass_error(forged)
    assert pass_error({"format": "x"}) == "not a founding pass"
    assert "names founder" in pass_error(make_pass({"founder": founder.pub}, "s"))
    assert "public keys" in pass_error(make_pass(dict(body, sphinx="zz"), "s"))
    assert "until after" in pass_error(make_pass(dict(body, until=50.0), "s"))
    assert "nonce" in pass_error(make_pass(dict(body, nonce=""), "s"))


# ---------------- the role on a person's peer ----------------
class World:
    def __init__(self, tmp, settings, **over):
        self.s = dataclasses.replace(settings, **over)
        self.tmp, self.home = tmp, PeerHome(str(tmp / "sphinx"), self.s)
        self.boot()

    def boot(self):
        self.desk = OwnerDesk(clock=time.time, keep=100)
        self.role = SphinxRole(self.s)
        self.peer = Peer(self.home.identity(), self.s, PeerConfig(url="mem://sphinx", operator="human"), self.home.area(),
                         DeskOwner(self.desk, self.s), NoLLM(), LocalTransport(), EventLog(echo=False), brokers={}, apps=[self.role],
                         home=self.home)
        return self

    async def ask(self, msg):
        return await self.peer.handle(msg)

    async def question(self, n=1, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            items = self.desk.list("open")
            if len(items) >= n:
                return items[-1]
            await asyncio.sleep(0.01)
        raise TimeoutError("no desk question")

    async def settle(self):
        await asyncio.gather(*[t for t in self.role._tasks.values()], return_exceptions=True)


async def test_an_application_must_be_signed_now_by_the_founder_key(tmp_path, settings):
    w, founder, other = World(tmp_path, settings), Identity.generate(), Identity.generate()
    good = application(founder, "독서 모임", "mailto:me@example.org", time.time())
    assert "an application is" in (await w.ask({"op": "sphinx.apply", "application": {"founder": founder.pub}, "sig": ""}))["error"]
    assert "public key" in (await w.ask(dict(good, application=dict(good["application"], founder="nope"))))["error"]
    long = application(founder, "x" * (settings.sphinx_purpose_max + 1), "c", time.time())
    assert "short text" in (await w.ask(long))["error"]
    assert "short text" in (await w.ask(application(founder, "p", "  ", time.time())))["error"]
    assert "signed now" in (await w.ask(application(founder, "p", "c", time.time() - 3600)))["error"]
    assert "founder key" in (await w.ask(dict(good, sig=other.sign(good["application"]))))["error"]
    assert w.desk.list("open") == []  # nothing reached the person


async def test_the_person_meets_the_applicant_and_says_yes(tmp_path, settings):
    w, founder = World(tmp_path, settings), Identity.generate()
    r = await apply_to_sphinx(founder, w.ask, "독서 모임 가지 그룹", "mailto:me@example.org", time.time())
    assert r["ok"] and r["status"] == "waiting"
    q = await w.question()
    assert founder.pub in q.body and "mailto:me@example.org" in q.body and "독서 모임" in q.body and "확인할 것" in q.body
    assert (await w.ask({"op": "sphinx.status", "application_id": r["application_id"]}))["status"] == "waiting"
    again = await apply_to_sphinx(founder, w.ask, "독서 모임", "mailto:me@example.org", time.time())
    assert again["application_id"] == r["application_id"] and len(w.desk.list("open")) == 1  # one at a time per founder
    w.desk.answer(q.id, {"yes": True, "why": "영상 통화로 확인"})
    await w.settle()
    got = await founding_pass(w.ask, r["application_id"], founder.pub)
    assert got["ok"] and got["status"] == "passed"
    p = got["pass"]
    assert pass_error(p, founder=founder.pub, now=time.time(), sphinxes={w.peer.identity.pub}) is None
    assert p["body"]["until"] - p["body"]["issued_at"] == pytest.approx(settings.sphinx_pass_days * DAY)
    info = await w.ask({"op": "sphinx.info"})
    assert info["issued_in_window"] == 1 and info["waiting"] == 0 and info["pub"] == w.peer.identity.pub
    held = await apply_to_sphinx(founder, w.ask, "또 하나", "mailto:me@example.org", time.time())
    assert held["status"] == "passed" and held["application_id"] == r["application_id"]  # a valid pass is not given twice
    assert (await founding_pass(w.ask, r["application_id"], Identity.generate().pub))["error"].startswith("the pass does not check out")
    assert (await w.ask({"op": "sphinx.status", "application_id": "nope"}))["error"] == "no such application"
    assert "그룹 생성 허락" in w.peer.offers() and w.role.profile_extra()["sphinx"]["found_branch"]


async def test_a_no_and_an_unanswered_question_are_told_apart(tmp_path, settings):
    w = World(tmp_path, settings)
    a, b = Identity.generate(), Identity.generate()
    ra = await apply_to_sphinx(a, w.ask, "p", "c", time.time())
    q = await w.question()
    w.desk.answer(q.id, {"yes": False, "why": "목적이 규약에 어긋남"})
    await w.settle()
    st = await w.ask({"op": "sphinx.status", "application_id": ra["application_id"]})
    assert st["status"] == "rejected" and st["why"] == "목적이 규약에 어긋남" and "pass" not in st
    (tmp_path / "w2").mkdir()
    w2 = World(tmp_path / "w2", settings, sphinx_decide_wait_sec=0.05)
    rb = await apply_to_sphinx(b, w2.ask, "p", "c", time.time())
    await w2.question()
    await w2.settle()
    st = await w2.ask({"op": "sphinx.status", "application_id": rb["application_id"]})
    assert st["status"] == "expired"  # nobody decided: not a rejection, apply again
    assert (await apply_to_sphinx(b, w2.ask, "p", "c", time.time()))["application_id"] != rb["application_id"]


async def test_the_sphinx_gives_at_most_its_cap_in_a_period(tmp_path, settings):
    w = World(tmp_path, settings, sphinx_cap_count=1)
    a, b, c = Identity.generate(), Identity.generate(), Identity.generate()
    ra = await apply_to_sphinx(a, w.ask, "p", "c", time.time())
    rb = await apply_to_sphinx(b, w.ask, "p", "c", time.time())  # both wait: the cap is counted on passes given
    await w.question(2)
    for q in w.desk.list("open"):
        w.desk.answer(q.id, {"yes": True, "why": "만남"})
    await w.settle()
    states = sorted([(await w.ask({"op": "sphinx.status", "application_id": x["application_id"]}))["status"] for x in (ra, rb)])
    assert states == ["passed", "rejected"]
    late = await apply_to_sphinx(c, w.ask, "p", "c", time.time())
    assert "apply later" in late["error"]
    w.peer.clock = lambda: time.time() + settings.sphinx_cap_days * DAY + 1  # the next period
    assert (await apply_to_sphinx(c, w.ask, "p", "c", w.peer.clock()))["ok"]


async def test_after_a_restart_the_person_is_asked_again(tmp_path, settings):
    w, founder = World(tmp_path, settings), Identity.generate()
    r = await apply_to_sphinx(founder, w.ask, "p", "c", time.time())
    await w.question()
    for t in w.role._tasks.values():
        t.cancel()
    w.boot()  # the same home, a new process
    await w.role.start(w.peer.ctx(w.role))
    q = await w.question()
    w.desk.answer(q.id, {"yes": True, "why": "다시 만남"})
    await w.settle()
    assert (await w.ask({"op": "sphinx.status", "application_id": r["application_id"]}))["status"] == "passed"


async def test_without_a_person_nothing_is_given(tmp_path, settings):
    w, founder = World(tmp_path, settings), Identity.generate()
    w.peer.owner = FakeOwner(yes=False, why="사람이 없음")  # an owner without a timeout parameter is asked plainly
    r = await apply_to_sphinx(founder, w.ask, "p", "c", time.time())
    await w.settle()
    assert (await w.ask({"op": "sphinx.status", "application_id": r["application_id"]}))["status"] == "rejected"


# ---------------- the applicant's command and the runner ----------------
async def test_the_applicant_applies_and_takes_the_pass_from_the_command_line(tmp_path, settings):
    w = World(tmp_path, settings)
    home = PeerHome(str(tmp_path / "founder"), settings)
    me = home.identity()

    async def cli(*args):
        out = io.StringIO()
        code = await cli_run(parser().parse_args(list(args)), w.s, out=out, ask_of=lambda url: w.ask)
        return code, json.loads(out.getvalue())
    code, r = await cli("apply", "--home", str(tmp_path / "founder"), "--sphinx", "http://sphinx", "--purpose", "동네 모임", "--contact", "tel:010")
    assert code == 0 and r["status"] == "waiting"
    q = await w.question()
    w.desk.answer(q.id, {"yes": True, "why": "대면 확인"})
    await w.settle()
    out = tmp_path / "pass.json"
    code, got = await cli("pass", "--sphinx", "http://sphinx", "--application", r["application_id"], "--home", str(tmp_path / "founder"), "--out", str(out))
    assert code == 0 and got["status"] == "passed" and json.loads(out.read_text())["body"]["founder"] == me.pub
    key = tmp_path / "god.key"
    god = Identity.load_or_create(str(key))
    code, r2 = await cli("apply", "--key-file", str(key), "--sphinx", "http://sphinx", "--purpose", "가지", "--contact", "tel:011")
    assert code == 0 and god.pub in (await w.question()).body
    assert (await cli("apply", "--key-file", str(tmp_path / "none.key"), "--sphinx", "x", "--purpose", "p", "--contact", "c"))[1]["error"].startswith("no key file")
    assert "needs --sphinx" in (await cli("apply", "--home", str(tmp_path / "founder")))[1]["error"]
    assert "--purpose" in (await cli("apply", "--home", str(tmp_path / "founder"), "--sphinx", "x"))[1]["error"]
    assert "--application" in (await cli("pass", "--sphinx", "x"))[1]["error"]
    assert "needs --broker" in (await cli("show"))[1]["error"]


def test_the_runner_is_a_person_s_peer_with_the_role(tmp_path, settings):
    from arena.peers import sphinx
    env = make_env(tmp_path, ARENA_PERSONAL_PEER_BROKERS="public=http://127.0.0.1:1", ARENA_PERSONAL_PEER_HOME=str(tmp_path / "s"),
                   ARENA_LLM_BACKEND="none")
    with pytest.raises(ConfigError, match="사람이 정한다"):
        sphinx.build(Settings.load(env=dict(env, ARENA_PERSONAL_MODE="agent"), dotenv_path=None))
    peer, service, token = sphinx.build(Settings.load(env=dict(env, ARENA_PERSONAL_MODE="human"), dotenv_path=None))
    assert peer.operator() == "human" and any(isinstance(a, SphinxRole) for a in peer.apps) and "sphinx.apply" in peer.skills() and token
