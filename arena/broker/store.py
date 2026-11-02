"""Where a broker keeps its board between restarts: profiles, notices (with versions and close marks), grants."""
from __future__ import annotations

import json
import os
from typing import Protocol


class BrokerStore(Protocol):
    def load(self) -> dict | None: ...
    def save(self, state: dict) -> None: ...


class MemoryBrokerStore:
    def __init__(self):
        self.state: dict | None = None

    def load(self):
        return json.loads(json.dumps(self.state)) if self.state is not None else None

    def save(self, state):
        self.state = json.loads(json.dumps(state))


class FileBrokerStore:
    """one JSON file, rewritten atomically on every change"""

    def __init__(self, path: str):
        self.path = path

    def load(self):
        if not os.path.exists(self.path):
            return None
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def save(self, state):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, self.path)
