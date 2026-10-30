"""Public area: the one place the owner opened to their own agent. Phase 2 implements a local folder of markdown.
Documents whose name starts with the owner prefix (default "_": rules, situation) are owner-only: the agent may read
them for its own judgement but never puts them in a profile or a reply to another peer."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from ..config import Settings


@dataclass(frozen=True)
class Doc:
    name: str
    text: str
    owner_only: bool


class PublicArea(Protocol):
    def documents(self, include_owner_only: bool = False) -> list[Doc]: ...
    def lines(self, include_owner_only: bool = False) -> list[str]: ...
    def add_note(self, text: str) -> None: ...


def _clean(line: str) -> str:
    return line.strip().lstrip("-*#").strip()


class LocalFolderArea:
    def __init__(self, root: str, settings: Settings):
        self.root, self.settings = root, settings

    def documents(self, include_owner_only=False):
        if not os.path.isdir(self.root):
            return []
        out = []
        for name in sorted(os.listdir(self.root)):
            if not name.endswith(".md"):
                continue
            owner = name.startswith(self.settings.area_owner_prefix)
            if owner and not include_owner_only:
                continue
            with open(os.path.join(self.root, name), encoding="utf-8") as f:
                out.append(Doc(name, f.read(), owner))
        return out

    def lines(self, include_owner_only=False):
        return [c for d in self.documents(include_owner_only) for c in map(_clean, d.text.splitlines()) if c]

    def add_note(self, text):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, self.settings.area_notes_file), "a", encoding="utf-8") as f:
            f.write(f"- {' '.join(text.split())}\n")
