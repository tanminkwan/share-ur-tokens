"""The person behind a peer. The assistant asks them yes/no questions and asks them to write things.
The demo plugs in a persona (an LLM playing the person); a real UI will implement the same interface."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Answer:
    yes: bool
    why: str


class Owner(Protocol):
    async def ask(self, question: str, context: str = "") -> Answer: ...
    async def write(self, task: str, context: str, schema: dict) -> dict: ...


class NoOwner:
    """for autonomous peers: nobody to ask, so every question is answered no and nothing is written"""

    async def ask(self, question, context=""):
        return Answer(False, "사람이 없는 자율 peer라 소유자 확인이 필요한 일은 하지 않습니다")

    async def write(self, task, context, schema):
        raise PermissionError("autonomous peer: no owner to write")
