"""Push notifications over A2A (user 2026-11-04: "a2a 방식은 sse, http, web hook으로 워키토키 방식으로 소통하는 것이 맞다",
"사람이 agent 흉내를 내는 것이 맞아"). No session is held between peers: a call is one message; a slow answer is a task;
when the task changes, the answering peer POSTs to the caller's webhook. The caller treats that only as a signal to
look again (tasks/get at the answering peer): the notification's body is never trusted, so a forged one changes
nothing. Looking again on a slow timer stays as the fallback when a notification does not come.

- TaskWatch (calling side): a one-time token per call, kept until the call is done; a notification with a known token
  wakes the waiting call, or the timer that will look again at a call that came back pending.
- push_url_ok (answering side): notifications go only to http(s) addresses ending in the webhook path, so a caller
  cannot make a peer POST to arbitrary internal addresses."""
from __future__ import annotations

import asyncio
import os
from collections import OrderedDict
from urllib.parse import urlsplit

NOTIFY_PATH = "/a2a/notify"
TOKEN_HEADER = "X-A2A-Notification-Token"


async def push_url_ok(url: str) -> bool:
    u = urlsplit(url)
    return u.scheme in ("http", "https") and bool(u.hostname) and u.path.endswith(NOTIFY_PATH)


def task_id_of(payload: dict) -> str | None:
    """the task a notification (an A2A StreamResponse as JSON) is about"""
    if not isinstance(payload, dict):
        return None
    for key, field in (("task", "id"), ("statusUpdate", "taskId"), ("artifactUpdate", "taskId")):
        v = payload.get(key)
        if isinstance(v, dict) and isinstance(v.get(field), str):
            return v[field]
    return None


class TaskWatch:
    def __init__(self, keep: int):
        self.keep = keep
        self.calls: OrderedDict[str, dict] = OrderedDict()  # token -> {wake, event_id, task_id, held}

    def issue(self, event_id: str | None = None) -> tuple[str, asyncio.Event]:
        token = os.urandom(16).hex()
        self.calls[token] = {"wake": asyncio.Event(), "event_id": event_id, "task_id": None, "held": False}
        while len(self.calls) > self.keep:
            self.calls.popitem(last=False)
        return token, self.calls[token]["wake"]

    def hold(self, token: str, task_id: str) -> None:
        """the call came back pending: keep listening for this task (the caller looks again later)"""
        if token in self.calls:
            self.calls[token].update(task_id=task_id, held=True)

    def done(self, token: str) -> None:
        self.calls.pop(token, None)

    def notify(self, token: str | None, task_id: str | None) -> dict | None:
        """a notification arrived: the call it belongs to (woken), or None when the token is unknown or for another task"""
        c = self.calls.get(token or "")
        if c is None or not task_id or (c["task_id"] not in (None, task_id)):
            return None
        c["task_id"] = task_id
        c["wake"].set()
        return c
