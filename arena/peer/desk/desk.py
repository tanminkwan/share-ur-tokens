"""OwnerDesk: keeps the items and the person's answers; hands an answer to whoever waits for it. OwnerDeskApp is the
peer app that owns the desk so it is kept in the peer's home (an item awaited before a restart is closed as "no")."""
from __future__ import annotations

import asyncio
import uuid

from ..plugin import BaseApp
from .model import ITEM_KINDS, DeskItem


class OwnerDesk:
    def __init__(self, clock, save=lambda items: None, keep: int = 500):
        self.clock, self._save, self.keep = clock, save, keep
        self.items: dict[str, DeskItem] = {}
        self._waiting: dict[str, asyncio.Future] = {}

    def load(self, items: list[dict]) -> None:
        self.items = {d["id"]: DeskItem.from_dict(d) for d in items}
        for it in self.items.values():  # nobody waits any more: close what was awaited as "no"
            if it.status == "open" and ITEM_KINDS[it.kind].awaits:
                it.status, it.answer = "done", {"yes": False, "approve": False, "why": "peer가 다시 시작되어 닫힘"}

    def add(self, kind: str, title: str, body: str = "", event_id: str | None = None, fields: dict | None = None) -> DeskItem:
        if kind not in ITEM_KINDS:
            raise ValueError(f"unknown desk item kind {kind!r}")
        it = DeskItem(uuid.uuid4().hex[:12], kind, title, body, event_id, dict(fields or {}), created=self.clock())
        self.items[it.id] = it
        self._trim()
        self._persist()
        return it

    async def wait(self, item: DeskItem, timeout: float) -> dict | None:
        """the person's answer to an awaited item, or None after the timeout (the item is then closed unanswered)"""
        fut = asyncio.get_running_loop().create_future()
        self._waiting[item.id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            item.status, item.answer = "done", {"timeout": True}
            self._persist()
            return None
        finally:
            self._waiting.pop(item.id, None)

    def answer(self, item_id: str, answer: dict) -> DeskItem:
        it = self.items.get(item_id)
        if it is None:
            raise KeyError(item_id)
        if it.status != "open":
            raise ValueError("already answered")
        keys = ITEM_KINDS[it.kind].answer_keys
        it.status, it.answer = "done", {k: answer[k] for k in keys if k in answer}
        self._persist()
        fut = self._waiting.get(item_id)
        if fut is not None and not fut.done():
            fut.set_result(it.answer)
        return it

    def list(self, status: str = "open", event_id: str | None = None) -> list[DeskItem]:
        out = [it for it in self.items.values() if (status == "all" or it.status == status) and (event_id is None or it.event_id == event_id)]
        return sorted(out, key=lambda x: x.created, reverse=True)

    def _trim(self) -> None:
        done = sorted((it for it in self.items.values() if it.status == "done"), key=lambda x: x.created)
        for it in done[:max(0, len(self.items) - self.keep)]:
            self.items.pop(it.id, None)

    def _persist(self) -> None:
        self._save([it.to_dict() for it in self.items.values()])


class OwnerDeskApp(BaseApp):
    """holds the desk inside the peer so it survives restarts (the app state is kept in the peer's home)"""
    name, version, app_id = "platform.owner_desk", "1.0", "3a7c5e9d-1b2f-4c6a-8e0d-7f9b1a3c5e72"

    def __init__(self, desk: OwnerDesk):
        self.desk = desk

    async def start(self, ctx) -> None:
        self.desk.load(ctx.state.load().get("items", []))
        self.desk._save = lambda items: ctx.state.save({"items": items})
