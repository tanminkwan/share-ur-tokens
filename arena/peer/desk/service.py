"""OwnerService: what the owner's screen may do (the application layer, P6-P5). It knows the peer, the desk and the basic
assistant; it does not know HTTP. Every check (signatures, the ledger, handles) stays in the peer's code."""
from __future__ import annotations

from ...llm import NoLLM
from ..assistant import EventAssistant
from ..scheduler import fmt_time
from .desk import OwnerDesk


class OwnerService:
    def __init__(self, peer, desk: OwnerDesk):
        self.peer, self.desk = peer, desk

    @property
    def _asst(self) -> EventAssistant:
        return self.peer.app(EventAssistant)

    @property
    def _ctx(self):
        return self.peer.ctx(EventAssistant)

    def config(self) -> dict:
        """what the screen needs to know in advance (no constants in the screen's code)"""
        from ...ledger.schedule import TIME_CODES
        from .model import ITEM_KINDS
        return {"poll_ms": self.peer.settings.desk_poll_ms, "drives": list(self._asst.allowed_drives(self._ctx)),
                "time_codes": {c: t.description for c, t in TIME_CODES.items()},
                "item_kinds": {k: v.label for k, v in ITEM_KINDS.items()}}

    def state(self) -> dict:
        p = self.peer
        events = [{"event_id": st.event_id, "title": st.title, "role": st.role, "drive": st.drive, "closed": st.closed}
                  for st in self._asst.events.values()]
        return {"me": {"pen": p.pen, "pub": p.identity.pub, "operator": p.operator(), "llm": not isinstance(p.llm, NoLLM)},
                "events": sorted(events, key=lambda x: (x["closed"], x["title"])), "open_items": len(self.desk.list("open"))}

    def items(self, status: str = "open") -> list[dict]:
        return [it.to_dict() for it in self.desk.list(status if status in ("open", "all") else "open")]

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
                "timers": [dict(t, when=fmt_time(t["at"])) for t in ctx.timers(event_id)]}

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
