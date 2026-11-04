"""A2A as a walkie-talkie (user 2026-11-04: "a2a 방식은 sse, http, web hook으로 워키토키 방식으로 소통하는 것이 맞다", "사람이
agent 흉내를 내는 것이 맞아"). No session between peers: one message per turn; a slow answer is a task; the answering peer
notifies the caller's webhook when it changes; the caller then looks again itself (the notification is only a signal);
SSE is there for clients that want to stay on the line. Real sockets, two real peers, no LLM."""
import asyncio
import dataclasses
import json
import time

import httpx

from arena.a2a import A2ATransport, build_a2a_app
from arena.a2a_push import NOTIFY_PATH, TOKEN_HEADER, TaskWatch, push_url_ok, task_id_of
from arena.crypto import Identity
from arena.events import EventLog
from arena.llm import NoLLM
from arena.peer.area import LocalFolderArea
from arena.peer.desk import DeskOwner, OwnerDesk
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.peer.plugin import BaseApp, Decision
from arena.serve import serve_background
from tests.test_processes import free_port


class AskOwner(BaseApp):
    name, version, app_id = "ask-owner", "1.0", "0b6a4c2e-8d1f-4e3a-9c5b-7a2d6e8f1b34"

    def offers(self):
        return ["member"]

    async def accept_role(self, ctx, role, request):
        a = await ctx.owner.ask(f"'{role}' 역할을 맡을까요?")
        return Decision(a.yes, a.why)


async def peer(tmp_path, s, name, owner=None, apps=()):
    port = free_port()
    (tmp_path / name).mkdir()
    me = Identity.generate()
    p = Peer(me, s, PeerConfig(url=f"http://127.0.0.1:{port}"), LocalFolderArea(str(tmp_path / name), s), owner or NoOwner(), NoLLM(),
             A2ATransport(s), EventLog(keep=50, echo=False), brokers={}, apps=list(apps))
    srv = await serve_background(p.a2a_app(), "127.0.0.1", port)
    await p.scheduler.start(p.ctx(p.scheduler))
    return p, srv


def engage(contractor):
    return {"op": "engage", "role": "member", "contract": {"role": "member", "contractor": contractor, "issuer": "i" * 64, "event_id": "e1", "nonce": "n"}}


async def test_a_persons_slow_answer_arrives_by_webhook_not_by_polling(tmp_path, settings):
    s = dataclasses.replace(settings, a2a_answer_wait_sec=0.1, a2a_push_fallback_sec=30.0)  # polling alone would take 30 s
    desk = OwnerDesk(lambda: 0.0, keep=50)
    callee, srv1 = await peer(tmp_path, s, "person", DeskOwner(desk, s), [AskOwner()])
    caller, srv2 = await peer(tmp_path, s, "caller")
    try:
        async def person_answers():
            while not desk.items:
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.5)
            desk.answer(next(iter(desk.items)), {"yes": True, "why": "좋아요"})
        later = asyncio.create_task(person_answers())
        t0 = time.monotonic()
        r = await caller.call(callee.config.url, engage(callee.identity.pub), wait=20)
        await later
        assert r["ok"] and r["sig"] and time.monotonic() - t0 < 5  # woken by the webhook, then looked again itself
        assert not caller.watch.calls  # the call is done: its token is forgotten
    finally:
        srv1.should_exit = srv2.should_exit = True


async def test_a_pending_call_is_woken_by_the_webhook(tmp_path, settings):
    s = dataclasses.replace(settings, a2a_answer_wait_sec=0.05, a2a_push_fallback_sec=30.0)
    desk = OwnerDesk(lambda: 0.0, keep=50)
    callee, srv1 = await peer(tmp_path, s, "person", DeskOwner(desk, s), [AskOwner()])
    caller, srv2 = await peer(tmp_path, s, "caller")
    try:
        sch = caller.scheduler
        sch.add(caller.ctx(sch), "some-app", caller.clock() + 3600, "pending_check", event_id="e1")
        r = await caller.call(callee.config.url, engage(callee.identity.pub), event="e1", wait=0.3)
        assert r["pending"] and any(c["held"] for c in caller.watch.calls.values())
        desk.answer(next(iter(desk.items)), {"yes": True, "why": "나중에 좋아요"})
        end = time.monotonic() + 5
        while time.monotonic() < end and sch.timers and sch.timers[0]["at"] > caller.clock():
            await asyncio.sleep(0.05)
        assert sch.timers == [] or sch.timers[0]["at"] <= caller.clock()  # the look-again timer was brought forward (or already fired)
        assert (await caller.check_task(r["url"], r["task_id"]))["ok"]
    finally:
        srv1.should_exit = srv2.should_exit = True


async def test_forged_or_misdirected_notifications_change_nothing(tmp_path, settings):
    caller, srv = await peer(tmp_path, settings, "caller")
    try:
        hook = caller.config.url + NOTIFY_PATH
        token, wake = caller.watch.issue("e1")
        caller.watch.hold(token, "task-1")
        async with httpx.AsyncClient(trust_env=False) as hc:
            assert (await hc.post(hook, json={"task": {"id": "task-1"}}, headers={TOKEN_HEADER: "wrong"})).status_code == 401
            assert (await hc.post(hook, json={"task": {"id": "other"}}, headers={TOKEN_HEADER: token})).status_code == 401
            assert (await hc.post(hook, content=b"not json", headers={TOKEN_HEADER: token})).status_code == 401
            assert not wake.is_set()
            forged = {"task": {"id": "task-1", "status": {"state": "TASK_STATE_COMPLETED", "message": {"parts": [{"text": json.dumps({"ok": True, "sig": "fake"})}]}}}}
            assert (await hc.post(hook, json=forged, headers={TOKEN_HEADER: token})).status_code == 200
        assert wake.is_set()  # only a signal: the caller looks again at the answering peer; the body above is never read as the answer
    finally:
        srv.should_exit = True
    assert task_id_of({"statusUpdate": {"taskId": "t"}}) == "t" and task_id_of({"x": 1}) is None and task_id_of("x") is None
    w = TaskWatch(keep=2)
    for _ in range(3):
        w.issue()
    assert len(w.calls) == 2  # the oldest calls are forgotten
    w.done("nothing")


async def test_the_answering_peer_notifies_only_webhook_addresses(settings):
    assert await push_url_ok("http://127.0.0.1:9000" + NOTIFY_PATH) and await push_url_ok("https://peer.example" + NOTIFY_PATH)
    assert not await push_url_ok("http://169.254.169.254/latest/meta-data") and not await push_url_ok("file:///etc/passwd" + NOTIFY_PATH)
    port = free_port()

    async def slow(msg):
        await asyncio.sleep(0.3)
        return {"ok": True}
    srv = await serve_background(build_a2a_app("t", "t", f"http://127.0.0.1:{port}", ["x"], slow, answer_wait=0.05), "127.0.0.1", port)
    try:
        bad = {"url": "http://127.0.0.1:1/evil", "token": "t", "wake": asyncio.Event()}
        refused = None
        try:
            await A2ATransport(settings).call(f"http://127.0.0.1:{port}", {"op": "x"}, meta={"notify": bad})
        except Exception as e:  # the answering peer refuses the request up front: not a webhook address
            refused = str(e)
        assert refused and "push notification URL" in refused
    finally:
        srv.should_exit = True


async def test_an_outside_client_can_stay_on_the_line_with_sse(settings):
    from a2a.client import ClientConfig, create_client
    from a2a.helpers.proto_helpers import get_message_text, new_text_message
    from a2a.types import Role, SendMessageRequest
    port = free_port()

    async def handler(msg):
        if msg["op"] == "slow":
            await asyncio.sleep(0.3)
        return {"ok": True, "op": msg["op"]}
    srv = await serve_background(build_a2a_app("t", "t", f"http://127.0.0.1:{port}", ["x"], handler, answer_wait=0.05), "127.0.0.1", port)
    try:
        for op in ("quick", "slow"):
            events = []
            async with httpx.AsyncClient(timeout=10, trust_env=False) as hc:
                client = await create_client(f"http://127.0.0.1:{port}", ClientConfig(streaming=True, httpx_client=hc))
                async for ev in client.send_message(SendMessageRequest(message=new_text_message(json.dumps({"op": op}), role=Role.ROLE_USER))):
                    events.append(ev)
            last = events[-1]
            text = get_message_text(last.message) if last.HasField("message") else \
                get_message_text(last.task.status.message if last.HasField("task") else last.status_update.status.message)
            assert json.loads(text) == {"ok": True, "op": op}, op
            assert op == "quick" or len(events) > 1  # the slow one streamed its progress (working, then the answer)
    finally:
        srv.should_exit = True


async def test_the_scheduler_brings_timers_forward(tmp_path, settings):
    p, srv = await peer(tmp_path, settings, "p")
    try:
        sch, ctx = p.scheduler, p.ctx(p.scheduler)
        sch.add(ctx, "a", p.clock() + 999, "pending_check", event_id="e1")
        sch.add(ctx, "a", p.clock() + 999, "remind", event_id="e1")
        assert sch.bring_forward(ctx, "e1", "pending_check") == 1 and sch.bring_forward(ctx, "e2", "pending_check") == 0
        assert sorted(t["kind"] for t in sch.timers if t["at"] <= p.clock()) in (["pending_check"], [])
    finally:
        srv.should_exit = True
