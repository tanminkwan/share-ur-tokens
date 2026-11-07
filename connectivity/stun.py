"""Minimal STUN (RFC 5389): binding request and answer only, no TURN, no other attributes (dev/phase10/design.md 8).
The server tells whoever asks the address it saw them from (XOR-MAPPED-ADDRESS). The asking side learns two things:
whether UDP gets out at all, and how it looks from outside. Nothing else here depends on UDP: everything also works over TCP."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import struct

MAGIC = 0x2112A442
BINDING_REQUEST, BINDING_SUCCESS = 0x0001, 0x0101
XOR_MAPPED_ADDRESS = 0x0020
HEADER = struct.Struct("!HHI12s")  # type, length, magic cookie, transaction id


def binding_request(txid: bytes | None = None) -> bytes:
    return HEADER.pack(BINDING_REQUEST, 0, MAGIC, txid or os.urandom(12))


def parse_request(data: bytes) -> bytes | None:
    """the transaction id of a well-formed binding request with no attributes, else None (anything else gets no answer)"""
    if len(data) != HEADER.size:
        return None
    kind, length, magic, txid = HEADER.unpack(data)
    return txid if kind == BINDING_REQUEST and length == 0 and magic == MAGIC else None


def _xor_key(txid: bytes, family: int) -> bytes:
    return struct.pack("!I", MAGIC) + (txid if family == 2 else b"")


def binding_response(txid: bytes, ip: str, port: int) -> bytes:
    addr = ipaddress.ip_address(ip)
    family = 1 if addr.version == 4 else 2
    key = _xor_key(txid, family)
    xaddr = bytes(a ^ b for a, b in zip(addr.packed, key))
    value = struct.pack("!BBH", 0, family, port ^ (MAGIC >> 16)) + xaddr
    attr = struct.pack("!HH", XOR_MAPPED_ADDRESS, len(value)) + value
    return HEADER.pack(BINDING_SUCCESS, len(attr), MAGIC, txid) + attr


def parse_response(data: bytes, txid: bytes) -> tuple[str, int] | None:
    """(ip, port) from a binding answer to my transaction, else None"""
    if len(data) < HEADER.size:
        return None
    kind, length, magic, got = HEADER.unpack(data[:HEADER.size])
    if kind != BINDING_SUCCESS or magic != MAGIC or got != txid or len(data) != HEADER.size + length:
        return None
    i = HEADER.size
    while i + 4 <= len(data):
        atype, alen = struct.unpack("!HH", data[i:i + 4])
        value = data[i + 4:i + 4 + alen]
        if atype == XOR_MAPPED_ADDRESS and len(value) in (8, 20):
            family, xport = value[1], struct.unpack("!H", value[2:4])[0]
            key = _xor_key(txid, family)
            raw = bytes(a ^ b for a, b in zip(value[4:], key))
            return str(ipaddress.ip_address(raw)), xport ^ (MAGIC >> 16)
        i += 4 + alen + (-alen % 4)  # attributes are padded to 4 bytes
    return None


class _Answer(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        txid = parse_request(data)
        if txid is not None:  # the answer is barely larger than the request: no amplification worth having
            self.transport.sendto(binding_response(txid, addr[0], addr[1]), addr)


async def serve(host: str, port: int):
    """answer binding requests on host:port (UDP); returns the transport (close() to stop)"""
    loop = asyncio.get_running_loop()
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    transport, _ = await loop.create_datagram_endpoint(_Answer, local_addr=(host, port), family=family)
    return transport


class _Ask(asyncio.DatagramProtocol):
    def __init__(self, txid: bytes):
        self.txid, self.got = txid, asyncio.get_running_loop().create_future()

    def datagram_received(self, data, addr):
        found = parse_response(data, self.txid)
        if found and not self.got.done():
            self.got.set_result(found)

    def error_received(self, exc):  # e.g. port unreachable: keep waiting, the timeout decides
        pass


async def check(host: str, port: int, timeout: float, tries: int = 3) -> dict:
    """ask once (sent `tries` times within the timeout, UDP may drop one). {udp: True, mapped: "ip:port"} or
    {udp: False, mapped: None, why}: no answer is a normal outcome (UDP blocked), never an exception"""
    loop = asyncio.get_running_loop()
    txid = os.urandom(12)
    try:
        info = await loop.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
        transport, proto = await loop.create_datagram_endpoint(lambda: _Ask(txid), remote_addr=info[0][4][:2], family=info[0][0])
    except OSError as e:
        return {"udp": False, "mapped": None, "why": f"{type(e).__name__}: {e}"}
    try:
        for _ in range(tries):
            transport.sendto(binding_request(txid))
            try:
                ip, p = await asyncio.wait_for(asyncio.shield(proto.got), timeout / tries)
                return {"udp": True, "mapped": f"[{ip}]:{p}" if ":" in ip else f"{ip}:{p}"}
            except asyncio.TimeoutError:
                continue
        return {"udp": False, "mapped": None, "why": f"no STUN answer from {host}:{port} in {timeout:g}s"}
    finally:
        transport.close()
