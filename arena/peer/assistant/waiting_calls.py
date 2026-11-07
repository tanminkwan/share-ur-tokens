"""WaitingCalls: calls of the basic assistant that came back pending (the other peer's answer is an A2A task still
working, e.g. its owner is deciding). One job: remember them per event and finish them when the answer arrives.

A tool that may get a pending answer registers how to finish it (`finisher(kind)`), so adding one does not change
this part (open/closed). The peer's scheduler wakes the assistant to look again (ARENA_ASSISTANT_PENDING_RECHECK_SEC);
the `check_pending` tool looks at once."""
from __future__ import annotations

from typing import Awaitable, Callable

FINISHERS: dict[str, Callable[..., Awaitable[dict]]] = {}
TIMER = "pending_check"


def finisher(kind: str):
    """register how a tool finishes once its pending answer arrives: async (host, ctx, st, answer, data) -> result"""
    def register(fn):
        if kind in FINISHERS:
            raise ValueError(f"finisher {kind!r} registered twice")
        FINISHERS[kind] = fn
        return fn
    return register


class WaitingCalls:
    def __init__(self, settings):
        self.s = settings

    def hold(self, ctx, st, answer: dict, kind: str, data: dict) -> dict:
        """keep a pending answer to finish later; -> what the tool reports now"""
        st.waiting_calls[answer["task_id"]] = {"url": answer["url"], "pub": answer.get("pub"), "kind": kind, "data": data, "since": ctx.clock()}
        self._wake_later(ctx, st)
        return {"ok": False, "pending": True, "task_id": answer["task_id"], "waiting_for": answer.get("error", ""),
                "note": "상대가 아직 답하지 않았다(사람이 정하는 중일 수 있다). 거절이 아니다. 코드가 정해진 간격으로 다시 확인해 "
                        "답이 오면 마저 처리하고 알린다. 지금 확인하려면 check_pending"}

    def _wake_later(self, ctx, st) -> None:
        if not any(t["kind"] == TIMER for t in ctx.timers(st.event_id)):
            ctx.schedule(ctx.clock() + self.s.assistant_pending_recheck_sec, TIMER, {}, event_id=st.event_id)

    async def check(self, host, ctx, st, task_id: str | None = None) -> list[dict]:
        """look at the waiting calls (or one); finish those whose answer arrived"""
        out = []
        for tid, w in list(st.waiting_calls.items()):
            if task_id and tid != task_id:
                continue
            r = await ctx.check_task(w["url"], tid, pub=w.get("pub"))  # where the peer is now, if it moved
            if r.get("pending"):
                out.append({"task_id": tid, "kind": w["kind"], "pending": True, "waiting_for": r.get("error", "")})
                continue
            del st.waiting_calls[tid]
            done = await FINISHERS[w["kind"]](host, ctx, st, r, w["data"]) if r.get("ok") else {"ok": False, "error": r.get("error")}
            out.append({"task_id": tid, "kind": w["kind"], **done})
        if st.waiting_calls:
            self._wake_later(ctx, st)
        return out

    @staticmethod
    def line(st) -> str:
        """for the state line: what is still waiting"""
        return ("기다리는 답: " + "; ".join(f"{w['kind']}({tid[:8]})" for tid, w in st.waiting_calls.items()) + " / ") if st.waiting_calls else ""
