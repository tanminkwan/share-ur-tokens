"""An event's schedule (user 2026-11-02: "가위바위보 game이 특정 시간에 서로 session을 맺고 경기해라라는 식의 룰을 가지고
있었다면 그 시간에 action할 수 있어야지"). The event declaration may carry `schedule`: a list of {at, code, subject?, note?}.
It is notarized with the declaration, so every participant sees the same times; each peer's scheduler wakes its app or
assistant at those times. What must hold at a time (a deadline) is the ledger's to enforce with its own clock (ts);
acting at a time is the peers'. Time codes are registered like purpose codes and listed in the code table."""
from __future__ import annotations

import numbers
from dataclasses import dataclass

from .types import EventColumn, register_event_column


@dataclass(frozen=True)
class TimeCode:
    code: str
    description: str


TIME_CODES: dict[str, TimeCode] = {}


def register_time_code(t: TimeCode) -> None:
    if t.code in TIME_CODES:
        raise ValueError(f"time code {t.code!r} registered twice")
    TIME_CODES[t.code] = t


for _t in (TimeCode("start", "시작: 이벤트의 진행을 시작하는 시각"),
           TimeCode("session", "만나서 진행: 당사자들이 그 시각에 서로 연결해 함께 진행한다(subject로 어느 주제인지)"),
           TimeCode("deadline", "마감: 그 시각까지 해야 할 일의 마감(무엇의 마감인지는 note나 규칙에)"),
           TimeCode("end", "끝: 진행을 마치고 결과를 정리해 닫는 시각")):
    register_time_code(_t)


def check_schedule(schedule, max_items: int) -> str | None:
    if not isinstance(schedule, list) or not schedule:
        return "schedule must be a non-empty list of {at, code, subject?, note?}"
    if len(schedule) > max_items:
        return f"schedule: at most {max_items} items"
    for x in schedule:
        if not isinstance(x, dict) or not set(x) <= {"at", "code", "subject", "note"}:
            return "schedule items are {at, code, subject?, note?}"
        if not isinstance(x.get("at"), numbers.Real) or isinstance(x.get("at"), bool):
            return "schedule: at must be a time in seconds"
        if x.get("code") not in TIME_CODES:
            return f"schedule: unknown time code {x.get('code')!r}"
        if any(k in x and not isinstance(x[k], str) for k in ("subject", "note")):
            return "schedule: subject and note are text"


register_event_column(EventColumn("schedule", lambda chain, p, s: check_schedule(p["schedule"], s.event_schedule_max)))
