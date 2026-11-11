"""A public area that lives at a URL: read-only remote documents plus a local folder for notes and owner memos.
The address is one markdown document (…/x.md) or a folder with an index.json listing its documents."""
from __future__ import annotations

import time
from typing import Callable
from urllib.parse import urljoin

import httpx

from ..egress import Egress
from ..config import Settings
from .area import Doc, LocalFolderArea, _clean


class UrlArea:
    def __init__(self, url: str, settings: Settings, http: httpx.AsyncClient | None = None,
                 clock: Callable[[], float] = time.time, notes_dir: str | None = None):
        self.url, self.settings, self._http, self.clock = url, settings, http, clock
        self.egress = Egress()  # how calls leave (arena/egress.py); a peer hands its own one in
        self.notes = LocalFolderArea(notes_dir or settings.area_local_notes_dir, settings)
        self._docs: list[Doc] = []
        self._fetched_at: float | None = None
        self.last_error: str | None = None

    async def _get(self, url):
        headers = {"Authorization": f"Bearer {self.settings.area_http_token}"} if self.settings.area_http_token else {}
        if self._http is not None:
            r = await self._http.get(url, headers=headers)
        else:
            async with self.egress.client(timeout=self.settings.area_http_timeout_sec) as hc:
                r = await hc.get(url, headers=headers)
        r.raise_for_status()
        return r

    async def refresh(self) -> bool:
        """fetch again unless the cache is fresh; on failure keep the last copy and return False"""
        if self._fetched_at is not None and self.clock() - self._fetched_at < self.settings.area_cache_sec:
            return True
        try:
            if self.url.endswith(".md"):
                docs = [(self.url.rsplit("/", 1)[-1], (await self._get(self.url)).text)]
            else:
                index_url = self.url if self.url.endswith("index.json") else self.url.rstrip("/") + "/index.json"
                listing = (await self._get(index_url)).json().get("documents", [])
                docs = [(d["name"], (await self._get(urljoin(index_url, d["url"]))).text) for d in listing]
        except (httpx.HTTPError, ValueError, KeyError) as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False
        prefix = self.settings.area_owner_prefix
        self._docs = sorted((Doc(n, t, n.startswith(prefix)) for n, t in docs), key=lambda d: d.name)
        self._fetched_at, self.last_error = self.clock(), None
        return True

    def documents(self, include_owner_only=False):
        remote = [d for d in self._docs if include_owner_only or not d.owner_only]
        return remote + self.notes.documents(include_owner_only)

    def lines(self, include_owner_only=False):
        return [c for d in self.documents(include_owner_only) for c in map(_clean, d.text.splitlines()) if c]

    def add_note(self, text, doc=None):
        self.notes.add_note(text, doc)  # the remote original is never modified
