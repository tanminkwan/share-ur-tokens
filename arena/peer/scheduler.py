"""The peer's scheduler (user 2026-11-02): "이 시각에 이 일". Code, no LLM: it keeps timers in the peer's home (they
survive a restart), sleeps until the next one is due, and hands it to the app that set it (TimerHandler.on_timer). A
timer missed while the peer was off is handed over once when it comes back. Waking exactly when needed replaces an
agent waking again and again to ask "is it time yet?" (that is LLM calls and tokens)."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from .plugin import BaseApp, TimerHandler


def fmt_time(ts: float) -> str:
    """a time as people and agents read it: local time with its offset, to the second"""
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def parse_when(when, now: float) -> float:
    """'+600' (seconds from now), a number (seconds since the epoch) or an ISO 8601 time -> seconds since the epoch"""
    if isinstance(when, (int, float)) and not isinstance(when, bool):
        return float(when)
    w = str(when).strip()
    if w.startswith("+"):
        return now + float(w[1:])
    t = datetime.fromisoformat(w)
    return (t if t.tzinfo else t.astimezone()).timestamp()


class Scheduler(BaseApp):
    name, version, app_id = "platform.scheduler", "1.0", "9e4b7c21-3a5d-4f68-b1c9-2d7e0f8a6b35"

    def __init__(self, settings):
        self.s = settings
        self.timers: list[dict] = []
        self._ctx = None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    # ---- used through AppContext.schedule / cancel_timer / timers ----
    def add(self, ctx, app_id: str, at: float, kind: str, data: dict | None = None, event_id: str | None = None) -> str:
        t = {"id": uuid.uuid4().hex[:12], "app_id": app_id, "at": float(at), "kind": kind, "data": dict(data or {}), "event_id": event_id}
        self.timers.append(t)
        self.timers.sort(key=lambda x: x["at"])
        self._save(ctx)
        self._wake.set()
        return t["id"]

    def cancel(self, ctx, timer_id: str = None, *, app_id: str = None, event_id: str = None) -> int:
        keep = [t for t in self.timers if not ((timer_id and t["id"] == timer_id) or
                                               (timer_id is None and app_id and t["app_id"] == app_id and (event_id is None or t["event_id"] == event_id)))]
        n, self.timers = len(self.timers) - len(keep), keep
        self._save(ctx)
        return n

    def of(self, app_id: str, event_id: str | None = None) -> list[dict]:
        return [dict(t) for t in self.timers if t["app_id"] == app_id and (event_id is None or t["event_id"] == event_id)]

    # ---- lifecycle ----
    async def start(self, ctx) -> None:
        self._ctx = ctx
        self.timers = sorted(ctx.state.load().get("timers", []), key=lambda x: x["at"])
        if self._task is None:
            self._task = asyncio.create_task(self._loop(ctx))

    async def stop(self, ctx) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self, ctx):
        while True:
            try:
                await self.fire_due(ctx)
                wait = self.s.scheduler_max_sleep_sec if not self.timers else max(0.0, min(self.timers[0]["at"] - ctx.clock(), self.s.scheduler_max_sleep_sec))
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as e:  # a failing handler must not stop the clock
                ctx.log.emit("scheduler", ctx.pen, f"예약 처리 실패: {type(e).__name__}: {e}")
                await asyncio.sleep(self.s.scheduler_retry_sec)

    async def fire_due(self, ctx, now: float | None = None) -> int:
        """hand every due timer to its app (once); returns how many fired"""
        now = ctx.clock() if now is None else now
        due = [t for t in self.timers if t["at"] <= now]
        if not due:
            return 0
        self.timers = [t for t in self.timers if t["at"] > now]
        self._save(ctx)
        for t in due:
            app = ctx.app_by_id(t["app_id"])
            if isinstance(app, TimerHandler):
                ctx.log.emit("scheduler", ctx.pen, f"예약 시각: {t['kind']} ({app.name}{', ' + t['event_id'] if t['event_id'] else ''})")
                await app.on_timer(ctx.ctx_of(app), dict(t, late=now - t["at"]))
        return len(due)

    def _save(self, ctx) -> None:
        ctx.state.save({"timers": self.timers})
