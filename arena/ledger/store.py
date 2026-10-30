"""Where a recorder keeps its chain."""
from __future__ import annotations

import json
import os
from typing import Protocol


class LedgerStore(Protocol):
    def load(self) -> list[dict]: ...
    def append(self, entry: dict) -> None: ...


class MemoryStore:
    def __init__(self):
        self.rows: list[dict] = []

    def load(self) -> list[dict]:
        return list(self.rows)

    def append(self, entry: dict) -> None:
        self.rows.append(entry)


class JsonlStore:
    """one entry per line, append-only"""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def append(self, entry: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
