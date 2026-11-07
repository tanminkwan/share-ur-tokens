"""P10-A: the connectivity server, a general-purpose service. A server with no inbound access polls; a caller's request
to /r/<key>/... is passed to it and its answer comes back. Its rules: sessions, limits, paths, headers, signatures.
Nothing here uses the rest of the repository: the service knows nobody's protocol."""
import asyncio
import base64
import dataclasses

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from connectivity.api import build_connectivity_app
from connectivity.config import ConnectivitySettings
from connectivity.service import ConnectivityService, load_allow_keys
from connectivity.signing import public_hex, sign_headers


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, sec):
        self.t += sec


def make(**over):
    s = dataclasses.replace(ConnectivitySettings(), **{"poll_hold_sec": 1.0, "request_timeout_sec": 2.0, **over})
    clock = Clock()
    svc = ConnectivityService(s, clock=clock)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_connectivity_app(svc)), base_url="http://c")
    return svc, client, clock


class Key:
    def __init__(self):
        self.priv = Ed25519PrivateKey.generate()
        self.pub = public_hex(self.priv)


async def poll(c, k, hold=0.5, clock=None):
    return await c.get(f"/poll?hold={hold}", headers=sign_headers(k.priv.sign, k.pub, "GET", "/poll", now=clock() if clock else None))


async def answer(c, k, request_id, status=200, body=b"{}", headers=None, clock=None):
    path = f"/reply/{request_id}"
    return await c.post(path, headers=sign_headers(k.priv.sign, k.pub, "POST", path, now=clock() if clock else None),
                        json={"status": status, "headers": headers or {}, "body": base64.b64encode(body).decode()})


async def serve_one(c, k, status=200, body=b'{"ok":true}', headers=None, clock=None):
    """what an attached server does: take the next request and answer it"""
    got = (await poll(c, k, hold=1.0, clock=clock)).json()["requests"]
    assert len(got) == 1
    return got[0], await answer(c, k, got[0]["id"], status, body, headers, clock=clock)


# ---- sessions and the tunnel ----
async def test_p10a_a_request_is_passed_to_the_polling_server_and_its_answer_comes_back():
    svc, c, clock = make()
    k = Key()
    first = await poll(c, k, hold=0, clock=clock)  # the first poll starts the session and says where callers reach it
    assert first.status_code == 200 and first.json()["requests"] == []
    assert first.json()["base"] == f"http://127.0.0.1:9200/r/{k.pub}"
    assert svc.health()["attached"] == 1
    call = asyncio.create_task(c.post(f"/r/{k.pub}/rpc?x=1", content=b'{"hello":1}', headers={"content-type": "application/json"}))
    seen, r = await serve_one(c, k, 201, b'{"answer":2}', {"content-type": "application/json", "etag": "e1"}, clock=clock)
    out = await call
    assert r.json() == {"ok": True}
    assert (seen["method"], seen["path"], seen["query"]) == ("POST", "/rpc", "x=1") and base64.b64decode(seen["body"]) == b'{"hello":1}'
    assert out.status_code == 201 and out.content == b'{"answer":2}' and out.headers["etag"] == "e1"


async def test_p10a_a_key_that_is_not_attached_gets_503():
    _, c, _ = make()
    r = await c.get(f"/r/{Key().pub}/rpc")
    assert r.status_code == 503 and "not attached" in r.json()["error"]


async def test_p10a_only_the_key_that_was_given_a_request_can_answer_it():
    _, c, clock = make()
    a, b = Key(), Key()
    await poll(c, a, hold=0, clock=clock)
    await poll(c, b, hold=0, clock=clock)
    call = asyncio.create_task(c.post(f"/r/{a.pub}/rpc", content=b"{}"))
    got = (await poll(c, a, hold=1.0, clock=clock)).json()["requests"][0]
    assert (await answer(c, b, got["id"], clock=clock)).status_code == 404  # b was not given it
    assert (await answer(c, a, got["id"], clock=clock)).status_code == 200
    assert (await call).status_code == 200


async def test_p10a_with_a_path_list_only_those_paths_pass():
    _, c, clock = make(paths=["/rpc", "/.well-known/agent-card.json"])
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    for path in ("/secret", "/", "/rpc/x", "/health"):
        assert (await c.get(f"/r/{k.pub}{path}")).status_code == 404, path
    assert (await c.get("/r/not-a-key/rpc")).status_code == 404


async def test_p10a_without_a_path_list_every_path_passes():
    _, c, clock = make()
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    call = asyncio.create_task(c.get(f"/r/{k.pub}/any/where"))
    seen, _ = await serve_one(c, k, clock=clock)
    assert seen["path"] == "/any/where" and (await call).status_code == 200


async def test_p10a_hop_by_hop_and_dropped_headers_do_not_pass():
    _, c, clock = make()
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    call = asyncio.create_task(c.post(f"/r/{k.pub}/rpc", content=b"{}", headers={
        "content-type": "application/json", "cookie": "s=1", "connection": "keep-alive", "a2a-version": "1.0"}))
    seen, _ = await serve_one(c, k, headers={"set-cookie": "s=1", "content-type": "application/json", "x-thing": "1"}, clock=clock)
    out = await call
    assert "cookie" not in seen["headers"] and "connection" not in seen["headers"] and "host" not in seen["headers"]
    assert seen["headers"]["a2a-version"] == "1.0" and seen["headers"]["content-type"] == "application/json"
    assert "set-cookie" not in out.headers and out.headers["x-thing"] == "1"


# ---- limits ----
async def test_p10a_a_body_over_the_limit_is_refused_both_ways():
    svc, c, clock = make(max_body_bytes=10)
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    assert (await c.post(f"/r/{k.pub}/rpc", content=b"x" * 11)).status_code == 413
    call = asyncio.create_task(c.post(f"/r/{k.pub}/rpc", content=b"x"))
    await serve_one(c, k, body=b"y" * 11, clock=clock)
    assert (await call).status_code == 502  # the answer was too large
    assert svc.health()["refused"]["big_request"] == 1 and svc.health()["refused"]["big_answer"] == 1


async def test_p10a_too_many_requests_from_one_source_to_one_key_get_429():
    _, c, clock = make(rate_per_sec=2.0)
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    calls = [asyncio.create_task(c.post(f"/r/{k.pub}/rpc", content=b"{}")) for _ in range(3)]
    await asyncio.sleep(0.05)
    for g in (await poll(c, k, hold=0.5, clock=clock)).json()["requests"]:
        await answer(c, k, g["id"], clock=clock)
    assert sorted([(await t).status_code for t in calls]) == [200, 200, 429]


async def test_p10a_a_key_cannot_be_given_too_many_requests_at_once():
    _, c, clock = make(max_inflight=1, rate_per_sec=100.0)
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    first = asyncio.create_task(c.post(f"/r/{k.pub}/rpc", content=b"{}"))
    await asyncio.sleep(0.05)
    assert (await c.post(f"/r/{k.pub}/rpc", content=b"{}")).status_code == 429
    got = (await poll(c, k, hold=0.5, clock=clock)).json()["requests"]
    await answer(c, k, got[0]["id"], clock=clock)
    assert (await first).status_code == 200


async def test_p10a_a_request_never_answered_ends_in_504():
    _, c, clock = make(request_timeout_sec=0.2)
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    assert (await c.post(f"/r/{k.pub}/rpc", content=b"{}")).status_code == 504


async def test_p10a_too_many_attached_keys_are_refused():
    _, c, clock = make(max_attached=1)
    a, b = Key(), Key()
    assert (await poll(c, a, hold=0, clock=clock)).status_code == 200
    assert (await poll(c, b, hold=0, clock=clock)).status_code == 429
    assert (await poll(c, a, hold=0, clock=clock)).status_code == 200  # the one already attached goes on


async def test_p10a_a_key_outside_the_allow_list_cannot_attach(tmp_path):
    ok, no = Key(), Key()
    f = tmp_path / "allow.txt"
    f.write_text(f"# who may attach\n{ok.pub}  # a friend\n", encoding="utf-8")
    svc, c, clock = make()
    svc.allow_keys = load_allow_keys(str(f))
    assert (await poll(c, ok, hold=0, clock=clock)).status_code == 200
    assert (await poll(c, no, hold=0, clock=clock)).status_code == 403
    assert load_allow_keys("") is None


# ---- the session ends when polls stop ----
async def test_p10a_when_polls_stop_the_session_closes_and_what_it_carried_ends_in_503():
    svc, c, clock = make(attach_grace_sec=30.0)
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    call = asyncio.create_task(c.post(f"/r/{k.pub}/rpc", content=b"{}"))
    await asyncio.sleep(0.05)
    clock.tick(31)  # it took nothing and polled no more
    assert (await c.get(f"/r/{k.pub}/rpc")).status_code == 503
    assert (await call).status_code == 503
    assert svc.health()["attached"] == 0


async def test_p10a_a_key_that_keeps_polling_stays_attached():
    svc, c, clock = make(attach_grace_sec=30.0)
    k = Key()
    for _ in range(3):
        await poll(c, k, hold=0, clock=clock)
        clock.tick(20)
    assert svc.health()["attached"] == 1


# ---- signatures ----
async def test_p10a_poll_and_reply_need_the_keys_signature():
    _, c, clock = make()
    k = Key()
    assert (await c.get("/poll?hold=0")).status_code == 401
    assert (await c.post("/reply/x", json={"status": 200, "body": ""})).status_code == 401
    old = sign_headers(k.priv.sign, k.pub, "GET", "/poll", now=clock() - 3600)  # outside the time window
    assert (await c.get("/poll?hold=0", headers=old)).status_code == 401
    other_path = sign_headers(k.priv.sign, k.pub, "GET", "/other", now=clock())
    assert (await c.get("/poll?hold=0", headers=other_path)).status_code == 401


async def test_p10a_health_shows_counts_and_never_what_passed():
    svc, c, clock = make()
    k = Key()
    await poll(c, k, hold=0, clock=clock)
    call = asyncio.create_task(c.post(f"/r/{k.pub}/rpc", content='{"secret":"파란 하늘"}'.encode()))
    await serve_one(c, k, body='{"reply":"비밀 답"}'.encode(), clock=clock)
    await call
    h = (await c.get("/health")).json()
    assert h["attached"] == 1 and h["relayed_bytes"] > 0
    assert "파란" not in str(h) and "비밀" not in str(h)


def test_p10a_settings_come_from_the_environment():
    s = ConnectivitySettings.from_env({"CONNECTIVITY_PORT": "9300", "CONNECTIVITY_PATHS": "/a, /b", "CONNECTIVITY_TRUST_FORWARDED": "true",
                                       "CONNECTIVITY_PUBLIC_URL": "https://connect.example.com/"})
    assert s.port == 9300 and s.paths == ["/a", "/b"] and s.trust_forwarded and s.base_url == "https://connect.example.com"
    assert ConnectivitySettings.from_env({}).drop_headers == ["cookie", "set-cookie"]
