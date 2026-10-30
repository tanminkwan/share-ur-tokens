"""Public area: the one place the owner opened to their own agent. Phase 2 implements a local folder of markdown.
Documents whose name starts with the owner prefix (default "_": rules, situation) are owner-only: the agent may read
them for its own judgement but never puts them in a profile or a reply to another peer."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlparse

from ..config import Settings


@dataclass(frozen=True)
class Doc:
    name: str
    text: str
    owner_only: bool


class PublicArea(Protocol):
    async def refresh(self) -> bool: ...
    def documents(self, include_owner_only: bool = False) -> list[Doc]: ...
    def lines(self, include_owner_only: bool = False) -> list[str]: ...
    def add_note(self, text: str, doc: str | None = None) -> None: ...


def _clean(line: str) -> str:
    return line.strip().lstrip("-*#").strip()


class LocalFolderArea:
    def __init__(self, root: str, settings: Settings):
        self.root, self.settings = root, settings

    async def refresh(self):
        return True  # the folder is read on every call

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

    def add_note(self, text, doc=None):
        """append one line; doc defaults to the public notes file (pass an owner-only name for private memos)"""
        name = doc or self.settings.area_notes_file
        if os.path.basename(name) != name or not name.endswith(".md"):
            raise ValueError(f"bad document name: {name!r}")
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, name), "a", encoding="utf-8") as f:
            f.write(f"- {' '.join(text.split())}\n")


# ---------------- opening a public area by address ----------------
_FACTORIES: dict[str, Callable[..., PublicArea]] = {}


def register_area(scheme: str, factory: Callable[..., PublicArea]) -> None:
    """add a storage kind (e.g. a cloud bucket) without touching the platform: factory(address, settings, **kw)"""
    _FACTORIES[scheme] = factory


def open_area(address: str, settings: Settings, **kw) -> PublicArea:
    scheme = urlparse(address).scheme
    if scheme not in _FACTORIES:
        raise ValueError(f"unknown public area address: {address!r} (known: {', '.join(sorted(s or 'path' for s in _FACTORIES))})")
    return _FACTORIES[scheme](address, settings, **kw)


def _local(address, settings, **kw):
    return LocalFolderArea(urlparse(address).path if address.startswith("file://") else address, settings)


def _url(address, settings, **kw):
    from .url_area import UrlArea
    return UrlArea(address, settings, **kw)


for _s in ("", "file"):
    register_area(_s, _local)
for _s in ("http", "https"):
    register_area(_s, _url)
