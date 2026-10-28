"""Shared plumbing: crypto identities, event log, A2A server/client helpers."""
import asyncio
import hashlib
import json
import time

import httpx
import uvicorn
from starlette.applications import Starlette

from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Role, SendMessageRequest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def alias(pub: str) -> str:
    return "가명-" + pub[:6]


class Identity:
    """A pseudonym is just an ed25519 public key."""

    def __init__(self):
        self._k = Ed25519PrivateKey.generate()
        self.pub = self._k.public_key().public_bytes_raw().hex()

    def sign(self, payload) -> str:
        return self._k.sign(canon(payload)).hex()


def verify(pub_hex: str, payload, sig_hex: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(bytes.fromhex(sig_hex), canon(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


# ---- in-process observability (the demo dashboard reads these) ----
EVENTS: list[dict] = []
STORE: dict[str, dict] = {}  # 지식 저장소: content_hash -> content (MVP: in-process dict, deletable)


def emit(kind: str, actor: str, text: str):
    EVENTS.append({"ts": time.time(), "kind": kind, "actor": actor, "text": text})
    print(f"[{kind:8}] {actor}: {text}", flush=True)


# ---- A2A helpers ----
class JsonExecutor(AgentExecutor):
    """Turns an async dict->dict handler into an A2A agent that answers with one JSON Message."""

    def __init__(self, handler):
        self.handler = handler

    async def execute(self, context, event_queue) -> None:
        try:
            res = await self.handler(json.loads(context.get_user_input()))
        except Exception as e:  # surface errors to the caller instead of hanging
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        await event_queue.enqueue_event(new_text_message(json.dumps(res, ensure_ascii=False), context_id=context.context_id))

    async def cancel(self, context, event_queue) -> None:
        pass


def make_agent_app(name: str, description: str, port: int, skill_ids: list[str], handler) -> Starlette:
    url = f"http://127.0.0.1:{port}"
    card = AgentCard(
        name=name, description=description, version="0.1",
        supported_interfaces=[AgentInterface(url=url + "/rpc", protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"], default_output_modes=["application/json"],
        skills=[AgentSkill(id=s, name=s, description=s, tags=[s]) for s in skill_ids],
    )
    rh = DefaultRequestHandlerV2(agent_executor=JsonExecutor(handler), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(rh, rpc_url="/rpc"))


async def serve(app, port: int):
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    return srv


async def rpc(url: str, obj: dict, timeout: float = 60) -> dict:
    """Direct A2A call: discover the Agent Card at `url`, send one JSON message, parse the JSON reply."""
    async with httpx.AsyncClient(timeout=timeout) as hc:
        client = await create_client(url, ClientConfig(streaming=False, httpx_client=hc))
        msg = new_text_message(json.dumps(obj, ensure_ascii=False), role=Role.ROLE_USER)
        last = None
        async for r in client.send_message(SendMessageRequest(message=msg)):
            last = r
    if last is None:
        return {"ok": False, "error": "no response"}
    if last.HasField("message"):
        return json.loads(get_message_text(last.message))
    return {"ok": False, "error": "unexpected task response"}
