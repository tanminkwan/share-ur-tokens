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

    async def peer(self, name, owner=None, apps=(), port=True):
        (self.tmp / name).mkdir()
        url = f"http://127.0.0.1:{free_port()}"
        p = Peer(Identity.generate(), self.s, PeerConfig(url=url), LocalFolderArea(str(self.tmp / name), self.s), owner or NoOwner(),
                 NoLLM(), A2ATransport(self.s), EventLog(keep=50, echo=False), brokers={"public": InMemoryBrokerClient(self.broker)},
                 apps=list(apps))
        if port:  # a peer behind a firewall serves nothing: nobody can reach this address
            self.servers.append(await serve_background(p.a2a_app(), "127.0.0.1", int(url.rsplit(":", 1)[1])))
        await p.scheduler.start(p.ctx(p.scheduler))
        await p.advertise()
        return p

    async def behind(self, p, servers):
        """the peer attaches to the connectivity server(s); returns once callers can reach it"""
        p.relay = RelayLink(p, servers)
        self.tasks.append(asyncio.create_task(p.relay.run()))
        for _ in range(200):
            if p.relay_url:
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


async def test_p10b_when_the_server_goes_the_peer_falls_back_and_moves_to_the_next(world):
    dead = f"http://127.0.0.1:{free_port()}"  # nothing listens here
    _, server, srv = await world.connectivity()
    b = await world.behind(await world.peer("b", port=False), [dead, server])
    assert b.url.startswith(server) and b.relay.state["server"] == server
    srv.should_exit = True  # the server goes away
    for _ in range(300):
        if b.relay_url is None:
            break
        await asyncio.sleep(0.05)
    assert b.url == b.config.url and world.broker.profiles[b.identity.pub]["url"] == b.config.url
    _, server2, _ = await world.connectivity()  # another comes; the peer is pointed at it next time it starts
    b2 = await world.behind(await world.peer("b2", port=False), [dead, server2])
    assert b2.url.startswith(server2)


async def test_p10b_the_peer_attaches_once_the_server_comes(world):
    port = free_port()
    server = f"http://127.0.0.1:{port}"
    b = await world.peer("b", port=False)
    b.relay = RelayLink(b, [server])
    world.tasks.append(asyncio.create_task(b.relay.run()))
    await asyncio.sleep(0.3)
    assert b.relay_url is None and b.relay.state["error"]  # not there yet: it keeps trying
    cs = dataclasses.replace(ConnectivitySettings(), public_url=server, poll_hold_sec=2.0)
    world.servers.append(await serve_background(build_connectivity_app(ConnectivityService(cs)), "127.0.0.1", port))
    for _ in range(200):
        if b.relay_url:
            break
        await asyncio.sleep(0.02)
    assert b.relay_url == f"{server}/r/{b.identity.pub}"
