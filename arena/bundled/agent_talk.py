"""AgentTalk (one job): a person talking with their own agent. The messages are kept in the window app's state; the
concierge (an LLM) answers and may act through the owner's use cases. Used by the chat window and the console."""
from __future__ import annotations

import time


class AgentTalk:
    def __init__(self, settings):
        self.s = settings
        self.messages: list[dict] = []
        self.concierge = None  # chat.concierge.Concierge
        self._state = None

    def bind(self, state, service) -> None:
        """state: the window app's own state (load/save); service: the owner's use cases (None: no agent to talk to)"""
        self._state = state
        self.messages = list(state.load().get("messages", []))
        self.use(service)

    def use(self, service) -> None:
        from .chat.concierge import Concierge  # here, not at the top: the chat package itself uses AgentTalk
        self.concierge = Concierge(service, self.s) if service is not None else None

    def _add(self, who: str, text: str) -> dict:
        m = {"who": who, "text": text, "ts": time.time()}
        self.messages = (self.messages + [m])[-self.s.chat_keep_messages:]
        if self._state is not None:
            self._state.save({"messages": self.messages})
        return m

    async def say(self, ctx, text: str) -> list[dict]:
        """the person said something; the agent answers"""
        text = (text or "").strip()
        if not text or self.concierge is None:
            return []
        history = list(self.messages)
        out = [self._add("owner", text)]
        for reply in await self.concierge.respond(ctx, history, text):
            out.append(self._add("agent", reply))
        return out
