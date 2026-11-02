"""P5-D: the app SDK, its adapters (adaptees made into apps) and the harness third-party developers test with."""
import json

import httpx
import pytest

from arena.a2a import build_a2a_app
from arena.sdk import (A2AAgentAdapter, BaseApp, Decision, HttpServiceAdapter, MessageHead, capabilities_of, discover_apps,
                       function_app)
from arena.sdk.testing import AppHarness
from arena.serve import serve_background
from tests.test_processes import free_port


async def test_function_app_has_exactly_the_given_capabilities(tmp_path):
    async def hi(ctx, msg, head):
        return {"ok": True, "to": msg.get("who"), "event": head.event_id}

    async def accept(ctx, role, request):
        return Decision(role == "helper", "ok")
    app = function_app("hello", app_id="0b1d3c3e-6f7a-4a43-9d1e-7a0c2f8e1b10", ops={"hi": hi}, offers=["helper"], accept_role=accept)
    assert capabilities_of(app) == ["OpProvider", "OfferProvider", "RoleAcceptor"]
    h = AppHarness(app, tmp_path)
    assert (await h.call("hi", {"who": "you"}, event="ev-1")) == {"ok": True, "to": "you", "event": "ev-1"}
    assert "helper" in h.peer.offers()


async def test_http_service_adapter_relays_a_core_system_endpoint(tmp_path):
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.content))
        if request.url.path == "/employees/42":
            return httpx.Response(200, json={"id": 42, "name": "홍길동", "dept": "HR"})
        return httpx.Response(404, json={"error": "nope"})
    app = HttpServiceAdapter("hr-system", "1.0", "http://hr.local", {"employee": ("GET", "/employees/{id}")}, app_id="0b1d3c3e-6f7a-4a43-9d1e-7a0c2f8e1b11",
                             allow_groups=["g-hr"], http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    h = AppHarness(app, tmp_path, group_id="g-hr")  # the service peer belongs to the HR group
    r = await h.call("employee", {"path": {"id": 42}}, group="g-hr")
    assert r["ok"] and r["result"]["name"] == "홍길동" and seen[0][:2] == ("GET", "http://hr.local/employees/42")
    assert (await h.call("employee", {"path": {"id": 42}}, group="g-other"))["error"].startswith("not a member")  # head check first
    assert (await app.ops()["employee"](h.ctx, {"path": {"id": 1}}, MessageHead("g-x")))["error"] == "group g-x may not use hr-system"
    assert (await app.ops()["employee"](h.ctx, {"path": {"id": 7}}, MessageHead("g-hr")))["status"] == 404
    assert app.profile_extra()["service"]["ops"] == ["employee"] and app.offers() == ["service:hr-system"]


async def test_a2a_agent_adapter_talks_to_any_a2a_agent(tmp_path, settings):
    async def agent(msg_or_text):  # an outside A2A agent that only knows text
        return {"ok": True, "echo": msg_or_text}
    port = free_port()
    url = f"http://127.0.0.1:{port}"

    async def text_agent(msg):
        return {"answer": "안녕하세요", "got": msg}
    srv = await serve_background(build_a2a_app("outside-agent", "not an arena peer", url, ["chat"], text_agent), "127.0.0.1", port)
    try:
        app = A2AAgentAdapter("helpdesk", "1.0", url, app_id="0b1d3c3e-6f7a-4a43-9d1e-7a0c2f8e1b12")
        h = AppHarness(app, tmp_path)
        r = await h.call("ask", {"text": json.dumps({"q": "근무 시간?"}, ensure_ascii=False)})
        assert r["ok"] and json.loads(r["reply"])["answer"] == "안녕하세요"
    finally:
        srv.should_exit = True


def test_sdk_version_mismatch_is_refused(tmp_path):
    class Future(BaseApp):
        name, version, sdk = "future", "1.0", "2"

        def ops(self):
            return {}
    with pytest.raises(ValueError, match="SDK 2"):
        AppHarness(Future(), tmp_path)


def test_discover_installed_apps_through_entry_points(settings):
    class EP:
        def __init__(self, name, target):
            self.name, self._t = name, target

        def load(self):
            return self._t
    from tests.plugin_samples.apps import make_greeter
    apps = discover_apps(settings, eps=[EP("greeter", make_greeter), EP("other", make_greeter)], names=["greeter"])
    assert [a.name for a in apps] == ["greeter"]
