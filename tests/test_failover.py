"""P5-C22: when the primary broker dies, peers reach a secondary of the same group without noticing."""
import pytest

from arena.broker.client import InMemoryBrokerClient
from arena.broker.failover import BrokerUnavailable, FailoverBrokerClient
from arena.broker.neighbors import InMemoryNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.search import BM25Searcher
from tests.test_broker_service import notice, profile


class Switchable:
    """a broker client whose broker can be switched off (connection errors) and on again"""

    def __init__(self, inner):
        self.inner, self.up, self.calls = inner, True, 0

    def __getattr__(self, name):
        target = getattr(self.inner, name)

        async def call(*a, **kw):
            self.calls += 1
            if not self.up:
                raise ConnectionError("broker down")
            return await target(*a, **kw)
        return call


@pytest.fixture
def pair(settings, clock):
    gw = InMemoryNeighbors()
    svcs = []
    for i in range(2):
        b = BrokerService(settings, Identity.generate(), BM25Searcher(), gw, name=f"b{i}", neighbors=[f"mem://b{1 - i}"], clock=clock)
        gw.register(f"mem://b{i}", b)
        svcs.append(b)
    a, b = Switchable(InMemoryBrokerClient(svcs[0])), Switchable(InMemoryBrokerClient(svcs[1]))
    return svcs, a, b, FailoverBrokerClient([a, b], settings, clock=clock)


async def test_p5c22_seamless_switch_to_the_secondary(pair, clock):
    (sa, sb), a, b, fo = pair
    me, issuer = Identity.generate(), Identity.generate()
    assert (await fo.advertise(me, profile("http://me", "기록 보관 담당", offers=["record"], now=clock())))["ok"]
    assert me.pub in sa.profiles and me.pub not in sb.profiles  # profiles live on the primary only
    assert (await fo.post_notice(issuer, notice(issuer, "n1", now=clock())))["ok"]  # shared to the secondary too
    first = await fo.changed_notices(me, since=0)
    a.up = False  # the primary dies
    got = await fo.list_notices(me)
    assert got["ok"] and [n["notice_id"] for n in got["notices"]] == ["n1"]  # the caller noticed nothing
    assert me.pub in sb.profiles  # the last profile was re-posted on the secondary
    assert [p["pub"] for p in (await fo.find("기록", role="record"))["peers"]] == [me.pub]
    again = await fo.changed_notices(me, since=first["now"])
    assert [n["notice_id"] for n in again["notices"]] == ["n1"]  # after a switch the change feed starts over
    assert fo.current == 1 and fo.switches == 1


async def test_p5c22_failback_to_the_primary_after_the_wait(pair, clock, settings):
    (sa, sb), a, b, fo = pair
    me = Identity.generate()
    await fo.advertise(me, profile("http://me", "x", now=clock()))
    a.up = False
    await fo.health()
    assert fo.current == 1
    a.up = True
    sa.profiles.clear()  # e.g. the primary restarted without its board
    await fo.health()
    assert fo.current == 1  # not yet: wait ARENA_BROKER_FAILBACK_SEC
    clock.tick(settings.broker_failback_sec + 1)
    await fo.health()
    assert fo.current == 0 and me.pub in sa.profiles  # back on the primary, profile re-posted


async def test_p5c22_all_down_is_an_error(pair):
    _, a, b, fo = pair
    a.up = b.up = False
    with pytest.raises(BrokerUnavailable):
        await fo.health()


def test_p5c22_group_with_several_brokers_in_settings():
    from arena.peers.common import parse_groups
    assert parse_groups(["public=http://a:1|http://b:2", "g-x=http://c:3"]) == {"public": ["http://a:1", "http://b:2"], "g-x": ["http://c:3"]}
