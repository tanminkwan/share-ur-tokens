"""OwnerService: what the owner's screen may do (the application layer, P6-P5). It knows the peer, the desk and the basic
assistant; it does not know HTTP. Every check (signatures, the ledger, handles) stays in the peer's code."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..llm import llm_available
from ..peer.desk import OwnerDesk
from ..peer.scheduler import fmt_time


@runtime_checkable
class EventsPort(Protocol):
    """what the owner's windows need from the app that runs the peer's events (the basic assistant is one). The service
    depends on this, not on a particular class"""
    events: dict
    DRIVES: tuple

    def allowed_drives(self, ctx) -> tuple: ...
    def state_line(self, ctx, st) -> str: ...
    def tools_view(self, st) -> list: ...
    def conversation(self, ctx, st, lines: int) -> dict: ...
    def set_drive(self, ctx, event_id: str, drive: str) -> dict: ...
    async def owner_run(self, ctx, event_id: str, name: str, args: dict) -> dict: ...
    async def feed(self, ctx, event_id: str, text: str, idle: bool = False, kind: str = "message"): ...
    async def host_event(self, ctx, **kw) -> str: ...


class OwnerService:
    def __init__(self, peer, desk: OwnerDesk):
        self.peer, self.desk = peer, desk

    @property
    def _asst(self) -> EventsPort:
        return next(a for a in self.peer.apps if isinstance(a, EventsPort))

    @property
    def _ctx(self):
        return self.peer.ctx(self._asst)

    def config(self) -> dict:
        """what the screen needs to know in advance (no constants in the screen's code)"""
        from ..ledger.schedule import TIME_CODES
        from ..peer.desk.model import ITEM_KINDS
        return {"poll_ms": self.peer.settings.desk_poll_ms, "drives": list(self._asst.allowed_drives(self._ctx)),
                "time_codes": {c: t.description for c, t in TIME_CODES.items()},
                "item_kinds": {k: v.label for k, v in ITEM_KINDS.items()}}

    def state(self) -> dict:
        p = self.peer
        events = [{"event_id": st.event_id, "title": st.title, "role": st.role, "drive": st.drive, "closed": st.closed}
                  for st in self._asst.events.values()]
        from .peer_kinds import kind_view
        return {"me": {"pen": p.pen, "nick": p.nick, "reach": p.relay.state["mode"] if p.relay else None, "pub": p.identity.pub, "operator": p.operator(), "llm": llm_available(p.llm), **kind_view(p.config.kind)},
                "events": sorted(events, key=lambda x: (x["closed"], x["title"])), "open_items": len(self.desk.list("open"))}

    async def set_nick(self, nick: str) -> dict:
        """the owner renames this peer, any time (P9-A5); the peer posts its profile again at once"""
        return await self.peer.set_nick(nick)

    def items(self, status: str = "open") -> list[dict]:
        return [it.to_dict() for it in self.desk.list(status if status in ("open", "all") else "open")]

    def item(self, item_id: str):
        """one desk item, or None"""
        return self.desk.items.get(item_id)

    def answer(self, item_id: str, answer: dict) -> dict:
        try:
            return {"ok": True, "item": self.desk.answer(item_id, answer or {}).to_dict()}
        except KeyError:
            return {"ok": False, "error": "없는 알림"}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def event(self, event_id: str) -> dict | None:
        a, ctx = self._asst, self._ctx
        st = a.events.get(event_id)
        if st is None:
            return None
        n = self.peer.settings.desk_transcript_lines
        return {"event_id": st.event_id, "title": st.title, "role": st.role, "drive": st.drive, "closed": st.closed, "rules": st.rules,
                "state_line": a.state_line(ctx, st), "transcript": st.transcript[-n:], "tools": a.tools_view(st),
                "schedule": [dict(x, when=fmt_time(x["at"])) for x in st.schedule],
                "timers": [dict(t, when=fmt_time(t["at"])) for t in ctx.timers(event_id)],
                **a.conversation(ctx, st, self.peer.settings.desk_transcript_lines)}

    async def say(self, event_id: str, to: str, text: str) -> dict:
        """the person speaks as their peer to another in this event (one message, a2a: walkie-talkie)"""
        text = (text or "").strip()
        if not text or not to:
            return {"ok": False, "error": "받는 이와 할 말이 필요하다"}
        return await self.run_tool(event_id, "send", {"to": to, "text": text, "data_json": "{}"})

    async def tell(self, event_id: str, text: str) -> dict:
        """pass the owner's words to the assistant of one event (it acts on them in its drive)"""
        if event_id not in self._asst.events:
            return {"ok": False, "error": "모르는 이벤트"}
        await self._asst.feed(self._ctx, event_id, f"[소유자의 지시] {text}", kind="owner")
        return {"ok": True}

    def find_event(self, ref: str) -> str | None:
        """an event named by its id or its exact title"""
        if ref in self._asst.events:
            return ref
        return next((st.event_id for st in self._asst.events.values() if st.title == ref), None)

    def set_drive(self, event_id: str, drive: str) -> dict:
        return self._asst.set_drive(self._ctx, event_id, drive)

    async def run_tool(self, event_id: str, name: str, args: dict) -> dict:
        return await self._asst.owner_run(self._ctx, event_id, name, args or {})

    async def host(self, form: dict) -> dict:
        need = [k for k in ("title", "kind", "rules") if not str(form.get(k, "")).strip()]
        if need:
            return {"ok": False, "error": f"빠진 칸: {', '.join(need)}"}
        try:
            ev = await self._asst.host_event(self._ctx, title=form["title"], kind=form["kind"], rules=form["rules"],
                                             policy=form.get("policy") or {"roles": ["member"]}, instruction=form.get("instruction") or "규칙대로 진행한다",
                                             elements=form.get("elements") or None, schedule=form.get("schedule") or None)
        except (RuntimeError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "event_id": ev}
