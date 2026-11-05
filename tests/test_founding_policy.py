"""FG-F6..F8 (dev/founding/design.md 2, 3): the foundation publishes the founding policy, signed and off the ledger; the
sphinx takes it (or falls back to its own settings), enforces it, knows whether it is delegated on the trunk, and says so
to its person (a notice card) and to its applicants."""
import os
import time
from types import SimpleNamespace

import pytest

from arena.config import ConfigError, Settings
from arena.crypto import Identity
from arena.groups.flows import application
from arena.ledger.founding import make_policy, policy_body, policy_error
from arena.peer.foundation_role import FoundationRole
from arena.recorder.client import InMemoryRecorderClient
from tests.conftest import make_env
from tests.test_delegation import delegation
from tests.test_sphinx import World
from tests.test_trust import Net, net  # noqa: F401  (net is a fixture)

FOUNDATION = "mem://foundation"


def test_fgf6_a_policy_is_signed_by_its_foundation_and_its_values_are_checked():
    f, other = Identity.generate(), Identity.generate()
    b = policy_body(f.pub, 5, 7, 3, 1.0)
    p = make_policy(b, f.sign(b))
    assert policy_error(p) is None and policy_error(p, foundation=f.pub) is None
    assert "another foundation" in policy_error(p, foundation=other.pub)
    assert "signature" in policy_error(make_policy(dict(b, pass_days=99.0), p["sig"]))
    assert "cap is" in policy_error(make_policy(dict(b, cap={"count": -1, "days": 7.0}), "s"))
    assert "cap is" in policy_error(make_policy(dict(b, cap={"count": 1, "days": 0}), "s"))
    assert "pass_days" in policy_error(make_policy(dict(b, pass_days=0), "s"))
    assert policy_error({"format": "x"}) == "not a founding policy"


async def test_fgf6_the_foundation_hands_out_its_policy(settings):
    f = Identity.generate()
    role = FoundationRole(settings.__class__(**{**settings.__dict__, "foundation_founding_cap_count": 3,
                                                "foundation_founding_cap_days": 10.0, "foundation_founding_pass_days": 2.0}))
    r = await role._policy(SimpleNamespace(pub=f.pub, clock=time.time, sign=f.sign), {}, None)
    assert r["ok"] and policy_error(r["policy"], foundation=f.pub) is None
    assert r["policy"]["body"]["cap"] == {"count": 3, "days": 10.0} and r["policy"]["body"]["pass_days"] == 2.0
    assert "founding.policy" in role.ops() and "가지 창설 기준" in role.offers()


def sphinx_world(tmp_path, settings, foundation, trunk=None, **policy):
    """a sphinx peer that asks `foundation` (an Identity) for its policy and, with trunk (a Net), the trunk for its delegation"""
    w = World(tmp_path, settings, sphinx_foundation_url=FOUNDATION, sphinx_foundation_pub=foundation.pub,
              sphinx_trunk_recorder_url="mem://trunk" if trunk else "", sphinx_policy_refresh_sec=0.0)
    vals = {"foundation_founding_cap_count": 1, "foundation_founding_cap_days": 10.0, "foundation_founding_pass_days": 2.0, **policy}
    frole = FoundationRole(settings.__class__(**{**settings.__dict__, **vals}))
    fctx = SimpleNamespace(pub=foundation.pub, clock=time.time, sign=foundation.sign)

    async def handle(msg):
        return await frole._policy(fctx, msg, None)
    w.peer.transport.register(FOUNDATION, handle)
    if trunk:
        w.peer.recorder_factory = lambda url: InMemoryRecorderClient(trunk.svc)
    return w


async def apply(w, founder):
    return await w.ask(application(founder, "작은 연구 모임", "메일로 연락", time.time()))


async def test_fgf7_the_sphinx_enforces_the_foundation_s_policy(tmp_path, settings):
    foundation = Identity.generate()
    w = sphinx_world(tmp_path, settings, foundation)
    info = await w.ask({"op": "sphinx.info"})
    assert info["policy"] == {"cap": {"count": 1, "days": 10.0}, "pass_days": 2.0, "source": "foundation", "foundation": foundation.pub}
    a = Identity.generate()
    assert (await apply(w, a))["ok"]
    await w.question(n=2)  # the notice card about the policy, then the question
    q = next(i for i in w.desk.list("open") if i.kind == "question")
    w.desk.answer(q.id, {"yes": True, "why": "만남"})
    await w.settle()
    st = w.peer.ctx(w.role).state.load()
    p = next(x for x in st["applications"].values() if x["founder"] == a.pub)["pass"]
    assert p["body"]["until"] - p["body"]["issued_at"] == pytest.approx(2.0 * 86400)  # the foundation's pass_days, not the sphinx's 30
    r = await apply(w, Identity.generate())
    assert not r["ok"] and "1 passes for 10 days" in r["error"]  # the foundation's cap


async def test_fgf7_a_wrong_or_missing_foundation_leaves_the_sphinx_s_own_settings(tmp_path, settings):
    w = sphinx_world(tmp_path, settings, Identity.generate())
    w.s = w.role.s = w.s.__class__(**{**w.s.__dict__, "sphinx_foundation_pub": Identity.generate().pub})  # trusts another key
    info = await w.ask({"op": "sphinx.info"})
    assert info["policy"]["source"] == "settings" and info["policy"]["cap"]["count"] == settings.sphinx_cap_count
    w.peer.transport.handlers.pop(FOUNDATION)
    assert (await w.ask({"op": "sphinx.info"}))["policy"]["source"] == "settings"


async def test_fgf7_the_last_good_policy_holds_when_the_foundation_goes_quiet(tmp_path, settings):
    w = sphinx_world(tmp_path, settings, Identity.generate())
    assert (await w.ask({"op": "sphinx.info"}))["policy"]["source"] == "foundation"
    w.peer.transport.handlers.pop(FOUNDATION)
    assert (await w.ask({"op": "sphinx.info"}))["policy"]["source"] == "foundation"


async def test_fgf8_the_sphinx_knows_and_tells_whether_it_is_delegated(tmp_path, settings, net):
    w = sphinx_world(tmp_path, settings, Identity.generate(), trunk=net)
    me = w.peer.identity
    info = await w.ask({"op": "sphinx.info"})
    assert info["delegated"] is False
    cards = [i for i in w.desk.list("open") if i.kind == "notice"]
    assert len(cards) == 1 and "위임 안 됨" in cards[0].title
    r = await apply(w, Identity.generate())
    assert "not delegated now" in r["note"]
    assert (await delegation(net, "delegate", me))["ok"]
    assert (await w.ask({"op": "sphinx.info"}))["delegated"] is True
    titles = [i.title for i in w.desk.list("open") if i.kind == "notice"]
    assert len(titles) == 2 and "위임됨" in titles[0]  # newest first; a card only when something changed
    await w.ask({"op": "sphinx.info"})
    assert len([i for i in w.desk.list("open") if i.kind == "notice"]) == 2


def test_fgf7_a_foundation_address_needs_its_key(tmp_path):
    from arena.peers import sphinx
    s = Settings.load(env=make_env(tmp_path, ARENA_PERSONAL_MODE="human", ARENA_SPHINX_FOUNDATION_URL="http://x"), dotenv_path=None)
    with pytest.raises(ConfigError, match="FOUNDATION_PUB"):
        sphinx.build(s)
