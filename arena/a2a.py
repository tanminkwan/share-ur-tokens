"""Peer-to-peer transport. Every peer is an A2A 1.0 server (Agent Card + JSON-RPC); a message is one JSON object.
Transport is the interface peers depend on: A2ATransport over HTTP, LocalTransport inside one process (tests)."""
from __future__ import annotations

import inspect
import json
from typing import Awaitable, Callable, Protocol

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Role, SendMessageRequest
from starlette.applications import Starlette

from .config import Settings

Handler = Callable[..., Awaitable[dict]]  # handler(msg) or handler(msg, meta)
RPC_PATH = "/rpc"
H_GROUP, H_EVENT = "X-Arena-Group", "X-Arena-Event"


class Transport(Protocol):
    async def call(self, url: str, msg: dict, timeout: float | None = None, meta: dict | None = None) -> dict: ...


def _wants_meta(handler) -> bool:
    return len(inspect.signature(handler).parameters) >= 2


async def _dispatch(handler, msg, meta):
    return await (handler(msg, meta) if _wants_meta(handler) else handler(msg))


class _JsonExecutor(AgentExecutor):
    """an async dict->dict handler as an A2A agent answering with one JSON message"""

    def __init__(self, handler: Handler):
        self.handler = handler

    async def execute(self, context, event_queue) -> None:
        try:
            m = context.message
            md = dict(m.metadata) if m is not None and m.metadata else {}
            meta = {"group_id": md.get("group_id"), "event_id": md.get("event_id"), "context_id": (m.context_id if m is not None else None) or None}
            res = await _dispatch(self.handler, json.loads(context.get_user_input()), meta)
        except Exception as e:  # surface errors to the caller instead of hanging
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        await event_queue.enqueue_event(new_text_message(json.dumps(res, ensure_ascii=False), context_id=context.context_id))

    async def cancel(self, context, event_queue) -> None:
        pass


def build_a2a_app(name: str, description: str, url: str, skills: list[str], handler: Handler, version: str = "1.0") -> Starlette:
    card = AgentCard(
        name=name, description=description, version=version,
        supported_interfaces=[AgentInterface(url=url.rstrip("/") + RPC_PATH, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"], default_output_modes=["application/json"],
        skills=[AgentSkill(id=s, name=s, description=s, tags=[s]) for s in skills])
    rh = DefaultRequestHandlerV2(agent_executor=_JsonExecutor(handler), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(rh, rpc_url=RPC_PATH))


class A2ATransport:
    def __init__(self, settings: Settings):
        self.timeout = settings.a2a_timeout_sec

    async def call(self, url, msg, timeout=None, meta=None):
        """discover the Agent Card at url, send one JSON message, parse the JSON reply.
        meta {"group_id", "event_id"} rides in the message head: context_id = event_id, metadata, and HTTP headers"""
        meta = meta or {}
        group, event = meta.get("group_id"), meta.get("event_id")
        headers = {k: v for k, v in ((H_GROUP, group), (H_EVENT, event)) if v}
        message = new_text_message(json.dumps(msg, ensure_ascii=False), role=Role.ROLE_USER, **({"context_id": event} if event else {}))
        if group or event:
            message.metadata.update({k: v for k, v in (("group_id", group), ("event_id", event)) if v})
        async with httpx.AsyncClient(timeout=timeout or self.timeout, headers=headers) as hc:
            client = await create_client(url, ClientConfig(streaming=False, httpx_client=hc))
            last = None
            async for r in client.send_message(SendMessageRequest(message=message)):
                last = r
        if last is None:
            return {"ok": False, "error": "no response"}
        if last.HasField("message"):
            return json.loads(get_message_text(last.message))
        return {"ok": False, "error": "unexpected task response"}


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
