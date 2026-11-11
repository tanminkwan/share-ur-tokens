"""Peer-to-peer transport. Every peer is an A2A 1.0 server (Agent Card + JSON-RPC); a message is one JSON object.
Transport is the interface peers depend on: A2ATransport over HTTP, LocalTransport inside one process (tests).
Slow answers (a person answers at a person's pace) become A2A tasks: arena/a2a_tasks.py (SlowAnswer on the answering
side, TaskFollower on the calling side). The caller sends with return_immediately."""
from __future__ import annotations

import inspect
import json
from typing import Awaitable, Callable, Protocol

import httpx
from a2a.client import ClientConfig, create_client
from a2a.client.errors import AgentCardResolutionError
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.types import (AgentCapabilities, AgentCard, AgentInterface, AgentSkill, GetTaskRequest, Role, SendMessageConfiguration,
                       SendMessageRequest, TaskPushNotificationConfig)
from starlette.applications import Starlette

from .egress import Egress, EgressTransport
from .a2a_push import push_url_ok
from .a2a_tasks import SlowAnswer, TaskFollower
from .config import Settings

Handler = Callable[..., Awaitable[dict]]  # handler(msg) or handler(msg, meta)
RPC_PATH = "/rpc"
H_GROUP, H_EVENT = "X-Arena-Group", "X-Arena-Event"


def never_delivered(e: BaseException) -> bool:
    """did this failure surely happen before the other peer got the message? Its agent card could not be fetched (that comes
    first), the connection was never made, or the server answered 503 (unavailable: nothing was processed). Only such a call
    may be sent again; a timeout or a bad answer may come after the peer acted on it (P10-C4)"""
    seen, x = set(), e
    while x is not None and id(x) not in seen:
        seen.add(id(x))
        if isinstance(x, (AgentCardResolutionError, httpx.ConnectError, httpx.ConnectTimeout)):
            return True
        status = getattr(x, "status_code", None) or getattr(getattr(x, "response", None), "status_code", None)
        if status == 503:
            return True
        x = x.__cause__  # only what it was explicitly raised from: not what happened to be handled at the time
    return False


class Transport(Protocol):
    async def call(self, url: str, msg: dict, timeout: float | None = None, meta: dict | None = None) -> dict: ...
    async def check_task(self, url: str, task_id: str, wait: float | None = None) -> dict: ...


def _wants_meta(handler) -> bool:
    return len(inspect.signature(handler).parameters) >= 2


async def _dispatch(handler, msg, meta):
    return await (handler(msg, meta) if _wants_meta(handler) else handler(msg))


class _JsonExecutor(AgentExecutor):
    """an async dict->dict handler as an A2A agent: one JSON message, or a task when the answer takes long"""

    def __init__(self, handler: Handler, answer_wait: float):
        self.handler, self.slow = handler, SlowAnswer(answer_wait)

    async def _run(self, context) -> dict:
        try:
            m = context.message
            md = dict(m.metadata) if m is not None and m.metadata else {}
            meta = {"group_id": md.get("group_id"), "event_id": md.get("event_id"), "context_id": (m.context_id if m is not None else None) or None}
            return await _dispatch(self.handler, json.loads(context.get_user_input()), meta)
        except Exception as e:  # surface errors to the caller instead of hanging
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def execute(self, context, event_queue) -> None:
        await self.slow.answer(lambda: self._run(context), context, event_queue)

    async def cancel(self, context, event_queue) -> None:
        pass


def build_a2a_app(name: str, description: str, url, skills: list[str], handler: Handler, version: str = "1.0",
                  answer_wait: float = 5.0, task_store=None, push: bool = True, streaming: bool = True, routes=(), egress=None) -> Starlette:
    """task_store: where slow answers' tasks are kept (a FileTaskStore in the peer's home survives a restart);
    push: notify a caller's webhook when a task changes (arena/a2a_push.py); streaming: accept SSE (message:stream);
    routes: more routes on the same server (the peer's own webhook); url: an address, or a function giving the address now
    (it can change while the server runs: the card is fitted to it on each request); egress: a function giving the Egress the
    webhook sender leaves by (arena/egress.py), None for httpx's usual way"""
    url_now = url if callable(url) else (lambda: url)
    url = url_now()
    card = AgentCard(
        name=name, description=description, version=version,
        supported_interfaces=[AgentInterface(url=url.rstrip("/") + RPC_PATH, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=streaming, push_notifications=push),
        default_input_modes=["application/json"], default_output_modes=["application/json"],
        skills=[AgentSkill(id=s, name=s, description=s, tags=[s]) for s in skills])
    pushes = {}
    if push:
        store = InMemoryPushNotificationConfigStore()
        pushes = {"push_config_store": store, "push_url_validator": push_url_ok,  # refused up front, and checked again on sending
                  "push_sender": BasePushNotificationSender(httpx.AsyncClient(timeout=10.0, **({"transport": EgressTransport(egress)} if egress else {})), store, push_url_validator=push_url_ok)}
    rh = DefaultRequestHandlerV2(agent_executor=_JsonExecutor(handler, answer_wait), task_store=task_store or InMemoryTaskStore(), agent_card=card,
                                 **pushes)
    async def fitted(c):
        want = url_now().rstrip("/") + RPC_PATH
        if c.supported_interfaces[0].url == want:
            return c
        out = AgentCard()
        out.CopyFrom(c)
        out.supported_interfaces[0].url = want
        return out
    return Starlette(routes=create_agent_card_routes(card, card_modifier=fitted) + create_jsonrpc_routes(rh, rpc_url=RPC_PATH) + list(routes))


class A2ATransport:
    def __init__(self, settings: Settings):
        self.timeout, self.wait = settings.a2a_timeout_sec, settings.a2a_task_wait_sec
        self.follower = TaskFollower(settings.a2a_task_poll_sec, fallback=settings.a2a_push_fallback_sec)
        self.egress = Egress()  # how my calls leave (arena/egress.py); a peer hands its own one in

    @property
    def via(self):
        return self.egress.via

    async def call(self, url, msg, timeout=None, meta=None):
        """discover the Agent Card at url, send one JSON message, parse the JSON reply.
        meta {"group_id", "event_id"} rides in the message head: context_id = event_id, metadata, and HTTP headers.
        meta "wait": how long to follow a task the peer answers with (seconds; default ARENA_A2A_TASK_WAIT_SEC);
        meta "notify" {url, token, wake}: my webhook for that task (arena/a2a_push.py), and the event it sets"""
        meta = meta or {}
        group, event = meta.get("group_id"), meta.get("event_id")
        headers = {k: v for k, v in ((H_GROUP, group), (H_EVENT, event)) if v}
        message = new_text_message(json.dumps(msg, ensure_ascii=False), role=Role.ROLE_USER, **({"context_id": event} if event else {}))
        if group or event:
            message.metadata.update({k: v for k, v in (("group_id", group), ("event_id", event)) if v})
        notify = meta.get("notify")
        config = SendMessageConfiguration(return_immediately=True)
        if notify:
            config.task_push_notification_config.CopyFrom(TaskPushNotificationConfig(url=notify["url"], token=notify["token"]))
        request = SendMessageRequest(message=message, configuration=config)
        async with self.egress.client(timeout=timeout or self.timeout, headers=headers) as hc:
            client = await create_client(url, ClientConfig(streaming=False, httpx_client=hc))
            last = None
            async for r in client.send_message(request):
                last = r
            if last is None:
                return {"ok": False, "error": "no response"}
            if last.HasField("message"):
                return json.loads(get_message_text(last.message))
            return _with_url(await self.follower.follow(client, last.task, meta.get("wait") or self.wait, (notify or {}).get("wake")), url)

    async def check_task(self, url, task_id, wait=None):
        """look again at a task a call gave back as pending (wait: how long to follow it now; 0 = just look)"""
        try:
            async with self.egress.client(timeout=self.timeout) as hc:
                client = await create_client(url, ClientConfig(streaming=False, httpx_client=hc))
                task = await client.get_task(GetTaskRequest(id=task_id))
                return _with_url(await self.follower.follow(client, task, wait or 0), url)
        except Exception as e:  # noqa: BLE001  (an unknown task, or the peer is gone)
            return {"ok": False, "error": f"cannot look at task {task_id}: {type(e).__name__}: {e}", "task_id": task_id}


def _with_url(r: dict, url: str) -> dict:
    """a pending answer names where to look again"""
    return dict(r, url=url) if r.get("pending") else r


class LocalTransport:
    """url -> handler in one process; messages are JSON round-tripped like on the wire"""

    def __init__(self):
        self.handlers: dict[str, Handler] = {}

    def register(self, url: str, handler: Handler) -> None:
        self.handlers[url] = handler

    async def call(self, url, msg, timeout=None, meta=None):
        if url not in self.handlers:
            raise ConnectionError(f"{url} unreachable")
        m = {"group_id": None, "event_id": None, **(meta or {})}
        return json.loads(json.dumps(await _dispatch(self.handlers[url], json.loads(json.dumps(msg)), m)))

    async def check_task(self, url, task_id, wait=None):
        return {"ok": False, "error": "no tasks here: this transport answers at once", "task_id": task_id}


async def ask_agent(url: str, text: str, timeout: float = 60.0, context_id: str | None = None) -> str:
    """talk to any A2A agent in plain text (not only arena peers): send one text message, return the reply text"""
    async with httpx.AsyncClient(timeout=timeout) as hc:
        client = await create_client(url, ClientConfig(streaming=False, httpx_client=hc))
        last = None
        msg = new_text_message(text, role=Role.ROLE_USER, **({"context_id": context_id} if context_id else {}))
        async for r in client.send_message(SendMessageRequest(message=msg)):
            last = r
    if last is not None and last.HasField("message"):
        return get_message_text(last.message)
    if last is not None and last.HasField("task"):
        t = last.task
        if t.status.HasField("message"):
            return get_message_text(t.status.message)
        for a in t.artifacts:
            for part in a.parts:
                if part.HasField("text"):
                    return part.text
    return ""
