"""P10-F: the connectivity server's way out (POST /out): a general HTTP forward for a signed key (dev/phase10/out-gateway.md).
Nothing here knows any protocol of this repository. The target is faked with httpx.MockTransport and a fake resolver, so
what the server does with a target (check, pin, forward, limit) is seen without a network."""
import base64
import dataclasses
import json
import time

import httpx
import pytest

from connectivity.api import build_connectivity_app
from connectivity.client import OutTransport, TunnelClient
from connectivity.config import ConnectivitySettings
from connectivity.out import OutGateway
from connectivity.service import ConnectivityService
from connectivity.signing import public_hex, sign_headers
from tests.test_p10_connectivity_service import Clock, Key

PUBLIC = "93.184.216.34"


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


class Target:
    """what the server reaches: records each request, answers as told"""

    def __init__(self):
        self.seen: list[httpx.Request] = []
        self.status, self.headers, self.body = 200, {"content-type": "application/json", "set-cookie": "a=b", "x-up": "1"}, b'{"up":1}'
        self.fail: Exception | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.fail:
            raise self.fail
        return httpx.Response(self.status, headers=self.headers, content=self.body)


def make(addresses=None, real_time=False, **over):
    s = dataclasses.replace(ConnectivitySettings(), **{"out_enabled": True, "request_timeout_sec": 2.0, **over})
    clock, target = (time.time if real_time else Clock()), Target()
    svc = ConnectivityService(s, clock=clock)
    table = {"example.com": [PUBLIC], **(addresses or {})}

    async def resolve(host):
        return table.get(host) or [host]  # an address literal is itself

    svc.out = OutGateway(s, resolve=resolve, transport=httpx.MockTransport(target))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_connectivity_app(svc)), base_url="http://c")
    return svc, client, clock, target


async def out(c, k, clock, url="http://example.com/rpc", method="POST", headers=None, body=b'{"x":1}', **raw):
    payload = json.dumps({"url": url, "method": method, "headers": headers or {"content-type": "application/json"}, "body": b64(body), **raw}).encode()
    if hasattr(clock, "tick"):
        clock.tick(0.001)  # each call is made at its own moment, as in life: the same signature is never made twice
    h = sign_headers(k.priv.sign, k.pub, "POST", "/out", now=clock(), body=payload)
    return await c.post("/out", content=payload, headers=h)


# ---- off by default, who may ----
async def test_p10f2_out_is_off_unless_the_operator_turns_it_on():
    assert ConnectivitySettings().out_enabled is False
    svc, c, clock, _ = make(out_enabled=False)
    assert (await c.get("/info")).json()["out"] is False
    r = await out(c, Key(), clock)
    assert r.status_code == 403 and r.json()["why"] == "out_off"


async def test_p10f2_info_says_out_when_it_is_on():
    _, c, _, _ = make()
    assert (await c.get("/info")).json()["out"] is True


async def test_p10f3_an_unsigned_request_is_refused():
    _, c, _, target = make()
    r = await c.post("/out", json={"url": "http://example.com/", "method": "GET", "headers": {}, "body": ""})
    assert r.status_code == 401 and not target.seen


async def test_p10f3_the_signature_covers_the_body_so_a_changed_target_is_refused():
    _, c, clock, target = make()
    k = Key()
    good = json.dumps({"url": "http://example.com/a", "method": "GET", "headers": {}, "body": ""}).encode()
    h = sign_headers(k.priv.sign, k.pub, "POST", "/out", now=clock(), body=good)
    evil = json.dumps({"url": "http://example.com/b", "method": "GET", "headers": {}, "body": ""}).encode()
    r = await c.post("/out", content=evil, headers=h)  # someone on the way keeps the headers and swaps the target
    assert r.status_code == 401 and not target.seen


async def test_p10f3_the_same_signature_is_taken_once():
    _, c, clock, target = make()
    k = Key()
    body = json.dumps({"url": "http://example.com/a", "method": "GET", "headers": {}, "body": ""}).encode()
    h = sign_headers(k.priv.sign, k.pub, "POST", "/out", now=clock(), body=body)
    assert (await c.post("/out", content=body, headers=h)).status_code == 200
    assert (await c.post("/out", content=body, headers=h)).status_code == 401  # a copy of it is not
    assert len(target.seen) == 1


async def test_p10f3_only_listed_keys_when_there_is_a_list():
    svc, c, clock, target = make()
    k, other = Key(), Key()
    svc.allow_keys = {k.pub}
    assert (await out(c, k, clock)).status_code == 200
    r = await out(c, other, clock)
    assert r.status_code == 403 and r.json()["why"] == "not_allowed" and len(target.seen) == 1


# ---- what is forwarded, and how ----
async def test_p10f1_the_request_is_forwarded_and_the_answer_comes_back():
    _, c, clock, target = make()
    target.status, target.body = 201, b'{"answer":2}'
    r = await out(c, Key(), clock, url="http://example.com:8080/rpc?x=1", method="POST", headers={"content-type": "application/json", "x-a": "1"})
    d = r.json()
    assert r.status_code == 200 and d["ok"] and d["status"] == 201 and base64.b64decode(d["body"]) == b'{"answer":2}'
    sent = target.seen[0]
    assert (sent.method, sent.url.path, sent.url.query, sent.content) == ("POST", "/rpc", b"x=1", b'{"x":1}')
    assert sent.headers["x-a"] == "1" and sent.headers["host"] == "example.com:8080"  # the name stays in Host


async def test_p10f4_the_connection_goes_to_the_address_that_was_checked():
    _, c, clock, target = make()
    await out(c, Key(), clock, url="https://example.com/rpc")
    sent = target.seen[0]
    assert sent.url.host == PUBLIC and sent.url.scheme == "https"  # not the name: it could answer differently the second time
    assert sent.extensions["sni_hostname"] == b"example.com" or sent.extensions["sni_hostname"] == "example.com"


async def test_p10f6_cookies_and_hop_headers_do_not_pass_either_way_and_redirects_are_not_followed():
    _, c, clock, target = make()
    target.status, target.headers = 302, {"location": "http://10.0.0.1/", "set-cookie": "a=b", "connection": "close", "x-up": "1"}
    r = await out(c, Key(), clock, headers={"cookie": "me=1", "proxy-authorization": "secret", "x-a": "1"})
    d = r.json()
    assert d["status"] == 302 and len(target.seen) == 1  # the 302 is the answer; the caller decides what to do with it
    assert "cookie" not in target.seen[0].headers and "proxy-authorization" not in target.seen[0].headers and target.seen[0].headers["x-a"] == "1"
    assert "set-cookie" not in d["headers"] and "connection" not in d["headers"] and d["headers"]["x-up"] == "1"


# ---- the server must not become a way into a private network ----
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://10.1.2.3:9100/profiles", "http://192.168.0.1/", "http://169.254.169.254/latest/",
                                 "http://[::1]/", "http://localhost/", "http://internal.example.com/", "http://172.16.0.5/"])
async def test_p10f4_a_target_that_is_not_public_is_refused(url):
    _, c, clock, target = make({"localhost": ["127.0.0.1"], "internal.example.com": ["10.9.9.9"]})
    r = await out(c, Key(), clock, url=url)
    assert r.status_code == 403 and r.json()["why"] == "bad_target" and not target.seen


async def test_p10f4_one_private_address_among_the_resolved_ones_is_enough_to_refuse():
    _, c, clock, target = make({"mixed.example.com": [PUBLIC, "10.0.0.7"]})
    r = await out(c, Key(), clock, url="http://mixed.example.com/")
    assert r.status_code == 403 and not target.seen


@pytest.mark.parametrize("url", ["ftp://example.com/", "file:///etc/passwd", "http://user:pw@example.com/", "example.com/no-scheme", "http:///x"])
async def test_p10f4_only_http_and_https_without_credentials(url):
    _, c, clock, target = make()
    r = await out(c, Key(), clock, url=url)
    assert r.status_code == 403 and r.json()["why"] == "bad_target" and not target.seen


async def test_p10f4_a_range_the_operator_allowed_is_reached():
    _, c, clock, target = make(out_allow=["10.0.0.0/8"])
    assert (await out(c, Key(), clock, url="http://10.1.2.3:9100/profiles")).status_code == 200
    assert (await out(c, Key(), clock, url="http://192.168.0.1/")).status_code == 403
    assert len(target.seen) == 1


async def test_p10f4_only_the_listed_ports_when_there_is_a_list():
    _, c, clock, target = make(out_ports=[80, 443, 9100])
    assert (await out(c, Key(), clock, url="http://example.com:9100/")).status_code == 200
    assert (await out(c, Key(), clock, url="http://example.com:25/")).status_code == 403
    assert (await out(c, Key(), clock, url="http://example.com/")).status_code == 200  # the default port of http is 80
    assert len(target.seen) == 2


# ---- limits ----
async def test_p10f5_too_many_calls_per_second_from_one_key():
    _, c, clock, _ = make(out_rate_per_sec=3)
    k = Key()
    codes = [(await out(c, k, clock)).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert (await out(c, Key(), clock)).status_code == 200  # another key has its own allowance


async def test_p10f5_a_request_body_over_the_limit():
    _, c, clock, target = make(max_body_bytes=100)
    r = await out(c, Key(), clock, body=b"x" * 101)
    assert r.status_code == 413 and not target.seen


async def test_p10f5_an_answer_over_the_limit():
    _, c, clock, target = make(max_body_bytes=100)
    target.body = b"x" * 101
    r = await out(c, Key(), clock)
    assert r.status_code == 502 and r.json()["why"] == "big_answer"


async def test_p10f5_a_target_that_cannot_be_reached_and_one_that_is_too_slow():
    _, c, clock, target = make()
    target.fail = httpx.ConnectError("no route")
    r = await out(c, Key(), clock)
    assert r.status_code == 502 and r.json()["why"] == "unreachable"
    target.fail = httpx.ReadTimeout("slow")
    r = await out(c, Key(), clock)
    assert r.status_code == 504 and r.json()["why"] == "out_timeout"


async def test_p10f5_too_many_in_flight_for_one_key():
    svc, c, clock, target = make(out_max_inflight=1)
    k = Key()
    svc.out.inflight[k.pub] = 1  # one is still being carried
    r = await out(c, k, clock)
    assert r.status_code == 429 and r.json()["why"] == "out_inflight" and not target.seen


async def test_p10f7_health_counts_and_never_shows_what_was_called():
    _, c, clock, _ = make()
    await out(c, Key(), clock, url="http://example.com/very-private-path")
    await out(c, Key(), clock, url="http://127.0.0.1/")
    h = (await c.get("/health")).json()
    assert h["out_calls"] == 1 and h["refused"]["bad_target"] == 1 and h["out_bytes"] > 0
    assert "very-private-path" not in json.dumps(h) and "example.com" not in json.dumps(h)


# ---- the client: what a peer behind a firewall uses ----
async def outside(host):  # tests: every host counts as outside my network (loopback stands in for the internet)
    return False


class Seen:
    def __init__(self):
        self.direct: list[httpx.Request] = []

    def __call__(self, request):
        self.direct.append(request)
        return httpx.Response(200, json={"direct": True})


def client_for(svc_client, key, servers):
    tc = TunnelClient(servers, key.pub, key.priv.sign, app=None)
    tc.http = lambda: svc_client  # tests: the server is reached in process
    tc.out_ok = True
    return tc


async def test_p10f8_a_call_to_a_third_party_goes_through_the_server():
    svc, c, clock, target = make(real_time=True)
    k, seen = Key(), Seen()
    tc = client_for(c, k, ["http://c"])
    async with httpx.AsyncClient(transport=OutTransport(tc, inner=httpx.MockTransport(seen), local=outside)) as hc:
        r = await hc.post("http://example.com/rpc", json={"q": 1}, headers={"x-a": "1"})
    assert r.status_code == 200 and r.json() == {"up": 1} and not seen.direct
    assert target.seen[0].headers["x-a"] == "1" and json.loads(target.seen[0].content) == {"q": 1}


async def test_p10f8_the_servers_own_address_is_not_sent_through_itself():
    svc, c, clock, target = make(real_time=True)
    seen = Seen()
    tc = client_for(c, Key(), ["http://c.example.org:9200"])
    async with httpx.AsyncClient(transport=OutTransport(tc, inner=httpx.MockTransport(seen), local=outside)) as hc:
        await hc.get("http://c.example.org:9200/r/abc/rpc")  # a relay address of another peer: the server is right there
    assert len(seen.direct) == 1 and not target.seen


async def test_p10f8_without_out_on_the_server_the_call_goes_straight_out():
    svc, c, clock, target = make(real_time=True)
    seen = Seen()
    tc = client_for(c, Key(), ["http://c"])
    tc.out_ok = False  # GET /info said out: false (or the server is an older one)
    async with httpx.AsyncClient(transport=OutTransport(tc, inner=httpx.MockTransport(seen), local=outside)) as hc:
        await hc.get("http://example.com/")
    assert len(seen.direct) == 1 and not target.seen


async def test_p10f8_a_refusal_comes_back_as_an_error_the_caller_can_read():
    svc, c, clock, target = make(real_time=True)
    tc = client_for(c, Key(), ["http://c"])
    async with httpx.AsyncClient(transport=OutTransport(tc, inner=httpx.MockTransport(Seen()), local=outside)) as hc:
        with pytest.raises(httpx.ConnectError) as e:
            await hc.get("http://127.0.0.1/")
    assert "bad_target" in str(e.value)


def test_p10f_signing_without_a_body_is_what_it_was():
    """the other paths (poll, reply, reach) sign no body and keep verifying as before"""
    from connectivity.signing import verify_headers
    k = Key()
    h = sign_headers(k.priv.sign, k.pub, "GET", "/poll", now=1_800_000_000.0)
    assert verify_headers(h, "GET", "/poll", now=1_800_000_000.0, window=60) == k.pub
    hb = sign_headers(k.priv.sign, k.pub, "POST", "/out", now=1_800_000_000.0, body=b"abc")
    assert verify_headers(hb, "POST", "/out", now=1_800_000_000.0, window=60, body=b"abc") == k.pub
    from connectivity.signing import SignatureError
    with pytest.raises(SignatureError):
        verify_headers(hb, "POST", "/out", now=1_800_000_000.0, window=60, body=b"abd")
    with pytest.raises(SignatureError):  # a body was signed, but the caller says there is none: not the same thing
        verify_headers(hb, "POST", "/out", now=1_800_000_000.0, window=60)


async def test_p10f8_a_private_address_goes_through_the_server_too():
    """once attached, an address is written as the server sees it: a broker at 10.10.0.5 beside the server is reached by
    the server (the operator allows that one address), not tried from my own network where it does not exist"""
    svc, c, clock, target = make(real_time=True, out_allow=["10.10.0.5/32"])
    seen = Seen()
    tc = client_for(c, Key(), ["http://c"])
    async with httpx.AsyncClient(transport=OutTransport(tc, inner=httpx.MockTransport(seen))) as hc:
        r = await hc.get("http://10.10.0.5:9100/profiles")
        assert r.status_code == 200 and not seen.direct and len(target.seen) == 1
        with pytest.raises(httpx.ConnectError) as e:  # another private address: still sent to the server, which refuses it
            await hc.get("http://192.168.1.5/")
    assert "bad_target" in str(e.value) and not seen.direct


async def test_p10f8_only_the_llm_gateway_inside_my_network_is_reached_straight():
    """a company LLM gateway is in my network, where the server cannot reach: named in `straight`, it goes straight while
    it is inside; the same origin outside my network, or another port of that host, goes through the server"""
    svc, c, clock, target = make(real_time=True)
    seen = Seen()
    tc = client_for(c, Key(), ["http://c"])
    gw = "http://10.1.2.3:8080"
    async with httpx.AsyncClient(transport=OutTransport(tc, inner=httpx.MockTransport(seen), straight=[gw, None])) as hc:
        await hc.post(f"{gw}/v1/chat/completions", json={})
        assert len(seen.direct) == 1
        with pytest.raises(httpx.ConnectError):
            await hc.get("http://10.1.2.3:9100/")  # same host, not the gateway's origin
    assert len(seen.direct) == 1
    seen = Seen()
    async with httpx.AsyncClient(transport=OutTransport(tc, inner=httpx.MockTransport(seen), straight=["http://example.com"],
                                                        local=outside)) as hc:
        await hc.get("http://example.com/v1/chat/completions")  # a gateway on the internet: the server carries it
    assert not seen.direct and len(target.seen) == 1


async def test_p10f8_inside_my_network_is_told_by_the_address_or_what_the_name_resolves_to():
    from connectivity.client import inside_my_network
    assert await inside_my_network("10.0.0.1") and await inside_my_network("127.0.0.1") and await inside_my_network("::1")
    assert not await inside_my_network("93.184.216.34")
    assert await inside_my_network("localhost")
    assert not await inside_my_network("no-such-name.invalid")  # a name I cannot resolve here is somewhere outside
