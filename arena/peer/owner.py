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
