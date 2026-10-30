"""A peer's home folder: everything that must survive the process stopping and starting again.

    home/identity.key    the peer's key (0600): the same peer after a restart
    home/area/           the public area (unless the peer is given another address)
    home/state.json      profile version, recorders used, direct-request inbox, per-app state
    home/receipts.jsonl  recorder-signed receipts, appended (to prove entries later)
    home/events/         events the basic assistant takes part in (state + owner-only secrets)
"""
from __future__ import annotations

import json
import os

from ..config import Settings
from ..crypto import Identity
from .area import LocalFolderArea


class PeerHome:
    def __init__(self, root: str, settings: Settings):
        self.root, self.settings = root, settings
        os.makedirs(root, exist_ok=True)

    def path(self, *parts) -> str:
        return os.path.join(self.root, *parts)

    def identity(self) -> Identity:
        return Identity.load_or_create(self.path("identity.key"))

    def area(self) -> LocalFolderArea:
        os.makedirs(self.path("area"), exist_ok=True)
        return LocalFolderArea(self.path("area"), self.settings)

    def events_dir(self) -> str:
        return self.path("events")

    def load_state(self) -> dict:
        p = self.path("state.json")
        if not os.path.exists(p):
            return {}
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def save_state(self, state: dict) -> None:
        tmp = self.path("state.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path("state.json"))

    def load_receipts(self) -> list[dict]:
        p = self.path("receipts.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def append_receipt(self, item: dict) -> None:
        with open(self.path("receipts.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
