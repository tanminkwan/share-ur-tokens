"""Where a link peer keeps its links (one job): every signed version of every link, newest last. SQLite, so a link
peer holding many links stays quick and a crash does not lose what was written. The role depends on LinkStore only."""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Protocol


class LinkStore(Protocol):
    def versions(self, link_id: str) -> list[dict]: ...
    def append(self, rec: dict, keep: int) -> None: ...
    def count(self) -> int: ...


class SqliteLinkStore:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS versions (id TEXT NOT NULL, ver INTEGER NOT NULL, rec TEXT NOT NULL, PRIMARY KEY (id, ver))")
        self.db.commit()

    def versions(self, link_id: str) -> list[dict]:
        rows = self.db.execute("SELECT rec FROM versions WHERE id = ? ORDER BY ver", (link_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def append(self, rec: dict, keep: int) -> None:
        with self.db:
            self.db.execute("INSERT INTO versions (id, ver, rec) VALUES (?, ?, ?)", (rec["id"], rec["ver"], json.dumps(rec, ensure_ascii=False)))
            self.db.execute("DELETE FROM versions WHERE id = ? AND ver <= ?", (rec["id"], rec["ver"] - keep))

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(DISTINCT id) FROM versions").fetchone()[0]


class MemoryLinkStore:
    """the same, in memory (tests)"""

    def __init__(self):
        self.links: dict[str, list[dict]] = {}

    def versions(self, link_id: str) -> list[dict]:
        return list(self.links.get(link_id, []))

    def append(self, rec: dict, keep: int) -> None:
        self.links[rec["id"]] = (self.links.get(rec["id"], []) + [dict(rec)])[-keep:]

    def count(self) -> int:
        return len(self.links)
