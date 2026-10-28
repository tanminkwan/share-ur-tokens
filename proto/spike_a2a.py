"""Feasibility spike: two real A2A agents on localhost negotiate over JSON-RPC.

Provider (총무) holds a projector. Consumer asks for Fri 14:00 -> taken ->
provider answers INPUT_REQUIRED with a counter-offer -> consumer accepts in the
same task -> COMPLETED with an artifact. No LLM involved; this only proves the
protocol layer (Agent Card discovery, multi-turn task, direct p2p call).
"""
import asyncio
import threading
import time

import httpx
import uvicorn
from starlette.applications import Starlette

from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import get_message_text, new_task_from_user_message, new_text_artifact, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Role, SendMessageRequest, TaskState)

PORT = 9101
URL = f"http://127.0.0.1:{PORT}"


class ProjectorProvider(AgentExecutor):
    TAKEN = "fri 14:00"
    COUNTER = "fri 15:00"

    async def execute(self, context: RequestContext, event_queue) -> None:
        text = context.get_user_input().lower()
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        up = TaskUpdater(event_queue, task.id, task.context_id)
        if self.TAKEN in text:
            await up.requires_input(up.new_agent_message([_text(f"{self.TAKEN} is taken. counter: {self.COUNTER}?")]))
        elif "accept" in text or self.COUNTER in text:
            await up.add_artifact([_text(f"CONFIRMED projector {self.COUNTER}")], name="reservation")
            await up.complete()
        else:
            await up.reject(up.new_agent_message([_text("unsupported request")]))

    async def cancel(self, context, event_queue) -> None:
        pass


def _text(s):
    from a2a.helpers.proto_helpers import new_text_part
    return new_text_part(s)


def build_app() -> Starlette:
    card = AgentCard(
        name="facilities-agent", description="총무: 빔프로젝터 대여", version="0.1",
        supported_interfaces=[AgentInterface(url=URL + "/rpc", protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        skills=[AgentSkill(id="lend-projector", name="projector lending", description="lend a projector", tags=["equipment"])],
    )
    handler = DefaultRequestHandlerV2(agent_executor=ProjectorProvider(), task_store=InMemoryTaskStore(), agent_card=card)
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/rpc")
    return Starlette(routes=routes)


async def consumer():
    async with httpx.AsyncClient() as http:
        card = (await http.get(URL + "/.well-known/agent-card.json")).json()
        print("DISCOVERED:", card["name"], [s["id"] for s in card["skills"]])
    client = await create_client(URL, ClientConfig(streaming=False))

    async def send(text, task_id=None):
        msg = new_text_message(text, role=Role.ROLE_USER, task_id=task_id)
        out = []
        async for resp in client.send_message(SendMessageRequest(message=msg)):
            out.append(resp)
        return out[-1]

    r1 = await send("reserve projector fri 14:00")
    t1 = r1.task
    print("TURN1 state:", TaskState.Name(t1.status.state), "|", get_message_text(t1.status.message))
    r2 = await send("accept", task_id=t1.id)
    t2 = r2.task
    print("TURN2 state:", TaskState.Name(t2.status.state), "|", [a.parts[0].text for a in t2.artifacts])


if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(build_app(), host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)
    asyncio.run(consumer())
