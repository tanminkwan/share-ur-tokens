"""Events a peer takes part in, kept locally so the basic assistant can continue after a restart.
State goes to state.json; committed values and their secret salts go to an owner-only _secrets.json (mode 0600)."""
from __future__ import annotations

import json
import os
from typing import Protocol


class EventStore(Protocol):
    def save(self, event_id: str, state: dict, secrets: dict) -> None: ...
    def load_all(self) -> list[tuple[dict, dict]]: ...


class MemoryEventStore:
    def __init__(self):
        self.rows: dict[str, tuple[dict, dict]] = {}

    def save(self, event_id, state, secrets):
        self.rows[event_id] = (json.loads(json.dumps(state)), json.loads(json.dumps(secrets)))

    def load_all(self):
        return list(self.rows.values())


class FolderEventStore:
    def __init__(self, root: str):
        self.root = root

    def _write(self, path, obj, private=False):
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        if private:
            os.chmod(path, 0o600)

    def save(self, event_id, state, secrets):
        d = os.path.join(self.root, event_id)
        os.makedirs(d, exist_ok=True)
        self._write(os.path.join(d, "state.json"), state)
        self._write(os.path.join(d, "_secrets.json"), secrets, private=True)

    def load_all(self):
        if not os.path.isdir(self.root):
            return []
        out = []
        for ev in sorted(os.listdir(self.root)):
            sp = os.path.join(self.root, ev, "state.json")
            if not os.path.exists(sp):
                continue
            with open(sp, encoding="utf-8") as f:
                state = json.load(f)
            secp = os.path.join(self.root, ev, "_secrets.json")
            secrets = json.load(open(secp, encoding="utf-8")) if os.path.exists(secp) else {}
            out.append((state, secrets))
        return out
