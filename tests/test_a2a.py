"""P2-B6, P2-B7: a real A2A server/client round trip, and the in-process transport."""
import pytest

from arena.a2a import A2ATransport, LocalTransport, build_a2a_app
from arena.serve import serve_background
from tests.test_processes import free_port


async def echo(msg):
    if msg.get("op") == "boom":
        raise RuntimeError("bad thing")
    return {"ok": True, "got": msg}


async def test_pb6_real_a2a_round_trip(settings):
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    srv = await serve_background(build_a2a_app("peer-x", "test peer", url, ["echo"], echo), "127.0.0.1", port)
    try:
        t = A2ATransport(settings)
        r = await t.call(url, {"op": "echo", "text": "안녕"})
        assert r == {"ok": True, "got": {"op": "echo", "text": "안녕"}}
        r = await t.call(url, {"op": "boom"})
        assert r["ok"] is False and "bad thing" in r["error"]
        import httpx
        async with httpx.AsyncClient() as hc:
            card = (await hc.get(url + "/.well-known/agent-card.json")).json()
        assert card["name"] == "peer-x" and [s["id"] for s in card["skills"]] == ["echo"]
    finally:
        srv.should_exit = True


async def test_pb7_local_transport_copies_messages():
    t = LocalTransport()
    t.register("mem://a", echo)
    msg = {"op": "echo", "n": [1]}
    r = await t.call("mem://a", msg)
    r["got"]["n"].append(2)
    assert msg["n"] == [1]  # JSON round trip like the real wire
    with pytest.raises(ConnectionError):
        await t.call("mem://nobody", {})
