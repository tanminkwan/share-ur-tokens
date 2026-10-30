"""RecorderService: a Ledger plus who may read it in full, and a log of read attempts. No HTTP here."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Callable, Iterable

from ..config import Settings
from ..crypto import Identity, pen_name, verify
from ..ledger import JsonlStore, Ledger, LedgerStore, contribution, events


class RecorderService:
    def __init__(self, settings: Settings, ledger: Ledger, readers: Iterable[str], clock: Callable[[], float] = time.time):
        self.settings, self.ledger, self.clock = settings, ledger, clock
        self.identity = ledger.identity
        self.readers = set(readers)
        self.access_log: deque = deque(maxlen=settings.access_log_size)
        self._lock = asyncio.Lock()

    @classmethod
    def build(cls, settings: Settings, identity: Identity, store: LedgerStore, readers: Iterable[str] | None = None,
              clock: Callable[[], float] = time.time) -> "RecorderService":
        ledger = Ledger(identity, store, settings, clock=clock)
        return cls(settings, ledger, settings.recorder_readers if readers is None else readers, clock=clock)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RecorderService":
        identity = Identity.load_or_create(settings.recorder_key_file)
        return cls.build(settings, identity, JsonlStore(settings.recorder_ledger_file))

    async def record(self, kind: str, payload: dict, sigs: dict) -> dict:
        async with self._lock:
            entry, err = self.ledger.propose(kind, payload, sigs)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "seq": entry["seq"], "hash": entry["hash"], "seal": entry["seal"]}

    def verify(self, hash_: str) -> dict:
        """public: does an entry with this hash exist, is it sealed by me, and its public metadata only.
        A contractor is shown unless the event's policy hides that role."""
        e = self.ledger.find(hash_)
        if not e:
            return {"ok": True, "exists": False, "type": None, "seal_ok": False, "event_id": None}
        p = e["payload"]
        out = {"ok": True, "exists": True, "type": e["type"], "seal_ok": verify(e["seal"]["pub"], e["hash"], e["seal"]["sig"]),
               "event_id": p.get("event_id")}
        if e["type"] == "event":
            out.update(issuer=p["issuer"], kind=p.get("kind"), approvers=list(p.get("approvers", [])))
        elif e["type"] == "contract":
            hidden = events(self.ledger.chain).get(p["event_id"], {}).get("policy", {}).get("hidden_roles", [])
            out.update(role=p["role"], issuer=p["issuer"], contractor=None if p["role"] in hidden else p["contractor"])
        return out

    def track(self, pub: str) -> dict:
        """public track record of one key: counts only, no counterparties, no content hashes"""
        if not self.settings.recorder_public_track:
            return {"ok": False, "error": "track records are not public on this recorder"}
        empty = {"published": 0, "received_by": 0, "verdicts_received": {}, "verdicts_given": {}, "roles": {}, "events": 0, "approvals": 0}
        return {"ok": True, "pub": pub, "track": contribution(self.ledger.chain).get(pub, empty)}

    def audit(self) -> dict:
        return {"ok": True, "status": self.ledger.audit(), "length": len(self.ledger.chain), "head": self.ledger.head()}

    def _allowed(self, reader_pub: str) -> bool:
        granted = reader_pub in self.readers
        self.access_log.append({"ts": self.clock(), "reader": reader_pub, "granted": granted})
        return granted

    def read_chain(self, reader_pub: str) -> dict:
        if not self._allowed(reader_pub):
            return {"ok": False, "error": "not authorized"}
        return {"ok": True, "chain": self.ledger.chain}

    def read_access_log(self, reader_pub: str) -> dict:
        if reader_pub not in self.readers:
            return {"ok": False, "error": "not authorized"}
        return {"ok": True, "log": list(self.access_log)}

    def health(self) -> dict:
        s = self.settings
        return {"ok": True, "name": s.recorder_name, "pub": self.identity.pub,
                "pen_name": pen_name(self.identity.pub, s.pen_name_prefix, s.pen_name_len),
                "length": len(self.ledger.chain), "head": self.ledger.head()}
