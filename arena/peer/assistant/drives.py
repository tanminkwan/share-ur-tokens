"""Drives (P6-P4): who drives an event (auto: the LLM, suggest: the LLM proposes and the owner approves, manual: the owner),
which drives this peer allows, and how the owner is told and asked. One responsibility: the owner's seat."""
from __future__ import annotations

import json

from ...llm import llm_available
from ..owner import Notifier


class Drives:
    ALL = ("auto", "suggest", "manual")
    NOTIFY_IN_AUTO = ("notice", "timer")  # the owner hears of these even while the LLM drives
    READ_ONLY = ("note", "event_progress", "verify", "my_reveal", "check_reveal", "contact", "submissions", "verdicts", "ask_owner")

    def __init__(self, settings):
        self.s = settings

    def allowed(self, ctx) -> tuple:
        """no LLM: only the owner drives. A human peer (dev/peer-spec.md 1.2): the person drives; an LLM plugin may only
        suggest, never act on its own"""
        if not llm_available(ctx.llm):
            return ("manual",)
        if ctx.operator == "human":
            return ("manual", "suggest")
        return self.ALL

    def initial(self, ctx) -> str:
        allowed = self.allowed(ctx)
        return self.s.peer_default_drive if self.s.peer_default_drive in allowed else allowed[0]

    def refuse(self, ctx, drive: str) -> str | None:
        """why this drive may not be chosen here, or None"""
        if drive not in self.ALL:
            return f"운전석은 {', '.join(self.ALL)} 가운데 하나"
        if drive not in self.allowed(ctx):
            return "LLM이 없는 peer는 수동(manual)만 된다" if not llm_available(ctx.llm) else "사람 peer는 수동(manual)이나 제안(suggest)만 된다"
        return None

    @staticmethod
    def notifier(ctx):
        return ctx.owner if isinstance(ctx.owner, Notifier) else None

    def title_body(self, text: str) -> tuple[str, str]:
        """a desk item's title and body: the first line is the title; the body is the rest, or the whole text only when
        the first line had to be cut (never the title said twice). `text` is already shortened"""
        first, _, rest = text.partition("\n")
        if len(first) > self.s.desk_title_chars:
            return first[:self.s.desk_title_chars] + "…", text
        return first, rest.strip()

    async def approved(self, ctx, st, name, args, thought, shorten) -> bool:
        """suggest: the owner approves an action before it runs (nobody to ask: it runs)"""
        note = self.notifier(ctx)
        if note is None:
            return True
        return await note.suggest(f"비서가 '{name}'을(를) 하려 합니다", shorten(f"{thought}\n인자: {json.dumps(args, ensure_ascii=False)}"),
                                  name, args, st.event_id)
