"""Slow answers over A2A (user 2026-11-03: a person answers at a person's pace; dev/peer-spec.md 1.1). The receiving peer
answers with one message when the op finishes in time, otherwise it reports an A2A task in state `working` (with a
note of what it waits for) and finishes it in the background; the caller follows the task until it completes or its
wait runs out (pending + task id). Real sockets, no LLM."""
import asyncio
import dataclasses
import json

from a2a.helpers.proto_helpers import new_task, new_text_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, TaskState
from starlette.applications import Starlette

from arena.a2a import RPC_PATH, A2ATransport, ask_agent, build_a2a_app
from arena.waiting import waiting_for
from arena.serve import serve_background
from tests.test_processes import free_port


async def serve(make_app):
    """make_app(url) -> the app; the agent card names the real address (clients go where the card says)"""
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    srv = await serve_background(make_app(url), "127.0.0.1", port)
    return srv, url


def fast(settings, **over):
    return dataclasses.replace(settings, a2a_task_poll_sec=0.05, **over)


async def test_a_quick_answer_is_one_message_and_a_slow_one_a_task_the_caller_follows(settings):
    calls = []

    async def handler(msg):
        calls.append(msg["op"])
        if msg["op"] == "slow":
            await asyncio.sleep(0.5)
        if msg["op"] == "boom":
            await asyncio.sleep(0.3)
            raise RuntimeError("broken in the background")
        return {"ok": True, "op": msg["op"]}
    srv, url = await serve(lambda u: build_a2a_app("t", "t", u, ["x"], handler, answer_wait=0.1))
    try:
        t = A2ATransport(fast(settings))
        assert await t.call(url, {"op": "quick"}) == {"ok": True, "op": "quick"}
        assert await t.call(url, {"op": "slow"}) == {"ok": True, "op": "slow"}  # answered as a task, followed to the end
        bad = await t.call(url, {"op": "boom"})
        assert not bad["ok"] and "broken in the background" in bad["error"]
        # a plain A2A client that does not ask to return immediately still gets the answer (it just waits)
        assert json.loads(await ask_agent(url, json.dumps({"op": "slow"}), timeout=10)) == {"ok": True, "op": "slow"}
    finally:
        srv.should_exit = True


async def test_the_caller_gives_back_pending_with_the_task_and_what_it_waits_for(settings):
    release = asyncio.Event()

    async def handler(msg):
        waiting_for("waiting for the owner (a person) to answer")
        await release.wait()
        return {"ok": True, "answered": True}
    srv, url = await serve(lambda u: build_a2a_app("t", "t", u, ["x"], handler, answer_wait=0.05))
    try:
        r = await A2ATransport(fast(settings)).call(url, {"op": "ask"}, meta={"wait": 0.3})
        assert r["ok"] is False and r["pending"] and r["task_id"] and "waiting for the owner" in r["error"]
        release.set()
    finally:
        await asyncio.sleep(0.1)
        srv.should_exit = True


class _Stubborn(AgentExecutor):
    """another A2A agent (not an arena peer) that fails or asks the caller for input"""

    def __init__(self, how):
        self.how = how

    async def execute(self, context, event_queue):
        await event_queue.enqueue_event(new_task(context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED))
        u = TaskUpdater(event_queue, context.task_id, context.context_id)
        m = new_text_message("which one do you mean?" if self.how == "input" else "out of paper", context_id=context.context_id)
        m.task_id = context.task_id
        await (u.requires_input(m) if self.how == "input" else u.failed(m))

    async def cancel(self, context, event_queue):
        pass


def stubborn_app(how, url):
    card = AgentCard(name="s", description="s", version="1", default_input_modes=["text/plain"], default_output_modes=["text/plain"],
                     supported_interfaces=[AgentInterface(url=url + RPC_PATH, protocol_binding="JSONRPC", protocol_version="1.0")],
                     capabilities=AgentCapabilities(streaming=False))
    rh = DefaultRequestHandlerV2(agent_executor=_Stubborn(how), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(rh, rpc_url=RPC_PATH))


async def test_a_task_that_fails_or_needs_the_callers_input_is_said_so(settings):
    for how, words in (("fail", "failed: out of paper"), ("input", "needs input: which one")):
        srv, url = await serve(lambda u: stubborn_app(how, u))
        try:
            r = await A2ATransport(fast(settings)).call(url, {"op": "x"})
            assert r["ok"] is False and words in r["error"] and r["task_id"], r
        finally:
            srv.should_exit = True


async def test_a_human_peer_is_followed_at_a_persons_pace(settings):
    """PeerReach gives a human peer the longer wait (ARENA_A2A_HUMAN_WAIT_SEC); other peers the default"""
    from arena.peer.reach import PeerReach
    seen = []

    async def a2a_call(url, msg, timeout, group=None, event=None, wait=None):
        seen.append(wait)
        return {"ok": True}

    class Broker:
        def __init__(self, op):
            self.op = op

        async def list_profiles(self, identity=None):
            return {"profiles": [{"pub": "p", "operator": self.op, "connections": [{"kind": "a2a", "url": "http://x"}]}]}
    for op in ("human", "agent"):
        reach = PeerReach(None, {"g": Broker(op)}, a2a_call, lambda: None, lambda: 3600.0)
        assert (await reach.call("p", {"op": "engage"}))["ok"]
    assert seen == [3600.0, None]


async def test_a_human_peer_asked_to_engage_answers_through_a_task(tmp_path, settings):
    """the person's answer comes minutes later on the desk; the caller follows the A2A task meanwhile, then gets the signature"""
    from arena.a2a import A2ATransport as T
    from arena.events import EventLog
    from arena.llm import NoLLM
    from arena.peer.area import LocalFolderArea
    from arena.peer.desk import DeskOwner, OwnerDesk
    from arena.peer.node import Peer, PeerConfig
    from arena.peer.plugin import BaseApp, Decision
    from arena.crypto import Identity

    class AskOwner(BaseApp):
        name, version, app_id = "ask-owner", "1.0", "0b6a4c2e-8d1f-4e3a-9c5b-7a2d6e8f1b34"

        def offers(self):
            return ["member"]

        async def accept_role(self, ctx, role, request):
            a = await ctx.owner.ask(f"'{role}' 역할을 맡을까요?")
            return Decision(a.yes, a.why)
    s = fast(settings, a2a_answer_wait_sec=0.1)
    desk = OwnerDesk(lambda: 0.0, keep=50)
    port = free_port()
    (tmp_path / "area").mkdir()
    me = Identity.generate()
    peer = Peer(me, s, PeerConfig(url=f"http://127.0.0.1:{port}"), LocalFolderArea(str(tmp_path / "area"), s), DeskOwner(desk, s), NoLLM(),
                T(s), EventLog(keep=10), brokers={}, apps=[AskOwner()])
    srv = await serve_background(peer.a2a_app(), "127.0.0.1", port)
    try:
        contract = {"role": "member", "contractor": me.pub, "issuer": "i" * 64, "event_id": "e1", "nonce": "n"}

        async def person_answers_later():
            while not desk.items:
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.4)  # longer than the answer window: the caller is following a task by now
            desk.answer(next(iter(desk.items)), {"yes": True, "why": "좋아요"})
        later = asyncio.create_task(person_answers_later())
        r = await T(s).call(f"http://127.0.0.1:{port}", {"op": "engage", "role": "member", "contract": contract})
        await later
        assert r["ok"] and r["reason"] == "좋아요" and r["sig"]
    finally:
        srv.should_exit = True


# ---------------- looking again, and the answering peer restarting ----------------
async def test_a_pending_call_is_looked_at_again_and_a_restart_closes_it_with_a_reason(tmp_path, settings):
    from arena.a2a_tasks import FileTaskStore
    release = asyncio.Event()

    async def handler(msg):
        waiting_for("waiting for the owner (a person) to answer")
        await release.wait()
        return {"ok": True, "op": msg["op"]}
    path = str(tmp_path / "home" / "a2a-tasks.json")
    srv, url = await serve(lambda u: build_a2a_app("t", "t", u, ["x"], handler, answer_wait=0.05, task_store=FileTaskStore(path, keep=50)))
    t = A2ATransport(fast(settings))
    try:
        first = await t.call(url, {"op": "engage"}, meta={"wait": 0.2})
        assert first["pending"] and first["url"] == url  # where to look again
        again = await t.check_task(url, first["task_id"])
        assert again["pending"] and "waiting for the owner" in again["error"]
        release.set()
        done = await t.check_task(url, first["task_id"], wait=2)
        assert done == {"ok": True, "op": "engage"}
        release.clear()
        second = await t.call(url, {"op": "engage"}, meta={"wait": 0.2})
        assert second["pending"]
    finally:
        srv.should_exit = True
        await asyncio.sleep(0.2)
    # the answering peer restarts: the task that was still working is closed with a reason, the finished one kept
    srv, url2 = await serve(lambda u: build_a2a_app("t", "t", u, ["x"], handler, answer_wait=0.05, task_store=FileTaskStore(path, keep=50)))
    try:
        gone = await t.check_task(url2, second["task_id"])
        assert gone["ok"] is False and "restarted" in gone["error"]
        assert (await t.check_task(url2, first["task_id"])) == {"ok": True, "op": "engage"}
        assert "cannot look at task" in (await t.check_task(url2, "no-such-task"))["error"]
    finally:
        release.set()
        srv.should_exit = True


async def test_the_task_store_keeps_the_newest_and_lists_by_context(tmp_path):
    from a2a.types import ListTasksRequest, Task, TaskStatus
    from arena.a2a_tasks import FileTaskStore
    store = FileTaskStore(str(tmp_path / "t.json"), keep=2)
    for i in range(3):
        await store.save(Task(id=f"t{i}", context_id="c" if i else "d", status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED)))
    assert set(store.tasks) == {"t1", "t2"} and (await store.get("t0")) is None
    listed = await store.list(ListTasksRequest(context_id="c"))
    assert [x.id for x in listed.tasks] == ["t2", "t1"]
    await store.delete("t1")
    assert set(FileTaskStore(str(tmp_path / "t.json"), keep=2).tasks) == {"t2"}  # kept on disk


async def test_a_transport_without_tasks_says_so(settings, tmp_path):
    from arena.a2a import LocalTransport
    assert "no tasks here" in (await LocalTransport().check_task("mem://x", "t"))["error"]
