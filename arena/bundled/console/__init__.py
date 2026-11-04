"""The console (bundled app, not required; user 2026-11-04: "a2a 방식이어도 관전 또는 인간 개입을 위한 인간을 위한 통합 ui는
필요해. 물론 plugin app이고"). One window for a person, whatever drives their peer:

- watch: every event's conversation as it happens (who said what to whom, in which direction), what the code says
  of where it stands, my desk's questions and suggestions;
- step in: speak as my peer to another in the event (one message, a2a walkie-talkie), instruct my agent (when there
  is an LLM), answer questions, switch the drive, run a tool by hand, open an event.

It is a local web window onto the owner API (the desk's use cases) plus the conversation; the peer core has no screen."""
from __future__ import annotations

from ..agent_talk import AgentTalk
from ..owner_service import OwnerService
from ..web import LocalWebApp
from .api import build_console_api


class ConsoleApp(LocalWebApp):
    name, version, app_id = "bundled.console", "1.0", "2f7a9c1e-6b3d-4e58-8a0f-5c1d9e3b7a42"

    def __init__(self, service: OwnerService | None, settings, host: str, port: int, token: str):
        super().__init__(host, port, token)
        self.s, self.service = settings, service
        self.talk = AgentTalk(settings)
        self._ctx = None

    def web_app(self, ctx):
        return build_console_api(self, self.token)

    def bind(self, ctx) -> None:
        self._ctx = ctx
        self.talk.bind(ctx.state, self.service if self.agent_available() else None)

    async def start(self, ctx) -> None:
        self.bind(ctx)
        await super().start(ctx)

    def agent_available(self) -> bool:
        """an agent to talk with: the peer has an LLM"""
        return bool(self.service and self.service.state()["me"]["llm"])

    def agent_feed(self) -> dict:
        return {"available": self.agent_available(), "messages": self.talk.messages}

    async def agent_say(self, text: str) -> list[dict]:
        return await self.talk.say(self._ctx, text)
