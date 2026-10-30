"""CollectorService: a Ledger plus who may read it in full, and a log of read attempts. No HTTP here."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Callable, Iterable

from ..config import Settings
from ..crypto import Identity, pen_name, verify
from ..ledger import JsonlStore, Ledger, LedgerStore


class CollectorService:
    def __init__(self, settings: Settings, ledger: Ledger, readers: Iterable[str], clock: Callable[[], float] = time.time):
        self.settings, self.ledger, self.clock = settings, ledger, clock
        self.identity = ledger.identity
        self.readers = set(readers)
        self.access_log: deque = deque(maxlen=settings.access_log_size)
        self._lock = asyncio.Lock()

    @classmethod
    def build(cls, settings: Settings, identity: Identity, store: LedgerStore, readers: Iterable[str] | None = None,
              clock: Callable[[], float] = time.time) -> "CollectorService":
        ledger = Ledger(identity, store, settings, clock=clock)
        return cls(settings, ledger, settings.collector_readers if readers is None else readers, clock=clock)

    @classmethod
    def from_settings(cls, settings: Settings) -> "CollectorService":
        identity = Identity.load_or_create(settings.collector_key_file)
        return cls.build(settings, identity, JsonlStore(settings.collector_ledger_file))

    async def record(self, kind: str, payload: dict, sigs: dict) -> dict:
        async with self._lock:
            entry, err = self.ledger.propose(kind, payload, sigs)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "seq": entry["seq"], "hash": entry["hash"], "seal": entry["seal"]}

    def verify(self, hash_: str) -> dict:
        """public: does an entry with this hash exist and is it sealed by me; contract metadata only"""
        e = self.ledger.find(hash_)
        p = e["payload"] if e else {}
        is_contract = bool(e and e["type"] == "contract")
        return {"ok": True, "exists": bool(e), "type": e["type"] if e else None,
                "seal_ok": bool(e and verify(e["seal"]["pub"], e["hash"], e["seal"]["sig"])),
                "role": p.get("role") if is_contract else None, "call_id": p.get("call_id") if is_contract else None,
                "issuer": p.get("issuer") if is_contract else None,
                "contractor": p.get("contractor") if is_contract and p.get("role") == "record" else None}

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
        return {"ok": True, "name": s.collector_name, "pub": self.identity.pub,
                "pen_name": pen_name(self.identity.pub, s.pen_name_prefix, s.pen_name_len),
                "length": len(self.ledger.chain), "head": self.ledger.head()}
