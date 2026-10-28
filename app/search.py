"""Mechanical retrieval for the broker: BM25 over character bigrams + words (works for Korean without a tokenizer).
No LLM. An embedding model can replace `rank` later without changing the broker's interface."""
import math
import re
from collections import Counter


def tokens(text: str) -> list[str]:
    text = text.lower()
    words = re.findall(r"[0-9a-z가-힣]+", text)
    grams = [w[i:i + 2] for w in words if len(w) > 1 for i in range(len(w) - 1)]
    return words + grams


def rank(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[tuple[int, float]]:
    """return [(doc_index, score)] sorted by BM25 score, highest first"""
    toks = [tokens(d) for d in docs]
    if not toks:
        return []
    avg = sum(map(len, toks)) / len(toks) or 1
    df = Counter(t for ts in toks for t in set(ts))
    n = len(toks)
    q = tokens(query)
    out = []
    for i, ts in enumerate(toks):
        tf = Counter(ts)
        s = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(ts) / avg))
        out.append((i, round(s, 3)))
    return sorted(out, key=lambda x: -x[1])
