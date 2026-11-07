"""The interface of what the platform injects into an app. Program against this, not against a concrete class.

SOLID re-check (2026-11-03, interface segregation): the context is offered as small interfaces, each one kind of thing,
so an app (or a test double) can say and provide only what it uses: `def handle(ctx: Messaging, ...)`. `Context` is all of
them together, and the platform's context provides all of them (a test keeps them equal: tests/test_sdk_context.py)."""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable


class State(Protocol):
    """the app's own persistent dict (kept in the peer's home across restarts)"""
    def load(self) -> dict: ...
    def save(self, state: dict) -> None: ...


@runtime_checkable
class Me(Protocol):
    """who I am"""
    app_name: str

    @property
    def pub(self) -> str: ...
    @property
    def pen(self) -> str: ...
    @property
    def nick(self) -> str: ...  # the nickname part of my pen name (the owner may change it any time)
    @property
    def url(self) -> str: ...
    @property
    def labels(self) -> list[str]: ...
    @property
    def operator(self) -> str: ...
    @property
    def identity(self): ...
    def sign(self, payload) -> str: ...


@runtime_checkable
class Platform(Protocol):
    """the platform's services: settings, time, the log, the LLM, the person, the public area"""
    @property
    def settings(self): ...
    def clock(self) -> float: ...
    @property
    def log(self): ...
    @property
    def llm(self): ...
    @property
    def owner(self): ...
    @property
    def area(self): ...


@runtime_checkable
class Storage(Protocol):
    """this app's own place to keep things"""
    state: State

    @property
    def data_dir(self) -> str: ...


@runtime_checkable
class LedgerAccess(Protocol):
    """recorders and their ledgers: reach one, prove it from the root of trust, keep the recorder's receipts"""
    @property
    def known_recorders(self) -> list[str]: ...
    @property
    def receipts(self): ...
    def recorder(self, url: str): ...
    async def recorder_trust(self, url: str) -> dict: ...
    async def ledger_id(self, url: str) -> str | None: ...


@runtime_checkable
class Messaging(Protocol):
    """other peers and the brokers: call by address or by who they are (their listed connections), look again at a slow
    answer that came back pending, find profiles, direct requests, whether a broker group keeps a ledger"""
    @property
    def brokers(self) -> Mapping: ...
    async def call(self, url: str, msg: dict, timeout: float | None = None, group: str | None = None, event: str | None = None) -> dict: ...
    async def call_peer(self, pub: str, msg: dict, timeout: float | None = None, group: str | None = None, event: str | None = None,
                        url: str | None = None) -> dict: ...
    async def check_task(self, url: str, task_id: str, wait: float | None = None, pub: str | None = None) -> dict: ...  # pub: look where that peer is now
    async def profile_of(self, pub: str) -> dict | None: ...
    async def solicit(self, targets: list[str], request: dict) -> dict: ...
    async def group_id(self, group: str) -> str: ...
    async def group_mode(self, group: str, fresh: bool = False) -> dict: ...


@runtime_checkable
class Showing(Protocol):
    """how this peer shows itself: what it offers, posting the profile, learning from experience"""
    def offers(self) -> list[str]: ...
    async def advertise(self) -> dict: ...
    async def add_experience(self, note: str) -> None: ...


@runtime_checkable
class Scheduling(Protocol):
    """the peer's scheduler: wake this app (TimerHandler.on_timer) at a time; kept across restarts"""
    def schedule(self, at: float, kind: str, data: dict | None = None, event_id: str | None = None) -> str: ...
    def cancel_timer(self, timer_id: str | None = None, event_id: str | None = None) -> int: ...
    def timers(self, event_id: str | None = None) -> list[dict]: ...


@runtime_checkable
class ElementAccess(Protocol):
    """what the built-in elements keep for this peer (submissions received, through any SubmissionSource app)"""
    async def submissions(self, event_id: str) -> list: ...


@runtime_checkable
class Context(Me, Platform, Storage, LedgerAccess, Messaging, Showing, Scheduling, ElementAccess, Protocol):
    """everything the platform injects into an app"""


PARTS = (Me, Platform, Storage, LedgerAccess, Messaging, Showing, Scheduling, ElementAccess)
