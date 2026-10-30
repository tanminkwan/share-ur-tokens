"""Observability: components write (kind, actor, text) to an injected EventLog; the dashboard reads it."""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class EventLog:
    def __init__(self, keep: int = 2000, echo: bool = True, clock: Callable[[], float] = time.time):
        self.items: deque = deque(maxlen=keep)
        self.echo, self.clock, self._subs = echo, clock, []

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        self._subs.append(fn)

    def emit(self, kind: str, actor: str, text: str) -> None:
        e = {"ts": self.clock(), "kind": kind, "actor": actor, "text": text}
        self.items.append(e)
        if self.echo:
            print(f"[{kind:9}] {actor}: {text}", flush=True)
        for fn in self._subs:
            fn(e)

    def tail(self, n: int) -> list[dict]:
        return list(self.items)[-n:]
