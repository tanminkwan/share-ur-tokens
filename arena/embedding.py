"""Embeddings behind one interface. HttpEmbedder talks to the bge-m3 service (POST /embed {"texts": [...]}
-> {"embeddings": [[...]], "dim": 1024, "count": n}); vectors come back normalized."""
from __future__ import annotations

from typing import Protocol

import httpx

from .config import Settings


class EmbedError(Exception):
    pass


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HttpEmbedder:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        settings.require("embed_url")
        self.settings, self._http, self.dim = settings, http, None

    async def _post(self, texts):
        url = self.settings.embed_url.rstrip("/") + "/embed"
        if self._http is not None:
            return await self._http.post(url, json={"texts": texts})
        async with httpx.AsyncClient(timeout=self.settings.embed_timeout_sec) as hc:
            return await hc.post(url, json={"texts": texts})

    async def _batch(self, texts):
        last = None
        for _ in range(self.settings.embed_retries + 1):
            try:
                r = await self._post(texts)
                r.raise_for_status()
                d = r.json()
                vecs = d["embeddings"]
                if len(vecs) != len(texts):
                    raise ValueError(f"asked {len(texts)} texts, got {len(vecs)} vectors")
                dim = d.get("dim") or (len(vecs[0]) if vecs else None)
                if self.dim is not None and dim != self.dim:
                    raise EmbedError(f"dimension changed from {self.dim} to {dim}")
                self.dim = dim
                return vecs
            except EmbedError:
                raise
            except (httpx.HTTPError, ValueError, KeyError) as e:
                last = e
        raise EmbedError(f"{type(last).__name__}: {str(last)[:120]}")

    async def embed(self, texts):
        out, n = [], self.settings.embed_batch
        for i in range(0, len(texts), n):
            out += await self._batch(texts[i:i + n])
        return out
