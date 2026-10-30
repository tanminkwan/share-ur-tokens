"""Peer-to-peer transport. Every peer is an A2A 1.0 server (Agent Card + JSON-RPC); a message is one JSON object.
Transport is the interface peers depend on: A2ATransport over HTTP, LocalTransport inside one process (tests)."""
from __future__ import annotations

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

Handler = Callable[[dict], Awaitable[dict]]
RPC_PATH = "/rpc"


class Transport(Protocol):
    async def call(self, url: str, msg: dict, timeout: float | None = None) -> dict: ...


class _JsonExecutor(AgentExecutor):
    """an async dict->dict handler as an A2A agent answering with one JSON message"""

    def __init__(self, handler: Handler):
        self.handler = handler

    async def execute(self, context, event_queue) -> None:
        try:
            res = await self.handler(json.loads(context.get_user_input()))
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

    async def call(self, url, msg, timeout=None):
        """discover the Agent Card at url, send one JSON message, parse the JSON reply"""
        async with httpx.AsyncClient(timeout=timeout or self.timeout) as hc:
            client = await create_client(url, ClientConfig(streaming=False, httpx_client=hc))
            last = None
            async for r in client.send_message(SendMessageRequest(message=new_text_message(json.dumps(msg, ensure_ascii=False), role=Role.ROLE_USER))):
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

    async def call(self, url, msg, timeout=None):
        if url not in self.handlers:
            raise ConnectionError(f"{url} unreachable")
        return json.loads(json.dumps(await self.handlers[url](json.loads(json.dumps(msg)))))
