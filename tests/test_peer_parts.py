"""SOLID re-check, part 3 (2026-11-03): the parts taken out of Peer, on their own: RecorderTrust (proving recorders from
the root of trust) and PeerReach (reaching a peer by its listed connections), refusals included."""
import dataclasses

from arena.peer.reach import PeerReach
from arena.peer.trust_check import RecorderTrust
from arena.recorder.client import InMemoryRecorderClient
from tests.test_trust import Child, Net, net  # noqa: F401  (net is a fixture)


class Down:
    async def trust(self):
        raise ConnectionError("down")


async def test_recorder_trust_refusals(net, settings):
    anchored = dataclasses.replace(settings, trust_genesis_hash=net.ledger_id, trust_god_pub=net.god.pub)
    child = await Child(settings, net).boot()
    other_trunk = await Net(settings).boot()
    stray = await Child(settings, other_trunk).boot()  # a branch of another trunk
    lone = await Net(settings).boot()                  # no origin at all
    clients = {"mem://root": InMemoryRecorderClient(net.svc), "mem://child": InMemoryRecorderClient(child.svc),
               "mem://stray": InMemoryRecorderClient(stray.svc), "mem://lone": InMemoryRecorderClient(lone.svc), "mem://down": Down()}
    t = RecorderTrust(lambda: anchored, lambda url: clients[url])
    assert (await t.check("mem://root"))["ok"] and "mem://root" in t.cache
    assert (await t.check("mem://child"))["linked_from"] == net.ledger_id
    assert "ConnectionError" in (await t.check("mem://down"))["why"]
    assert "not the trunk" in (await t.check("mem://lone"))["why"]
    assert "another chain" in (await t.check("mem://stray"))["why"]
    clients["mem://root"] = Down()  # the trunk goes away: a branch not proven yet cannot be proven
    t2 = RecorderTrust(lambda: anchored, lambda url: clients[url])
    assert "parent chain not proven" in (await t2.check("mem://child"))["why"]
    open_ = RecorderTrust(lambda: settings, lambda url: clients[url])  # no root values: every recorder passes, unanchored
    r = await open_.check("mem://lone")
    assert r["ok"] and r["anchored"] is False


async def test_peer_reach_picks_a_connection_and_refuses_when_none_fits(settings):
    calls = []

    async def a2a(url, msg, timeout=None, group=None, event=None):
        calls.append(("a2a", url))
        return {"ok": True}

    class Rest:
        async def call(self, url, msg, timeout=None, meta=None):
            calls.append(("api", url, meta))
            return {"ok": True}

    class Broker:
        def __init__(self, profiles):
            self.profiles = profiles

        async def list_profiles(self, identity=None):
            return {"profiles": self.profiles}

    class Broken:
        async def list_profiles(self, identity=None):
            raise ConnectionError("down")
    profiles = [{"pub": "a", "connections": [{"kind": "a2a", "url": "http://a"}]},
                {"pub": "s", "connections": [{"kind": "api", "url": "http://s"}]},
                {"pub": "h", "connections": [{"kind": "human", "contact": "tel:1"}]},
                {"pub": "old", "url": "http://old"}]
    reach = PeerReach(None, {"down": Broken(), "public": Broker(profiles)}, a2a, lambda: Rest())
    assert (await reach.profile_of("a"))["pub"] == "a" and await reach.profile_of("nobody") is None
    await reach.call("a", {"op": "x"})
    await reach.call("s", {"op": "x"}, group="g", event="e")
    await reach.call("old", {"op": "x"})                       # an old profile without connections: its a2a url
    await reach.call("nobody", {"op": "x"}, url="http://given")  # no profile: the address the peer gave
    assert calls == [("a2a", "http://a"), ("api", "http://s", {"group_id": "g", "event_id": "e"}), ("a2a", "http://old"), ("a2a", "http://given")]
    r = await reach.call("h", {"op": "x"})  # only a human contact: code never uses it
    assert not r["ok"] and "no connection method" in r["error"]
