"""DeskOwner: the platform's Owner (ask, write) and Notifier (notify, suggest) on the owner desk. A question not answered
in time is a "no" (dev/peer-spec.md 2.6)."""
from __future__ import annotations

from ...waiting import waiting_for
from ..owner import Answer
from .desk import OwnerDesk

WAITING = "waiting for the owner (a person) to answer"
UNANSWERED = "정해진 시간 안에 소유자의 답이 없어 아니오로 본다"


class DeskOwner:
    def __init__(self, desk: OwnerDesk, settings):
        self.desk, self.s = desk, settings

    async def ask(self, question: str, context: str = "", event_id: str | None = None, timeout: float | None = None) -> Answer:
        """timeout: how long to wait for this question (default ARENA_DESK_QUESTION_TIMEOUT_SEC); unanswered = no"""
        it = self.desk.add("question", question, context, event_id)
        waiting_for(WAITING)  # a caller following this answer as an A2A task sees why it takes long
        a = await self.desk.wait(it, self.s.desk_question_timeout_sec if timeout is None else timeout)
        if a is None:
            return Answer(False, UNANSWERED, answered=False)
        return Answer(bool(a.get("yes")), str(a.get("why") or ("예" if a.get("yes") else "아니오")))

    async def write(self, task: str, context: str, schema: dict) -> dict:
        props = (schema or {}).get("properties", {})
        fields = {k: str(v.get("description", k)) for k, v in props.items()}
        it = self.desk.add("write", task, context, fields=fields)
        waiting_for(WAITING)
        a = await self.desk.wait(it, self.s.desk_question_timeout_sec)
        if a is None:
            raise TimeoutError("소유자가 정해진 시간 안에 쓰지 않았다")
        got = a.get("fields") or {}
        return {k: got.get(k, "") for k in fields}

    # ---- Notifier ----
    def notify(self, kind: str, title: str, body: str = "", event_id: str | None = None) -> None:
        self.desk.add(kind, title, body, event_id)

    async def suggest(self, title: str, body: str, tool: str, args: dict, event_id: str | None = None) -> bool:
        it = self.desk.add("suggestion", title, body, event_id, fields={"tool": tool, "args": args})
        waiting_for(WAITING)
        a = await self.desk.wait(it, self.s.desk_question_timeout_sec)
        return bool(a and a.get("approve"))
