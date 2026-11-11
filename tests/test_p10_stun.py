"""P10-C6, C7 (10-D): minimal STUN. The connectivity server answers STUN binding requests on UDP (CONNECTIVITY_STUN_PORT, off by
default); a peer asks once at startup and shows whether UDP works and the address seen from outside. Only shown: no path
depends on it, and "UDP does not work" is not an error (everything works over TCP). Real UDP sockets on loopback."""
import asyncio
import dataclasses
import socket

import httpx
import pytest

from arena.peer.desk import OwnerDesk
from arena.peer.relay_link import RelayLink
from connectivity import stun
from connectivity.client import TunnelClient
from tests.test_p10_relay import world  # noqa: F401  (fixture)

TXID = bytes.fromhex("b7e7a701bc34d686fa87dfae")  # RFC 5769 2.2


def udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---- the packets (RFC 5389) ----

def test_p10c7_a_binding_request_has_the_standard_header():
    req = stun.binding_request(TXID)
    assert len(req) == 20 and req[:2] == b"\x00\x01" and req[2:4] == b"\x00\x00" and req[4:8] == bytes.fromhex("2112a442")
    assert req[8:] == TXID and stun.parse_request(req) == TXID


def test_p10c7_the_answer_carries_the_xor_mapped_address_of_rfc_5769():
    res = stun.binding_response(TXID, "192.0.2.1", 32853)
    assert res[:2] == b"\x01\x01" and res[4:8] == bytes.fromhex("2112a442") and res[8:20] == TXID
    assert bytes.fromhex("0020000800 01a147e112a643".replace(" ", "")) in res  # the RFC's own bytes for 192.0.2.1:32853
    assert stun.parse_response(res, TXID) == ("192.0.2.1", 32853)
    v6 = stun.binding_response(TXID, "2001:db8:1234:5678:11:2233:4455:6677", 32853)
    assert stun.parse_response(v6, TXID) == ("2001:db8:1234:5678:11:2233:4455:6677", 32853)


def test_p10c7_anything_else_is_not_a_binding_request_or_answer():
    good = stun.binding_request(TXID)
    for bad in (b"", good[:19], b"\x00\x02" + good[2:], good[:4] + b"\x00\x00\x00\x00" + good[8:],  # type, magic
                good[:2] + b"\x00\x04" + good[4:],  # says it has attributes it does not have
                b"\x80" + good[1:]):  # the first two bits must be zero
        assert stun.parse_request(bad) is None
    res = stun.binding_response(TXID, "192.0.2.1", 1)
    assert stun.parse_response(res, b"x" * 12) is None and stun.parse_response(res[:24], TXID) is None


# ---- a real UDP server on loopback ----

async def test_p10c7_the_server_answers_and_the_check_says_udp_works():
    port = udp_port()
    server = await stun.serve("127.0.0.1", port)
    try:
        r = await stun.check("127.0.0.1", port, timeout=2.0)
        assert r["udp"] is True and r["mapped"].startswith("127.0.0.1:")
    finally:
        server.close()


async def test_p10c7_no_answer_means_udp_does_not_work_and_is_not_an_error():
    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # bound, never answers (UDP dropped on the way)
    silent.bind(("127.0.0.1", 0))
    try:
        r = await stun.check("127.0.0.1", silent.getsockname()[1], timeout=0.5)
        assert r == {"udp": False, "mapped": None, "why": r["why"]} and r["why"]
    finally:
        silent.close()
    r = await stun.check("127.0.0.1", udp_port(), timeout=0.5)  # nothing there at all
    assert r["udp"] is False


async def test_p10c7_the_server_says_nothing_to_what_is_not_a_binding_request():
    port = udp_port()
    server = await stun.serve("127.0.0.1", port)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(False)
    try:
        s.sendto(b"\x00\x01\x00\x00hello, not stun", ("127.0.0.1", port))
        s.sendto(stun.binding_request(TXID), ("127.0.0.1", port))
        loop = asyncio.get_running_loop()
        first = await asyncio.wait_for(loop.sock_recv(s, 2048), 2)
        assert stun.parse_response(first, TXID)  # the only answer is to the real request
    finally:
        s.close()
        server.close()


# ---- the server tells where its STUN port is; the client checks through it ----

async def test_p10c7_the_server_names_its_stun_port_and_the_client_checks_udp(world):  # noqa: F811
    port = udp_port()
    _, server, _ = await world.connectivity(stun_port=port)
    _, plain, _ = await world.connectivity()
    async with httpx.AsyncClient() as hc:
        assert (await hc.get(f"{server}/info")).json() == {"ok": True, "stun_port": port, "out": False}
        assert (await hc.get(f"{plain}/info")).json() == {"ok": True, "stun_port": None, "out": False}
    stun_server = await stun.serve("127.0.0.1", port)  # the HTTP server here does not open UDP itself (python -m does)
    try:
        c = TunnelClient([plain, server], "k" * 64, lambda b: b"", None)
        r = await c.udp_check(timeout=2.0)
        assert r["udp"] is True and r["server"] == server and r["mapped"].startswith("127.0.0.1:")
        assert (await TunnelClient([plain], "k" * 64, lambda b: b"", None).udp_check(timeout=0.5))["udp"] is None  # nobody offers it
    finally:
        stun_server.close()


async def test_p10c6_the_peer_shows_udp_in_its_window_and_takes_no_other_path(world):  # noqa: F811
    from arena.bundled.owner_service import OwnerService
    from arena.peer.assistant import EventAssistant
    port = udp_port()
    stun_server = await stun.serve("127.0.0.1", port)
    try:
        _, server, _ = await world.connectivity(stun_port=port)
        b = await world.peer("b", apps=[EventAssistant(world.s)], port=False, post=False)
        b.relay = RelayLink(b, [server])
        assert await b.relay.start() == "relay"  # the path is decided by the TCP check only
        for _ in range(100):
            if b.relay.state["udp"] is not None:
                break
            await asyncio.sleep(0.02)
        me = OwnerService(b, OwnerDesk(lambda: 0.0, keep=10)).state()["me"]
        assert me["reach"] == "relay" and me["udp"] is True and b.relay.state["mapped"].startswith("127.0.0.1:")
        await b.relay.close()
    finally:
        stun_server.close()
    _, plain, _ = await world.connectivity()
    c = await world.peer("c", apps=[EventAssistant(world.s)], port=False, post=False)
    c.relay = RelayLink(c, [plain])
    await c.relay.start()
    await asyncio.sleep(0.2)
    assert OwnerService(c, OwnerDesk(lambda: 0.0, keep=10)).state()["me"]["udp"] is None  # nothing to show
    await c.relay.close()


def test_p10c7_stun_is_off_unless_the_operator_opens_it():
    from connectivity.config import ConnectivitySettings
    assert ConnectivitySettings().stun_port == 0 and dataclasses.is_dataclass(ConnectivitySettings)
    assert "CONNECTIVITY_STUN_PORT=0" in open("deploy/connectivity/.env.example", encoding="utf-8").read()


@pytest.mark.parametrize("ip", ["10.0.0.1", "::1"])
def test_p10c7_both_address_families_round_trip(ip):
    assert stun.parse_response(stun.binding_response(TXID, ip, 3478), TXID) == (ip, 3478)
