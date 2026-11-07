"""P10-B: a peer with no open port is reached through a connectivity server. Real sockets: a real connectivity server on
loopback, real A2A between peers, no LLM. The peer behind the relay serves no port at all; its app is reached only
through the tunnel. Above the transport nothing changes: callers use the peer's url like any other."""
import asyncio
import dataclasses
import time

import httpx
import pytest

from arena.a2a import A2ATransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.events import EventLog
from arena.llm import NoLLM
from arena.peer.area import LocalFolderArea
from arena.peer.desk import DeskOwner, OwnerDesk
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.peer.relay_link import RelayLink
from arena.search import BM25Searcher
from arena.serve import serve_background
from connectivity.api import build_connectivity_app
from connectivity.config import ConnectivitySettings
from connectivity.service import ConnectivityService
from tests.fakes import FakeOwner
from tests.test_a2a_push import AskOwner, engage
from tests.test_processes import free_port


@pytest.fixture
async def world(tmp_path, settings):
    w = World(tmp_path, dataclasses.replace(settings, a2a_answer_wait_sec=0.1, a2a_push_fallback_sec=30.0,
                                            peer_relay_hold_sec=2.0, broker_retry_sec=0.05, broker_retry_max_sec=0.2))
    yield w
    await w.close()


class World:
    def __init__(self, tmp, s):
        self.tmp, self.s, self.servers, self.tasks = tmp, s, [], []
        self.broker = BrokerService(s, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[])

    async def connectivity(self, **over):
        port = free_port()
        cs = dataclasses.replace(ConnectivitySettings(), **{"public_url": f"http://127.0.0.1:{port}", "poll_hold_sec": 2.0, **over})
        svc = ConnectivityService(cs)
        srv = await serve_background(build_connectivity_app(svc), "127.0.0.1", port)
        self.servers.append(srv)
        return svc, f"http://127.0.0.1:{port}", srv

    async def peer(self, name, owner=None, apps=(), port=True, post=True):
        (self.tmp / name).mkdir()
        url = f"http://127.0.0.1:{free_port()}"
        p = Peer(Identity.generate(), self.s, PeerConfig(url=url), LocalFolderArea(str(self.tmp / name), self.s), owner or NoOwner(),
                 NoLLM(), A2ATransport(self.s), EventLog(keep=50, echo=False), brokers={"public": InMemoryBrokerClient(self.broker)},
                 apps=list(apps))
        if port:  # a peer behind a firewall serves nothing: nobody can reach this address
            self.servers.append(await serve_background(p.a2a_app(), "127.0.0.1", int(url.rsplit(":", 1)[1])))
        await p.scheduler.start(p.ctx(p.scheduler))
        if post:
            await p.advertise()
        return p

    async def behind(self, p, servers):
        """the peer attaches to the connectivity server(s); returns once callers can reach it"""
        p.relay = RelayLink(p, servers)
        self.tasks.append(asyncio.create_task(p.relay.run()))
        for _ in range(200):
            if p.reach_url:
                return p
            await asyncio.sleep(0.02)
        raise AssertionError(f"not attached: {p.relay.state}")

    async def close(self):
        for t in self.tasks:
            t.cancel()
        for s in self.servers:
            s.should_exit = True
        await asyncio.sleep(0.1)


async def test_p10b_a_peer_with_no_port_is_reached_through_the_relay(world):
    _, server, _ = await world.connectivity()
    b = await world.behind(await world.peer("b", FakeOwner(yes=True, why="좋다"), [AskOwner()], port=False), [server])
    a = await world.peer("a")
    assert b.url == f"{server}/r/{b.identity.pub}" and b.url != b.config.url
    with pytest.raises(Exception):  # its own address is not reachable: there is no server behind it
        async with httpx.AsyncClient(timeout=1) as hc:
            await hc.get(b.config.url + "/.well-known/agent-card.json")
    r = await a.call(b.url, engage(b.identity.pub))  # a calls b like any peer: the address is all it knows
    assert r["ok"] and r["sig"]
    async with httpx.AsyncClient() as hc:
        card = (await hc.get(b.url + "/.well-known/agent-card.json")).json()
    assert card["supportedInterfaces"][0]["url"] == b.url + "/rpc"  # the card names the relay address


async def test_p10b_the_profile_names_the_relay_address_and_nothing_else_changes(world):
    _, server, _ = await world.connectivity()
    b = await world.behind(await world.peer("b", port=False), [server])
    prof = world.broker.profiles[b.identity.pub]
    assert prof["url"] == b.url and prof["connections"] == [{"kind": "a2a", "url": b.url}]
    assert "connectivity" not in prof and not any("relay" in k for k in prof)  # the layers above never learn of it (P10-P3, P4)


async def test_p10b_a_slow_answer_reaches_a_caller_behind_a_relay_by_its_webhook(world):
    """both behind relays: the answering peer posts to the caller's webhook at the caller's relay address"""
    _, server, _ = await world.connectivity()
    desk = OwnerDesk(lambda: 0.0, keep=50)
    b = await world.behind(await world.peer("b", DeskOwner(desk, world.s), [AskOwner()], port=False), [server])
    a = await world.behind(await world.peer("a", port=False), [server])

    async def person_answers():
        while not desk.items:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)
        desk.answer(next(iter(desk.items)), {"yes": True, "why": "좋아요"})
    later = asyncio.create_task(person_answers())
    t0 = time.monotonic()
    r = await a.call(b.url, engage(b.identity.pub), wait=20)
    await later
    assert r["ok"] and r["sig"] and time.monotonic() - t0 < 5  # woken by the webhook through the relay (polling alone: 30 s)


async def test_p10b_only_the_a2a_paths_reach_the_peers_app(world):
    _, server, _ = await world.connectivity()  # the server itself passes every path (a general service)
    b = await world.behind(await world.peer("b", port=False), [server])
    async with httpx.AsyncClient() as hc:
        assert (await hc.get(b.url + "/a2a/../health")).status_code == 404
        assert (await hc.get(b.url + "/anything")).status_code == 404  # refused by the adapter, not by the server
        assert (await hc.get(b.url + "/.well-known/agent-card.json")).status_code == 200


async def test_p10b_when_the_server_goes_the_peer_keeps_its_relay_address_until_it_attaches_again(world):
    """a relay that drops for a moment (a restart) changes nothing others see: the address stays, no profile is posted again.
    Its own address would not help (nobody can open it); calls in the gap are sent again by the caller (P10-C4)"""
    _, server, srv = await world.connectivity()
    b = await world.behind(await world.peer("b", port=False), [server])
    relay, ver = b.url, world.broker.profiles[b.identity.pub]["ver"]
    srv.should_exit = True  # the server goes away
    assert await wait_for(lambda: b.relay.client.base is None, 300)
    assert b.url == relay and b.relay.state["error"]  # the window says it is attaching again
    assert world.broker.profiles[b.identity.pub]["url"] == relay and world.broker.profiles[b.identity.pub]["ver"] == ver
    await restart_at(world, server)
    assert await wait_for(lambda: b.relay.client.base == relay, 300)
    assert world.broker.profiles[b.identity.pub]["ver"] == ver  # back at the same address: nothing to post


async def test_p10b_when_the_server_goes_for_good_the_peer_moves_to_the_next_with_one_post(world):
    dead = f"http://127.0.0.1:{free_port()}"  # nothing listens here
    _, s1, srv1 = await world.connectivity()
    _, s2, _ = await world.connectivity()
    b = await world.behind(await world.peer("b", port=False), [dead, s1, s2])
    assert b.url.startswith(s1) and b.relay.state["server"] == s1
    ver = world.broker.profiles[b.identity.pub]["ver"]
    srv1.should_exit = True
    assert await wait_for(lambda: b.url.startswith(s2), 300)  # (the dead one is tried on the way, and skipped)
    prof = world.broker.profiles[b.identity.pub]
    assert prof["url"] == b.url and prof["ver"] == ver + 1  # one post: the new address, never the unreachable own one


async def test_p10b_the_peer_attaches_once_the_server_comes(world):
    port = free_port()
    server = f"http://127.0.0.1:{port}"
    b = await world.peer("b", port=False)
    b.relay = RelayLink(b, [server])
    world.tasks.append(asyncio.create_task(b.relay.run()))
    await asyncio.sleep(0.3)
    assert b.reach_url is None and b.relay.state["error"]  # not there yet: it keeps trying
    cs = dataclasses.replace(ConnectivitySettings(), public_url=server, poll_hold_sec=2.0)
    world.servers.append(await serve_background(build_connectivity_app(ConnectivityService(cs)), "127.0.0.1", port))
    for _ in range(200):
        if b.reach_url:
            break
        await asyncio.sleep(0.02)
    assert b.reach_url == f"{server}/r/{b.identity.pub}"


# ---- P10-C: the inbound check decides direct or relay ----
async def linked(world, p, servers, rounds=1):
    p.relay = RelayLink(p, servers)
    await p.relay.run(rounds=rounds)
    return p


async def wait_for(cond, n=200):
    for _ in range(n):
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


async def test_p10c_a_peer_reachable_at_its_port_goes_direct_and_does_not_attach(world):
    svc, server, _ = await world.connectivity(probe_allow=["127.0.0.0/8"])  # a test on loopback: the operator allows it
    a = await linked(world, await world.peer("a"), [server])
    assert a.relay.mode == "direct" and a.relay.last_check["source"] == "127.0.0.1"
    assert a.url == a.config.url and svc.health()["attached"] == 0  # no session on the server
    assert world.broker.profiles[a.identity.pub]["url"] == a.config.url


async def test_p10c_a_peer_not_reachable_attaches_and_is_announced_at_the_relay(world):
    svc, server, _ = await world.connectivity(probe_allow=["127.0.0.0/8"])
    b = await linked(world, await world.peer("b", port=False), [server])
    assert b.relay.mode == "relay" and "no signed answer" in b.relay.last_check["why"]
    assert await wait_for(lambda: b.reach_url) and b.url == f"{server}/r/{b.identity.pub}"
    await b.relay.close()


async def test_p10c_a_private_source_is_not_tried_unless_allowed(world):
    svc, server, _ = await world.connectivity()  # nothing allowed: loopback is not public
    a = await linked(world, await world.peer("a"), [server])
    assert a.relay.mode == "relay" and a.relay.last_check["why"] == "source address is not public"
    await a.relay.close()


async def test_p10c_when_the_port_stops_answering_the_next_check_moves_to_the_relay(world):
    _, server, _ = await world.connectivity(probe_allow=["127.0.0.0/8"])
    a = await world.peer("a")
    a.relay = RelayLink(a, [server])
    assert await a.relay.decide() == "direct"
    world.servers[-1].should_exit = True  # a's own port closes (its server was the last one started)
    await asyncio.sleep(0.3)
    assert await a.relay.decide() == "relay"
    assert await wait_for(lambda: a.reach_url and "/r/" in a.reach_url)
    assert world.broker.profiles[a.identity.pub]["url"] == a.url  # posted again
    await a.relay.close()


async def test_p10c_the_check_goes_only_back_to_the_source_and_signs_are_checked(world):
    from connectivity.signing import sign_headers
    _, server, _ = await world.connectivity(probe_allow=["127.0.0.0/8"], check_per_hour=2)
    me, other = Identity.generate(), await world.peer("other")
    other.relay = RelayLink(other, [server])  # serves its own key's answer at its port
    port = int(other.config.url.rsplit(":", 1)[1])

    async def ask(body):
        async with httpx.AsyncClient() as hc:
            return await hc.post(f"{server}/reach", json=body, headers=sign_headers(me.sign_bytes, me.pub, "POST", "/reach"))
    r = await ask({"port": port, "host": "10.1.2.3"})  # a named host is ignored: only the source is tried
    assert r.status_code == 200 and r.json()["source"] == "127.0.0.1"
    assert r.json()["reachable"] is False  # the answer there is signed by another key, not mine
    assert (await ask({"port": 80})).status_code == 400  # privileged ports are not tried
    await ask({"port": port})
    assert (await ask({"port": port})).status_code == 429  # checks per key per hour
    async with httpx.AsyncClient() as hc:
        assert (await hc.post(f"{server}/reach", json={"port": port})).status_code == 401


async def test_p10c_no_server_answering_keeps_trying_through_the_relay(world):
    dead = f"http://127.0.0.1:{free_port()}"
    a = await world.peer("a")
    a.relay = RelayLink(a, [dead])
    assert await a.relay.decide() == "relay" and a.relay.last_check["reachable"] is None
    assert a.relay.state["error"]
    await a.relay.close()


async def test_p10b6_the_owners_window_shows_how_the_peer_is_reached(world):
    from arena.bundled.owner_service import OwnerService
    from arena.peer.assistant import EventAssistant
    _, server, _ = await world.connectivity(probe_allow=["127.0.0.0/8"])
    desk = OwnerDesk(lambda: 0.0, keep=10)
    a = await world.peer("a", apps=[EventAssistant(world.s)])
    assert OwnerService(a, desk).state()["me"]["reach"] is None  # no connectivity server set: nothing to show
    await linked(world, a, [server])
    assert OwnerService(a, desk).state()["me"]["reach"] == "direct"


# ---- 10-E: found in the real-process docker test (dev/phase10/test-results.md) ----

async def test_p10e_the_relay_address_is_known_at_once_even_with_a_long_poll_hold(world):
    """the first poll after attaching does not wait: a server holding polls for 25 s must not leave the peer unreachable for 25 s"""
    world.s = dataclasses.replace(world.s, peer_relay_hold_sec=25.0)
    _, server, _ = await world.connectivity(poll_hold_sec=25.0)
    b = await world.peer("b", FakeOwner(yes=True, why="좋다"), [AskOwner()], port=False)
    t0 = time.monotonic()
    b = await world.behind(b, [server])
    assert time.monotonic() - t0 < 2.0 and b.url.startswith(server)
    a = await world.peer("a")
    assert (await a.call(b.url, engage(b.identity.pub)))["ok"]  # and requests flow at once (the next poll is the long one)


async def test_p10e_the_first_profile_already_names_the_address_others_can_reach(world):
    """the first decision comes before the first post: the broker never lists a peer at an address nobody can open"""
    svc, server, _ = await world.connectivity()
    b = await world.peer("b", port=False, post=False)
    b.relay = RelayLink(b, [server])
    assert await b.relay.start() == "relay"
    assert world.broker.profiles.get(b.identity.pub) is None  # the decision posts nothing; the first post follows it
    await b.advertise()
    prof = world.broker.profiles[b.identity.pub]
    assert prof["url"] == f"{server}/r/{b.identity.pub}" and svc.health()["attached"] == 1
    await b.relay.close()


async def test_p10e_a_repost_before_any_post_posts_nothing(world):
    b = await world.peer("b", post=False)
    await b.set_reach_url("http://example.invalid/r/x")
    assert world.broker.profiles.get(b.identity.pub) is None and b.url == "http://example.invalid/r/x"
    await b.advertise()
    assert world.broker.profiles[b.identity.pub]["url"] == "http://example.invalid/r/x"


# ---- P10-C4: a call the other peer surely never got is sent again, to where it is now ----

async def restart_at(world, server):
    """a connectivity server comes back at the same address (a restart): nobody is attached to it yet"""
    port = int(server.rsplit(":", 1)[1])
    cs = dataclasses.replace(ConnectivitySettings(), public_url=server, poll_hold_sec=2.0)
    for _ in range(50):
        try:
            world.servers.append(await serve_background(build_connectivity_app(ConnectivityService(cs)), "127.0.0.1", port))
            return
        except Exception:  # noqa: BLE001  (the old socket is not let go yet)
            await asyncio.sleep(0.05)
    raise AssertionError("could not start the server again")


async def test_p10c4_a_call_while_the_relay_is_down_goes_through_once_the_peer_is_back(world):
    world.s = dataclasses.replace(world.s, peer_call_retries=5, peer_call_retry_sec=0.1)
    _, server, srv = await world.connectivity()
    b = await world.behind(await world.peer("b", FakeOwner(yes=True, why="좋다"), [AskOwner()], port=False), [server])
    a = await world.peer("a")
    srv.should_exit = True  # the relay restarts: b is not reachable for a moment
    assert await wait_for(lambda: b.relay.client.base is None, 300)
    call = asyncio.create_task(a.call_peer(b.identity.pub, engage(b.identity.pub)))
    await asyncio.sleep(0.3)
    assert not call.done()  # not an error at once: it is trying again
    await restart_at(world, server)
    r = await asyncio.wait_for(call, 10)
    assert r["ok"] and r["sig"] and b.url.startswith(server)


async def test_p10c4_a_call_goes_to_the_new_address_when_the_peer_moved(world):
    world.s = dataclasses.replace(world.s, peer_call_retries=5, peer_call_retry_sec=0.1)
    _, s1, srv1 = await world.connectivity()
    _, s2, _ = await world.connectivity()
    b = await world.behind(await world.peer("b", FakeOwner(yes=True, why="좋다"), [AskOwner()], port=False), [s1, s2])
    a = await world.peer("a")
    srv1.should_exit = True  # b moves to the second server; a still knows the first address
    assert await wait_for(lambda: not (b.reach_url or "").startswith(s1), 300)  # s1 is gone (b is between servers, or on s2)
    r = await asyncio.wait_for(a.call_peer(b.identity.pub, engage(b.identity.pub), url=f"{s1}/r/{b.identity.pub}"), 10)
    assert r["ok"] and b.url.startswith(s2)


async def test_p10c4_only_a_call_that_surely_never_arrived_is_sent_again(world):
    from a2a.client.errors import AgentCardResolutionError
    from arena.a2a import never_delivered
    from arena.peer.reach import PeerReach
    assert never_delivered(AgentCardResolutionError("no card")) and never_delivered(httpx.ConnectError("refused"))
    resp = httpx.Response(503, request=httpx.Request("POST", "http://x/rpc"))
    assert never_delivered(httpx.HTTPStatusError("503", request=resp.request, response=resp))
    for maybe_arrived in (httpx.ReadTimeout("slow"), RuntimeError("bad answer"), KeyError("x")):
        assert not never_delivered(maybe_arrived)

    calls, naps = [], []

    def caller(exc):
        async def a2a_call(url, msg, timeout=None, **kw):
            calls.append(url)
            raise exc
        return a2a_call

    async def nap(sec):
        naps.append(sec)

    class Fixed(PeerReach):
        async def profile_of(self, pub):
            return {"pub": pub, "url": f"http://now/{len(calls)}", "connections": [{"kind": "a2a", "url": f"http://now/{len(calls)}"}]}

    s = dataclasses.replace(world.s, peer_call_retries=3, peer_call_retry_sec=0.5)
    r = Fixed(None, {}, caller(httpx.ReadTimeout("slow")), lambda: None, settings=s, sleep=nap)
    with pytest.raises(httpx.ReadTimeout):
        await r.call("k" * 64, {"op": "x"})
    assert len(calls) == 1 and naps == []  # it may have arrived: never sent twice
    calls.clear()
    r = Fixed(None, {}, caller(AgentCardResolutionError("no card")), lambda: None, settings=s, sleep=nap)
    with pytest.raises(AgentCardResolutionError):
        await r.call("k" * 64, {"op": "x"})
    assert calls == ["http://now/0", "http://now/1", "http://now/2", "http://now/3"]  # the profile is read again each time
    assert naps == [0.5, 1.0, 2.0]  # the wait doubles


async def test_p10c4_a_pending_answer_is_looked_at_where_the_peer_is_now(world):
    world.s = dataclasses.replace(world.s, a2a_task_wait_sec=0.3, a2a_human_wait_sec=0.3)
    _, s1, srv1 = await world.connectivity()
    _, s2, _ = await world.connectivity()
    desk = OwnerDesk(lambda: 0.0, keep=50)
    b = await world.behind(await world.peer("b", DeskOwner(desk, world.s), [AskOwner()], port=False), [s1, s2])
    a = await world.peer("a")
    r = await a.call_peer(b.identity.pub, engage(b.identity.pub), timeout=5)
    assert r.get("pending") and r["pub"] == b.identity.pub and r["url"].startswith(s1)  # the person has not answered yet
    srv1.should_exit = True
    assert await wait_for(lambda: (b.reach_url or "").startswith(s2), 300)  # b moved to the second server
    desk.answer(next(iter(desk.items)), {"yes": True, "why": "좋아요"})
    done = await a.check_task(r["url"], r["task_id"], pub=r["pub"])  # the old address is dead; the key finds it
    assert done["ok"] and done["sig"]
