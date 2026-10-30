"""RecorderService: a Ledger plus who may read it in full, and a log of read attempts. No HTTP here."""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from typing import Callable, Iterable

from ..config import Settings
from ..crypto import Identity, pen_name, verify
from ..ledger import JsonlStore, Ledger, LedgerStore, contribution, empty_record, public_view


class RecorderService:
    def __init__(self, settings: Settings, ledger: Ledger, readers: Iterable[str], clock: Callable[[], float] = time.time,
                 access_log_path: str | None = None):
        self.settings, self.ledger, self.clock = settings, ledger, clock
        self.identity = ledger.identity
        self.readers = set(readers)
        self.access_log: deque = deque(maxlen=settings.access_log_size)
        self.access_log_path = access_log_path  # appended file: who tried to read the whole ledger, kept across restarts
        if access_log_path and os.path.exists(access_log_path):
            with open(access_log_path, encoding="utf-8") as f:
                self.access_log.extend(json.loads(line) for line in f if line.strip())
        self._lock = asyncio.Lock()

    @classmethod
    def build(cls, settings: Settings, identity: Identity, store: LedgerStore, readers: Iterable[str] | None = None,
              clock: Callable[[], float] = time.time, access_log_path: str | None = None) -> "RecorderService":
        ledger = Ledger(identity, store, settings, clock=clock)
        return cls(settings, ledger, settings.recorder_readers if readers is None else readers, clock=clock, access_log_path=access_log_path)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RecorderService":
        identity = Identity.load_or_create(settings.recorder_key_file)
        return cls.build(settings, identity, JsonlStore(settings.recorder_ledger_file), access_log_path=settings.recorder_access_log_file)

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
            return {"ok": True, "exists": False, "type": None, "seal_ok": False, "event_id": None, "group_id": None}
        p = e["payload"]
        out = {"ok": True, "exists": True, "type": e["type"], "seal_ok": verify(e["seal"]["pub"], e["hash"], e["seal"]["sig"]),
               "event_id": p.get("event_id"), "group_id": p.get("group_id")}
        out.update(public_view(e, self.ledger.chain))  # each entry type decides what may be shown
        return out

    def track(self, pub: str) -> dict:
        """public track record of one key: counts only, no counterparties, no content hashes"""
        if not self.settings.recorder_public_track:
            return {"ok": False, "error": "track records are not public on this recorder"}
        empty = {k: (len(v) if isinstance(v, set) else dict(v) if isinstance(v, dict) else v) for k, v in empty_record().items()}
        return {"ok": True, "pub": pub, "track": contribution(self.ledger.chain).get(pub, empty)}

    def audit(self) -> dict:
        return {"ok": True, "status": self.ledger.audit(), "length": len(self.ledger.chain), "head": self.ledger.head()}

    def _allowed(self, reader_pub: str) -> bool:
        granted = reader_pub in self.readers
        row = {"ts": self.clock(), "reader": reader_pub, "granted": granted}
        self.access_log.append(row)
        if self.access_log_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.access_log_path)), exist_ok=True)
            with open(self.access_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
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
