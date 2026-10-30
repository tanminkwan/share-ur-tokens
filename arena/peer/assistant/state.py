"""What the basic assistant knows about one event, and how it is saved (secrets apart, owner-only)."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

from ...crypto import canon, h


def commit_hash(label: str, value, salt: str, pub: str) -> str:
    return h(canon({"label": label, "value": value, "salt": salt, "pub": pub}))


def nonce(*parts) -> str:
    return h(canon([*parts, time.time(), os.urandom(8).hex()]))[:16]


@dataclass
class EventState:
    event_id: str
    role: str  # "host" | "participant"
    title: str
    rules: str
    rules_hash: str
    group_id: str
    recorder_url: str
    recorder_pub: str
    issuer_pub: str
    issuer_url: str
    offer_roles: list = field(default_factory=list)
    transcript: list = field(default_factory=list)
    secrets: dict = field(default_factory=dict)      # label -> {value, salt, commit, publish_hash}
    pending: dict = field(default_factory=dict)      # signature requests waiting for me: id -> {payload, from_pub, from_url}
    proposals: dict = field(default_factory=dict)    # my attest proposals: id -> {payload, sigs}
    peers: dict = field(default_factory=dict)        # pub -> url learned from messages and contracts
    contracts: list = field(default_factory=list)    # [role, contractor pub] this host has contracted (kept by code)
    aliases: dict = field(default_factory=dict)      # what the LLM sees -> the real value: 필명-xxxxxx -> public key, #ab12.. -> hash
    last_action: list = field(default_factory=list)  # [tool, args] of the last tool run (to refuse an identical repeat)
    joined: bool = False
    closed: bool = False
    notice_ver: int = 1
    notice_closed: bool = False
    last_input_at: float = 0.0
    idle_checks: int = 0
    inbox: list = field(default_factory=list)
    task: asyncio.Task | None = None

    KEEP = ("event_id", "role", "title", "rules", "rules_hash", "group_id", "recorder_url", "recorder_pub", "issuer_pub", "issuer_url",
            "offer_roles", "transcript", "pending", "proposals", "peers", "contracts", "aliases", "last_action", "joined", "closed", "notice_ver", "notice_closed",
            "last_input_at", "idle_checks")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.KEEP}

    @classmethod
    def from_dict(cls, d: dict, secrets: dict) -> "EventState":
        st = cls(**{k: d[k] for k in cls.KEEP if k in d})
        st.secrets = dict(secrets)
        return st
