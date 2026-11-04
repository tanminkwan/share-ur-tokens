"""The chat app (bundled, not required): a person talks with their own agent in a local web window. The agent (the
concierge) handles the screen side: it tells the person how things stand and passes the person's words on; the agent's
pending questions show in the chat, and the person may answer them with a button or in words. This is how a person takes
part in a2a through their agent (dev/peer-spec.md 1.1)."""
from __future__ import annotations

from ..owner_service import OwnerService
from ..web import LocalWebApp
from .api import build_chat_api
from ..agent_talk import AgentTalk


class ChatApp(LocalWebApp):
    name, version, app_id = "bundled.chat", "1.0", "8b2e4f6a-9c1d-4e73-a5b8-0f2c6d9e1a47"

    def __init__(self, service: OwnerService, settings, host: str, port: int, token: str):
        super().__init__(host, port, token)
        self.s = settings
        self.talk = AgentTalk(settings)
        self._ctx = None
        self.service = service

    @property
    def service(self) -> OwnerService:
        return self._service

    @service.setter
    def service(self, svc: OwnerService | None) -> None:
        self._service = svc
        self.talk.use(svc)

    @property
    def concierge(self):
        return self.talk.concierge

    @property
    def messages(self) -> list[dict]:
        return self.talk.messages

    def web_app(self, ctx):
        return build_chat_api(self, self.token)

    async def start(self, ctx) -> None:
        self.bind(ctx)
        await super().start(ctx)

    def bind(self, ctx) -> None:
        """for composition roots and tests that drive the app without starting its window"""
        self._ctx = ctx
        self.talk.bind(ctx.state, self._service)

    async def say(self, text: str) -> list[dict]:
        """the owner said something: the agent answers (and may act through the owner's use cases)"""
        return await self.talk.say(self._ctx, text)

    def feed(self) -> dict:
        st = self.service.state()
        return {"me": st["me"], "messages": self.messages, "items": self.service.items("open"), "poll_ms": self.s.desk_poll_ms}
