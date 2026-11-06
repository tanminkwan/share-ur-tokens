"""P9: a peer's pen name = the nickname its owner chose + the start of its key. The profile carries it, the broker checks it,
and a name typed by a person (the nickname alone, or with the start of the key) becomes one key by code."""
import pytest

from arena.broker.client import InMemoryBrokerClient
from arena.config import ConfigError
from arena.crypto import Identity
from arena.peer.area import LocalFolderArea
from arena.peer.assistant import EventAssistant
from arena.peer.assistant.handles import AmbiguousName
from arena.peer.home import PeerHome
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.events import EventLog
from tests.test_assistant import Eco, Steps, asst, ctx, settle


@pytest.fixture
async def eco(tmp_path, settings):
    e = Eco(tmp_path, settings)
    e.host, e.a, e.b = e.peer("host"), e.peer("a"), e.peer("b")
    e.host.nick, e.a.nick, e.b.nick = "나루", "비단길", "비단길"  # two peers share a nickname
    await e.boot()
    return e


def profiles(eco):
    return {p["pub"]: p for p in eco.broker.profiles.values()}


async def resolve(eco, who, ref, need_url=False):
    c = ctx(who)
    return await asst(who).handles.resolve_peer(c, asst(who).fresh_state() if hasattr(asst(who), "fresh_state") else _state(who), ref, need_url)


def _state(p):
    from tests.test_assistant_parts import state
    return state(issuer_pub=p.identity.pub)


# ---- A: the peer chooses it ----
async def test_p9a1_the_pen_name_is_the_nickname_and_the_key_start(eco):
    assert eco.a.pen == f"비단길-{eco.a.identity.pub[:6]}"
    assert eco.host.pen == f"나루-{eco.host.identity.pub[:6]}"
    assert profiles(eco)[eco.a.identity.pub]["nick"] == "비단길"  # its own field in the signed profile (P9-A3)


async def test_p9a2_without_a_nickname_the_default_one_is_used(tmp_path, settings):
    e = Eco(tmp_path, settings)
    p = e.peer("plain")
    assert p.nick == settings.pen_name_default_nick and p.pen == f"{settings.pen_name_default_nick}-{p.identity.pub[:6]}"


def test_p9a4_a_nickname_the_rules_refuse_stops_the_peer_from_starting(tmp_path, settings):
    (tmp_path / "n").mkdir()
    with pytest.raises(ConfigError):
        Peer(Identity.generate(), settings, PeerConfig(url="mem://x", nick="a b"), LocalFolderArea(str(tmp_path / "n"), settings),
             NoOwner(), None, None, None, brokers={}, apps=[])


async def test_p9a4_the_broker_refuses_a_profile_with_a_bad_nickname(eco):
    me = Identity.generate()
    from arena.broker.service import Caller  # noqa: F401
    bad = {"url": "mem://z", "nick": "a-b", "summary": "", "offers": [], "labels": [], "until": 9e12, "ver": 1}
    r = await InMemoryBrokerClient(eco.broker).advertise(me, bad)
    assert not r["ok"] and "nickname" in r["error"]


async def test_p9a5_the_nickname_changes_any_time_and_is_posted_at_once(eco):
    ver = profiles(eco)[eco.a.identity.pub]["ver"]
    r = await eco.a.set_nick("물결")
    assert r == {"ok": True, "nick": "물결", "pen": f"물결-{eco.a.identity.pub[:6]}"}
    p = profiles(eco)[eco.a.identity.pub]
    assert p["nick"] == "물결" and p["ver"] == ver + 1
    assert (await eco.a.set_nick("물결"))["ok"]  # the same again posts nothing new
    assert profiles(eco)[eco.a.identity.pub]["ver"] == ver + 1
    for bad in ("", "a b", "x" * 99, "a-b"):
        assert not (await eco.a.set_nick(bad))["ok"]
    assert eco.a.nick == "물결"


async def test_p9a5_the_changed_nickname_survives_a_restart(tmp_path, settings):
    home = PeerHome(str(tmp_path / "home"), settings)
    (tmp_path / "area").mkdir()
    ident = home.identity()

    def make(nick):
        return Peer(ident, settings, PeerConfig(url="mem://h", nick=nick), LocalFolderArea(str(tmp_path / "area"), settings), NoOwner(),
                    Steps(), None, EventLog(echo=False), brokers={}, apps=[], home=home)
    first = make("처음")
    assert first.nick == "처음"
    await first.set_nick("나중")
    assert make("처음").nick == "나중"  # the home's value wins over the setting


async def test_p9a5_renaming_asks_the_llm_for_nothing(eco):
    n = len(eco.a.llm.prompts)
    await eco.a.set_nick("다른이름")
    assert len(eco.a.llm.prompts) == n  # the same profile is posted under the new name; no new summary is written


async def test_p9a6_nicknames_may_repeat(eco):
    nicks = [p["nick"] for p in profiles(eco).values()]
    assert nicks.count("비단길") == 2


# ---- B: calling by name ----
async def test_p9b_the_full_name_and_the_nickname_alone(eco):
    a, host = eco.a, eco.host
    assert (await resolve(eco, a, host.pen))[0] == host.identity.pub  # the full name
    assert (await resolve(eco, a, "나루"))[0] == host.identity.pub  # the nickname alone: the only 나루
    assert (await resolve(eco, a, "나루"))[1] == host.config.url


async def test_p9b3_a_shared_nickname_is_told_apart_by_the_key_start(eco):
    a, b, host = eco.a, eco.b, eco.host
    long = next(n for n in range(1, 7) if a.identity.pub[:n] != b.identity.pub[:n])  # how much of the key tells them apart
    assert (await resolve(eco, host, f"비단길-{a.identity.pub[:long]}"))[0] == a.identity.pub
    assert (await resolve(eco, host, f"비단길-{b.identity.pub[:long]}"))[0] == b.identity.pub
    assert (await resolve(eco, host, a.pen))[0] == a.identity.pub


async def test_p9b4_a_shared_nickname_alone_is_refused_and_names_both(eco):
    with pytest.raises(AmbiguousName) as e:
        await resolve(eco, eco.host, "비단길")
    assert eco.a.pen in str(e.value) and eco.b.pen in str(e.value)


async def test_p9b4_the_toolbox_reports_it_instead_of_raising(eco):
    ev = await eco.host.app(EventAssistant).host_event(ctx(eco.host), title="t", kind="k", rules="r", policy={"roles": ["member"]}, instruction="x")
    st = asst(eco.host).events[ev]
    out = await asst(eco.host).toolbox.run(asst(eco.host), ctx(eco.host), st, "contact", {"peer": "비단길"})
    assert eco.a.pen in out["error"] and eco.b.pen in out["error"]


async def test_p9b4_a_name_nobody_has_is_not_found(eco):
    assert (await resolve(eco, eco.host, "누구도없음"))[0] is None
    assert (await resolve(eco, eco.host, "비단길-ffffff"))[0] is None


async def test_p9a7_the_old_nickname_stops_working_after_a_change(eco):
    await eco.host.set_nick("새나루")
    assert (await resolve(eco, eco.a, "새나루"))[0] == eco.host.identity.pub
    assert (await resolve(eco, eco.a, "나루"))[0] is None  # the old nickname names nobody now
    assert (await resolve(eco, eco.a, eco.host.pen))[0] == eco.host.identity.pub  # the current full name still does


# ---- C: showing ----
async def test_p9c_others_are_shown_by_the_nickname_they_posted(eco):
    a = eco.a
    c = ctx(a)
    h = asst(a).handles
    await h.directory.profiles(c)  # the broker's list is what teaches the nicknames
    assert h.handle(c, _state(a), eco.host.identity.pub) == eco.host.pen
    assert h.handle(c, _state(a), a.identity.pub) == a.pen
    unseen = Identity.generate().pub
    assert h.handle(c, _state(a), unseen) == f"{eco.s.pen_name_default_nick}-{unseen[:6]}"  # not known yet: the default nickname (P9-C2)


# ---- A7: a nickname just changed shows at once on the other side ----
async def test_p9a7_a_message_shows_the_senders_new_nickname_at_once(eco):
    import dataclasses
    from tests.test_assistant import joined
    ev = await joined(eco)
    a, b = eco.a, eco.b
    for p in (a, b):  # the throttle would otherwise hide a change made a moment after the last read
        p.settings = dataclasses.replace(p.settings, nick_refresh_sec=0.0)
    a.llm.push("send", to=b.pen, text="안녕", data={})
    await asst(a).feed(ctx(a), ev, "보내라")
    await settle(a, b)
    first = [x for x in asst(b).events[ev].timeline if x["dir"] == "in" and x["text"] == "안녕"][-1]
    assert first["who"] == a.pen
    await a.set_nick("물결")
    b_to_a = a.pen  # the new full name
    a.llm.push("send", to=eco.host.pen, text="이름을 바꿨다", data={})
    b.llm.push("send", to=b_to_a, text="새 이름으로 부른다", data={})
    await asst(b).feed(ctx(b), ev, "보내라")
    await settle(a, b)
    a.llm.push("send", to=b.pen, text="바뀐 뒤 메시지", data={})
    await asst(a).feed(ctx(a), ev, "보내라")
    await settle(a, b)
    last = [x for x in asst(b).events[ev].timeline if x["dir"] == "in" and x["text"] == "바뀐 뒤 메시지"][-1]
    assert last["who"] == f"물결-{a.identity.pub[:6]}"  # not the old name
