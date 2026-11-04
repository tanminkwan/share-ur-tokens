"""Timeline (one job): what happened in one event, the way a person watching it reads it (user 2026-11-04: a window for
humans to watch and to step in). The transcript is what the LLM reads; this is who said what, in which direction:

    {ts, dir: in | out | note, by: peer | agent | owner | system, kind, who (the other side's pen name), text}

in: another peer spoke to me. out: my peer spoke to another (by my agent or by me). note: what happened besides (an
action and how it ended, my agent's thought, a notice, the ledger, a timer, my instruction)."""
from __future__ import annotations

import re

from .tools import LABELS

PUB = re.compile(r"^[0-9a-f]{64}$")


class Timeline:
    def __init__(self, settings, handles):
        self.s, self.handles = settings, handles

    def add(self, ctx, st, dir: str, by: str, kind: str, text: str, who: str | None = None) -> None:
        st.timeline.append({"ts": ctx.clock(), "dir": dir, "by": by, "kind": kind, "who": who,
                            "text": str(text)[: self.s.timeline_text_chars]})
        del st.timeline[: -self.s.assistant_timeline_max]

    def received(self, ctx, st, pub: str, kind: str, text: str) -> None:
        self.add(ctx, st, "in", "peer", kind, text, self.handles.handle(ctx, st, pub))

    def _name(self, ctx, st, who):
        """a person reads pen names, whether the call named a pen name or a public key"""
        return self.handles.handle(ctx, st, who) if isinstance(who, str) and PUB.match(who) else who

    def note(self, ctx, st, by: str, kind: str, text: str) -> None:
        self.add(ctx, st, "note", by, kind, text)

    def action(self, ctx, st, by: str, name: str, args: dict, result) -> None:
        """my side did something: a message out is a line of the conversation, anything else a note of how it ended"""
        ok = not (isinstance(result, dict) and (result.get("ok") is False or result.get("error")))
        if name == "send" and ok:
            self.add(ctx, st, "out", by, "message", args.get("text", ""), self._name(ctx, st, args.get("to")))
            return
        if name == "solicit" and ok:
            self.add(ctx, st, "out", by, "request", args.get("text", ""), ", ".join(self._name(ctx, st, t) for t in args.get("targets") or []))
            return
        why = "" if ok else f": {result.get('error') if isinstance(result, dict) else result}"
        pending = isinstance(result, dict) and result.get("pending")
        self.note(ctx, st, by, "action", f"{LABELS.get(name, name)} → {'기다리는 중' if pending else '완료' if ok else '실패'}{why}")
