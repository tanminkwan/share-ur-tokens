"""SDK adapters (function apps, HTTP relay, A2A agents) and the chat agent's tools, branch by branch. No real LLM."""
import httpx

from arena.peer.plugin import Decision, MessageHead
from arena.sdk import A2AAgentAdapter, HttpServiceAdapter, function_app
from arena.signing import sign_message
from tests.test_assistant import asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

APP_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


async def test_function_app_has_only_the_capabilities_given(eco):
    calls = []

    async def accept(ctx, role, request):
        calls.append(("accept", role))
        return Decision(True, "좋다")

    async def approve(ctx, event, request):
        calls.append(("approve", event))
        return Decision(False, "아니다")

    async def on_request(ctx, request, sender):
        calls.append(("request", sender))

    async def start(ctx):
        calls.append(("start",))
    app = function_app("fx", "1.0", app_id=APP_ID, ops={"hi": lambda ctx, msg, head: None}, offers=["x"], accept_role=accept,
                       approve_event=approve, on_request=on_request, profile_extra={"k": 1}, start=start)
    assert app.offers() == ["x"] and "hi" in app.ops() and app.profile_extra() == {"k": 1}
    assert (await app.accept_role(None, "r", {})).accept and not (await app.approve_event(None, {"e": 1}, {})).accept
    await app.on_request(None, {}, "s")
    await app.start(None)
    assert [c[0] for c in calls] == ["accept", "approve", "request", "start"]
    bare = function_app("bare", "1.0", app_id=APP_ID)
    assert not hasattr(bare, "ops") and not hasattr(bare, "start")


async def test_http_relay_checks_groups_and_signatures_and_survives_a_down_service(eco):
    p = eco.a
    seen = {}

    def backend(request: httpx.Request):
        seen["url"] = str(request.url)
        if request.url.path == "/text":
            return httpx.Response(200, text="plain")
        return httpx.Response(201, json={"id": 7})
    hc = httpx.AsyncClient(transport=httpx.MockTransport(backend))
    relay = HttpServiceAdapter("hr", "1.0", "http://hr", {"emp": ("GET", "/emp/{id}"), "text": ("GET", "/text")}, app_id=APP_ID,
                               allow_groups=["public"], require_signed=True, http=hc)
    assert relay.offers() == ["service:hr"] and relay.profile_extra()["service"]["ops"] == ["emp", "text"]
    ctx_ = p.ctx(asst(p))
    ops = relay.ops()
    assert "may not use" in (await ops["emp"](ctx_, {}, MessageHead(group_id="other")))["error"]
    assert "signed message required" in (await ops["emp"](ctx_, {"path": {"id": 7}}, MessageHead(group_id="public")))["error"]
    signed = dict({"op": "emp", "path": {"id": 7}}, **sign_message(p.identity, "emp"))
    r = await ops["emp"](ctx_, signed, MessageHead(group_id="public"))
    assert r["ok"] and r["status"] == 201 and r["result"] == {"id": 7} and seen["url"].endswith("/emp/7")
    assert (await ops["text"](ctx_, dict({"op": "text"}, **sign_message(p.identity, "text")), MessageHead(group_id="public")))["result"] == "plain"
    down = HttpServiceAdapter("down", "1.0", "http://127.0.0.1:1", {"x": ("GET", "/")}, app_id=APP_ID, timeout=1)
    assert "unreachable" in (await down.ops()["x"](ctx_, {}, MessageHead()))["error"]


async def test_a2a_agent_adapter_relays_text_and_reports_an_unreachable_agent():
    async def ask(url, text, timeout, context_id):
        if text == "fail":
            raise ConnectionError("no")
        return f"답: {text}"
    ad = A2AAgentAdapter("helper", "1.0", "http://agent", app_id=APP_ID, ask=ask)
    assert ad.offers() == ["agent:helper"]
    h = ad.ops()["ask"]
    assert (await h(None, {"text": "안녕"}, MessageHead(event_id="e")))["reply"] == "답: 안녕"
    assert "agent unreachable" in (await h(None, {"text": "fail"}, MessageHead()))["error"]


async def test_chat_tools_branch_by_branch(eco):
    from arena.bundled.chat import concierge as C
    from tests.test_chat import chat_peer
    from tests.test_desk import hosted
    p, desk, chat = await chat_peer(eco)
    svc = chat.service
    assert "모르는 이벤트" in (await C._event_status(svc, "nope"))["error"]
    assert "모르는 이벤트" in (await C._tell_event(svc, "nope", "x"))["error"]
    assert "모르는 이벤트" in (await C._set_drive(svc, "nope", "auto"))["error"]
    assert "열린 알림이 아니다" in (await C._answer_item(svc, "nope", True, "예"))["error"]
    ev = await hosted(eco, title="점심")
    p.llm.push("wait")
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    status = await C._event_status(svc, "점심")  # an event named by its title
    assert status["event_id"] == ev and "state_line" in status
    assert (await C._set_drive(svc, ev, "manual"))["ok"]
    suggestion = desk.add("suggestion", "비서가 하려 합니다", fields={"tool": "join_event", "args": {}})
    assert (await C._answer_item(svc, suggestion.id, True, "좋다"))["ok"] and desk.items[suggestion.id].answer == {"approve": True}
    hosted_r = await C._host_event(svc, "새 대회", "놀이", "규칙", "member, judge")
    assert hosted_r["ok"] and svc.find_event("새 대회") == hosted_r["event_id"]
    p.llm.push("events", wrong="x")  # arguments the tool does not take are dropped; a tool that errors is reported
    p.llm.push("event_status")  # missing the required argument
    p.llm.push("reply", text="끝")
    out = await chat.say("확인해")
    assert out[-1]["text"] == "끝"
    assert await chat.say("   ") == []  # nothing said, nothing answered
