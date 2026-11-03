"""Edges of the platform's plumbing: the REST binding and A2A on real sockets, the window base class, the runners'
assembly, the Claude adapter with a stand-in client (no network, no real LLM)."""
import asyncio
import dataclasses
import json
import sys
import types

import httpx
import pytest

from arena.a2a import LocalTransport, ask_agent
from arena.bundled.web import LocalWebApp
from arena.llm import LLMError, NoLLM, build_llm, llm_available
from arena.rest import RestTransport, build_rest_app
from arena.serve import serve_background
from tests.test_assistant import eco  # noqa: F401  (fixture)
from tests.test_processes import free_port


async def echo(msg, meta):
    if msg.get("op") == "boom":
        raise RuntimeError("broke")
    return {"ok": True, "got": msg, "meta": meta}


async def test_rest_binding_refuses_bad_bodies_and_reports_handler_errors(settings):
    app = build_rest_app(echo)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as hc:
        assert (await hc.post("/ops/x", content=b"not json")).status_code == 400
        assert (await hc.post("/ops/x", json=[1, 2])).status_code == 400
        assert (await hc.post("/ops/boom", json={})).json() == {"ok": False, "error": "RuntimeError: broke"}
        r = (await hc.post("/ops/hello", json={"a": 1}, headers={"X-Arena-Group": "g", "X-Arena-Event": "e"})).json()
        assert r["got"] == {"a": 1, "op": "hello"} and r["meta"]["group_id"] == "g" and r["meta"]["event_id"] == "e"
    port = free_port()  # RestTransport with its own client, on a real socket
    srv = await serve_background(app, "127.0.0.1", port)
    try:
        r = await RestTransport(settings).call(f"http://127.0.0.1:{port}", {"op": "hello", "b": 2}, meta={"group_id": "g"})
        assert r["got"] == {"b": 2, "op": "hello"} and r["meta"]["group_id"] == "g"
    finally:
        srv.should_exit = True


async def test_a2a_local_transport_and_plain_text_agents(eco, settings):
    with pytest.raises(ConnectionError):
        await LocalTransport().call("mem://nowhere", {"op": "x"})
    port = free_port()
    eco.a.config.url = f"http://127.0.0.1:{port}"  # the agent card names a real address
    srv = await serve_background(eco.a.a2a_app(), "127.0.0.1", port)
    try:
        reply = await ask_agent(f"http://127.0.0.1:{port}", json.dumps({"op": "no-such-op"}), timeout=10)
        assert "unknown op" in reply  # any A2A client can talk to a peer; it answers in the platform's JSON
    finally:
        srv.should_exit = True
    await asyncio.sleep(0.05)


async def test_a_window_app_opens_and_closes_its_local_web(settings):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    class Hello(LocalWebApp):
        name, version, app_id = "hello-window", "1.0", "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"

        def web_app(self, ctx):
            return Starlette(routes=[Route("/", lambda r: PlainTextResponse("hi"))])

    class Ctx:
        pen = "필명-test"
        log = types.SimpleNamespace(emit=lambda *a: None)
    port = free_port()
    w = Hello("127.0.0.1", port, "tok")
    assert w.address == f"http://127.0.0.1:{port}/#token=tok"
    await w.start(Ctx)
    await w.start(Ctx)  # starting twice opens one window
    async with httpx.AsyncClient() as hc:
        assert (await hc.get(f"http://127.0.0.1:{port}/")).text == "hi"
    await w.stop(Ctx)
    await w.stop(Ctx)
    with pytest.raises(NotImplementedError):
        LocalWebApp("127.0.0.1", 0, "t").web_app(Ctx)


def test_runners_assemble_their_peers(tmp_path, settings):
    from arena.peers import foundation, search
    base = lambda pre: {f"{pre}_brokers": ["public=http://127.0.0.1:1"], f"{pre}_area": str(tmp_path / pre), f"{pre}_key_file": str(tmp_path / f"{pre}.key")}
    f = foundation.build(dataclasses.replace(settings, **base("foundation_peer")))
    assert f.operator() == "service" and any(a.name == "platform.foundation" for a in f.apps)
    s = search.build(dataclasses.replace(settings, embed_url="http://127.0.0.1:1", **base("search_peer")))
    assert s.operator() == "service" and any(a.name == "search" or "search" in a.name for a in s.apps)
    from arena.config import ConfigError
    with pytest.raises(ConfigError):
        foundation.build(dataclasses.replace(settings, foundation_peer_brokers=[], foundation_peer_area=str(tmp_path / "x")))


def test_llm_builders_and_availability(settings):
    assert not llm_available(NoLLM()) and llm_available(object())
    assert isinstance(build_llm(dataclasses.replace(settings, llm_backend="none")), NoLLM)
    from arena.config import ConfigError
    with pytest.raises(ConfigError):
        build_llm(dataclasses.replace(settings, llm_backend="mystery"))


async def test_claude_adapter_with_a_stand_in_client(settings, monkeypatch):
    """the Claude adapter's own logic (JSON out, usage, refusals and API errors retried, then a clear error), on a fake SDK"""
    class APIError(Exception):
        pass
    replies = []

    class Messages:
        async def create(self, **kw):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

    class AsyncAnthropic:
        def __init__(self, **kw):
            self.messages = Messages()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=AsyncAnthropic, APIError=APIError))
    from arena.llm import ClaudeLLM
    s = dataclasses.replace(settings, llm_backend="claude", llm_claude_api_key="k", llm_model_agent="m", llm_retries=1)
    llm = build_llm(s)
    assert isinstance(llm, ClaudeLLM) and llm_available(llm)
    text = lambda t: types.SimpleNamespace(type="text", text=t)
    ok = types.SimpleNamespace(stop_reason="end_turn", content=[text('{"a": 1}')], usage=types.SimpleNamespace(input_tokens=3, output_tokens=4))
    seen = []
    replies[:] = [ok]
    assert await llm.ask_json(system="s", schema={}, user="u", on_usage=seen.append) == {"a": 1} and seen == [{"prompt_tokens": 3, "completion_tokens": 4}]
    replies[:] = [types.SimpleNamespace(stop_reason="refusal", content=[], usage=None), ok]
    assert await llm.ask_json(system="s", schema={}, user="u") == {"a": 1}  # a refusal is retried
    replies[:] = [APIError("busy"), APIError("busy")]
    with pytest.raises(LLMError, match="APIError"):
        await llm.ask_json(system="s", schema={}, user="u")
