"""A peer keeps connecting to its broker until it connects (user 2026-11-03: "peer들은 기본적으로 broker가 커넥트될 때까지
계속 시도하지?"). A broker that does not answer yet is tried again with a growing wait; once it answers, the profile is
kept fresh. A failing broker or an app that cannot start yet does not stop the peer."""
import dataclasses

from arena.broker.failover import FailoverBrokerClient
from arena.peer.plugin import BaseApp
from arena.peer.presence import Presence
from tests.test_event_apps import World


class Flaky:
    """a broker client that is unreachable for the first `down` calls"""

    def __init__(self, real, down):
        self.real, self.down, self.calls = real, down, 0

    def __getattr__(self, name):
        attr = getattr(self.real, name)

        async def call(*a, **kw):
            self.calls += 1
            if self.calls <= self.down:
                raise ConnectionError("broker not up yet")
            return await attr(*a, **kw)
        return call


async def test_the_peer_keeps_connecting_until_its_broker_answers(tmp_path, settings):
    s = dataclasses.replace(settings, broker_retry_sec=1.0, broker_retry_max_sec=4.0, profile_ttl_sec=600.0)
    w = World(tmp_path, s)
    await w.boot()
    p = w.peer("late", [])
    flaky = Flaky(p.brokers["public"], down=3)
    p.brokers["public"] = FailoverBrokerClient([flaky], s)
    waits = []

    async def sleep(t):
        waits.append(t)
    await Presence(p, sleep=sleep).keep(rounds=5)
    assert waits == [1.0, 2.0, 4.0, 300.0]  # backing off while unreached (capped at the max), then refreshing before expiry
    assert not p.unreached and p.identity.pub in w.public.profiles  # posted once the broker answered


async def test_an_app_that_cannot_start_yet_does_not_stop_the_peer(tmp_path, settings):
    class Broken(BaseApp):
        name, version, app_id = "broken", "1.0", "6c1e9b3a-4d2f-4a8e-b7c5-1f0e3d9a2b64"

        async def start(self, ctx):
            raise ConnectionError("recorder not up yet")
    w = World(tmp_path, settings)
    await w.boot()
    p = w.peer("p", [Broken()])
    await p.start()
    assert any("broken 시작 실패" in x["text"] for x in w.log.tail(50))
