"""Vector index behind one interface. MemoryVectorIndex: normalized vectors in a dict, cosine = dot product."""
from __future__ import annotations

import math
from typing import Callable, Protocol


class VectorIndex(Protocol):
    def upsert(self, key: str, vector: list[float], meta: dict) -> None: ...
    def remove(self, key: str) -> None: ...
    def get(self, key: str) -> tuple[list[float], dict] | None: ...
    def keys(self) -> list[str]: ...
    def search(self, vector: list[float], k: int, where: Callable[[dict], bool] | None = None) -> list[tuple[str, float, dict]]: ...


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class MemoryVectorIndex:
    def __init__(self):
        self._rows: dict[str, tuple[list[float], dict]] = {}

    def __len__(self):
        return len(self._rows)

    def upsert(self, key, vector, meta):
        self._rows[key] = (_norm(vector), meta)

    def remove(self, key):
        self._rows.pop(key, None)

    def get(self, key):
        return self._rows.get(key)

    def keys(self):
        return list(self._rows)

    def search(self, vector, k, where=None):
        q = _norm(vector)
        scored = [(key, sum(a * b for a, b in zip(q, v)), meta) for key, (v, meta) in self._rows.items() if where is None or where(meta)]
        return sorted(scored, key=lambda x: -x[1])[:k]
