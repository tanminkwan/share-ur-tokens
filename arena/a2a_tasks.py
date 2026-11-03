"""Slow answers over A2A as tasks (user 2026-11-03). Three parts, one job each:

- SlowAnswer (the answering side): run an op; if it finishes within the answer window, answer with one message;
  otherwise report a task in state `working` with what it waits for (arena/waiting.py) and complete it later.
- TaskFollower (the calling side): follow a task with tasks/get until it ends or the wait runs out (then: pending and
  the task id, so the caller can tell it apart from a refusal).
- FileTaskStore (the answering side): keeps the tasks in the peer's home, so a caller still gets an answer after a
  restart. A task that was still working when the peer stopped is closed as failed ("ask again"): the person's
  question on the desk is closed the same way (OwnerDesk), so nothing waits for an answer that cannot come.

`working`, not `input-required`: the person waited on is the answering peer's own owner. `input-required` means the
answering agent needs more input from the caller; a caller following another agent's task is told so (needs_input)."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Awaitable, Callable

from a2a.helpers.proto_helpers import get_message_text, new_task, new_text_message
from a2a.server.tasks import TaskStore, TaskUpdater
from a2a.types import GetTaskRequest, ListTasksResponse, Task, TaskState, TaskStatus
from google.protobuf import json_format

from .waiting import watch

DONE_BAD = {TaskState.TASK_STATE_FAILED: "failed", TaskState.TASK_STATE_CANCELED: "canceled", TaskState.TASK_STATE_REJECTED: "rejected"}
NEEDS_INPUT = (TaskState.TASK_STATE_INPUT_REQUIRED, TaskState.TASK_STATE_AUTH_REQUIRED)
SLOW = "the answer takes longer than usual"


def json_message(obj, context_id=None, task_id=None):
    m = new_text_message(json.dumps(obj, ensure_ascii=False), context_id=context_id)
    if task_id:
        m.task_id = task_id
    return m


class SlowAnswer:
    def __init__(self, answer_wait: float):
        self.answer_wait = answer_wait

    async def answer(self, run: Callable[[], Awaitable[dict]], context, event_queue) -> None:
        with watch() as holder:
            job = asyncio.ensure_future(run())  # the op sees the holder (the task copies the context here)
        done, _ = await asyncio.wait({job}, timeout=self.answer_wait)
        if job in done:
            await event_queue.enqueue_event(json_message(job.result(), context.context_id))
            return
        await event_queue.enqueue_event(new_task(context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED,
                                                 history=[context.message] if context.message is not None else []))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work(json_message({"waiting": True, "note": holder["note"] or SLOW}, context.context_id, context.task_id))
        await updater.complete(json_message(await job, context.context_id, context.task_id))


def task_text(task) -> str:
    return get_message_text(task.status.message) if task.status.HasField("message") else ""


def _note(text: str) -> str:
    try:
        return json.loads(text).get("note") or text
    except (ValueError, AttributeError):
        return text


class TaskFollower:
    def __init__(self, poll: float, clock: Callable[[], float] = time.monotonic, sleep=asyncio.sleep):
        self.poll, self.clock, self.sleep = poll, clock, sleep

    async def follow(self, client, task, wait: float) -> dict:
        end = self.clock() + wait
        while True:
            st = task.status.state
            if st == TaskState.TASK_STATE_COMPLETED:
                return json.loads(task_text(task))
            if st in DONE_BAD:
                return {"ok": False, "error": f"the peer's task {DONE_BAD[st]}: {task_text(task)}", "task_id": task.id}
            if st in NEEDS_INPUT:
                return {"ok": False, "error": f"the peer needs input: {task_text(task)}", "task_id": task.id, "needs_input": True}
            if self.clock() >= end:
                return {"ok": False, "pending": True, "task_id": task.id, "error": f"still waiting: {_note(task_text(task))}"}
            await self.sleep(min(self.poll, max(0.0, end - self.clock())))
            task = await client.get_task(GetTaskRequest(id=task.id))


RESTARTED = {"ok": False, "error": "the peer restarted before it could answer; ask again"}
TERMINAL = {TaskState.TASK_STATE_COMPLETED, *DONE_BAD}


class FileTaskStore(TaskStore):
    def __init__(self, path: str, keep: int):
        self.path, self.keep = path, keep
        self.tasks: dict[str, Task] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for d in json.load(f):
                    t = json_format.ParseDict(d, Task())
                    if t.status.state not in TERMINAL:  # it was still working when the peer stopped
                        t.status.CopyFrom(TaskStatus(state=TaskState.TASK_STATE_FAILED, message=json_message(RESTARTED, t.context_id, t.id)))
                    self.tasks[t.id] = t
            self._write()

    def _write(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([json_format.MessageToDict(t) for t in self.tasks.values()], f, ensure_ascii=False)
        os.replace(tmp, self.path)

    async def save(self, task, context=None) -> None:
        self.tasks.pop(task.id, None)
        self.tasks[task.id] = Task().FromString(task.SerializeToString())  # a copy, newest last
        while len(self.tasks) > self.keep:
            self.tasks.pop(next(iter(self.tasks)))
        self._write()

    async def get(self, task_id, context=None):
        return self.tasks.get(task_id)

    async def list(self, params, context=None):
        out = [t for t in self.tasks.values() if (not params.context_id or t.context_id == params.context_id)
               and (not params.status or t.status.state == params.status)]
        return ListTasksResponse(tasks=list(reversed(out)))

    async def delete(self, task_id, context=None) -> None:
        if self.tasks.pop(task_id, None) is not None:
            self._write()

