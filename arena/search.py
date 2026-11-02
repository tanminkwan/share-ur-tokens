"""Mechanical retrieval: BM25 over words + character bigrams (works for Korean without a tokenizer). No LLM.
`Searcher` is the interface the broker depends on; an embedding searcher can replace BM25Searcher."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

_WORD = re.compile(r"[0-9a-z가-힣]+")


def tokens(text: str) -> list[str]:
    words = _WORD.findall(text.lower())
    grams = [w[i:i + 2] for w in words if len(w) > 1 for i in range(len(w) - 1)]
    return words + grams


class Searcher(Protocol):
    def rank(self, query: str, docs: list[str]) -> list[tuple[int, float]]:
        """[(doc_index, score)] best first; one tuple per doc"""


class BM25Searcher:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b

    def rank(self, query: str, docs: list[str]) -> list[tuple[int, float]]:
        toks = [tokens(d) for d in docs]
        if not toks:
            return []
        avg = sum(map(len, toks)) / len(toks) or 1
        df = Counter(t for ts in toks for t in set(ts))
        n, q, out = len(toks), tokens(query), []
        for i, ts in enumerate(toks):
            tf, s = Counter(ts), 0.0
            for t in q:
                if t in tf:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * len(ts) / avg))
            out.append((i, round(s, 3)))
        return sorted(out, key=lambda x: -x[1])
