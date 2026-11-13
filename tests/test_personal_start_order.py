"""A personal peer behind a connectivity server starts the relay before its apps: the event router's first call to the broker
must already leave by the server's way out (2026-11-13, a company PC: the first call went straight to a private broker address
and failed with a JSONDecodeError)."""
import asyncio

from arena.peers.personal import start_peer


class FakeRelay:
    def __init__(self, order):
        self.order = order

    async def start(self):
        self.order.append("relay.start")
        return "relay"

    async def run(self, started=False):
        self.order.append("relay.run")


class FakePeer:
    def __init__(self, relay):
        self.order, self.relay, self.apps = [], None, []
        if relay:
            self.relay = FakeRelay(self.order)

    async def start(self):
        self.order.append("peer.start")


async def test_the_relay_decides_how_calls_leave_before_the_apps_make_their_first_call():
    p = FakePeer(relay=True)
    await start_peer(p)
    await asyncio.sleep(0)  # the relay's own loop is a task
    assert p.order[:2] == ["relay.start", "peer.start"] and "relay.run" in p.order


async def test_a_peer_without_a_relay_starts_its_apps_as_before():
    p = FakePeer(relay=False)
    await start_peer(p)
    assert p.order == ["peer.start"]
