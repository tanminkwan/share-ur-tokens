"""What an answer is waiting for (user 2026-11-03: a person answers at a person's pace). Transport-neutral: whoever
serves a request opens a watch around the handler; anything the handler calls may say what it waits for (the owner
desk does: "waiting for the owner"). The A2A server shows it in a slow answer's task status; nothing else depends on A2A."""
from __future__ import annotations

import contextvars
from contextlib import contextmanager

_NOTE: contextvars.ContextVar = contextvars.ContextVar("arena_waiting", default=None)


def waiting_for(note: str) -> None:
    """say what the current answer waits for (no effect outside a watch)"""
    holder = _NOTE.get()
    if holder is not None:
        holder["note"] = note


@contextmanager
def watch():
    """-> a holder {"note"} filled by waiting_for() in tasks started inside this block (they copy the context)"""
    holder = {"note": None}
    token = _NOTE.set(holder)
    try:
        yield holder
    finally:
        _NOTE.reset(token)
