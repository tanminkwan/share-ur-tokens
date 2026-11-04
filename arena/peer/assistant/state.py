"""What the basic assistant knows about one event, and how it is saved (secrets apart, owner-only)."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

from ...crypto import canon, commit_hash, h  # noqa: F401  (commit_hash kept importable from here)




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
    timeline: list = field(default_factory=list)       # what a person watching reads: who said what, in which direction (Timeline)
    waiting_calls: dict = field(default_factory=dict)  # my calls that came back pending (A2A task id -> {url, kind, data, since})
    proposals: dict = field(default_factory=dict)    # my attest proposals: id -> {payload, sigs}
    peers: dict = field(default_factory=dict)        # pub -> url learned from messages and contracts
    contracts: list = field(default_factory=list)    # [role, contractor pub] this host has contracted (kept by code)
    applicants: list = field(default_factory=list)   # pubs whose signed join carried this event's rules hash (checked by code)
    drive: str = "auto"                              # who drives this event: auto (LLM) · suggest (LLM proposes, owner approves) · manual (owner)
    schedule: list = field(default_factory=list)     # the event's notarized schedule [{at, code, subject?, note?}] (+ intake deadline)
    instruction: str = ""                            # the owner's standing instruction for this event (pinned in the prompt)
    role_offers: dict = field(default_factory=dict)  # host: policy role not contracted yet -> pubs whose profile offers it
    sealed_view: list = field(default_factory=list)  # code-made lines on the sealed rounds I am in (sealed element)
    evaluations: dict = field(default_factory=dict)  # content hash -> verdicts recorded for it (evaluation element, host side)
    service_receipts: list = field(default_factory=list)  # signed receipts of API-providing peers I called (checked by code)
    elements: dict = field(default_factory=dict)     # the built-in elements the event switched on (name -> setting)
    policy: dict = field(default_factory=dict)       # the event's policy block (roles, allowed revealed values, ...)
    assignments: dict = field(default_factory=dict)  # subject -> parties, as recorded by the issuer on the ledger (kept by code)
    ledger_seen: int = 0                             # the last ledger seq of this event the assistant has looked at
    sent_reveals: dict = field(default_factory=dict)  # my label -> handles I sent its reveal record to (kept by code)
    reveals: dict = field(default_factory=dict)      # "author pub|label" -> a received reveal record the code checked against the ledger
    roster: list = field(default_factory=list)       # pubs seen in this event's ledger entries (shown as handles)
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
            "offer_roles", "transcript", "timeline", "pending", "waiting_calls", "proposals", "peers", "contracts", "applicants", "drive", "schedule", "instruction", "role_offers", "sealed_view", "evaluations", "service_receipts", "elements", "policy", "assignments", "ledger_seen", "sent_reveals", "reveals", "roster", "aliases", "last_action", "joined", "closed", "notice_ver", "notice_closed",
            "last_input_at", "idle_checks")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.KEEP}

    @classmethod
    def from_dict(cls, d: dict, secrets: dict) -> "EventState":
        st = cls(**{k: d[k] for k in cls.KEEP if k in d})
        st.secrets = dict(secrets)
        return st
