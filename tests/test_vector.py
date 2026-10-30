"""P3-A2: in-memory vector index with cosine similarity."""
from arena.vector import MemoryVectorIndex


def test_p3a2_upsert_search_remove_and_filter():
    ix = MemoryVectorIndex()
    ix.upsert("a", [3.0, 0.0], {"g": 1})
    ix.upsert("b", [1.0, 1.0], {"g": 2})
    ix.upsert("c", [0.0, 2.0], {"g": 1})
    hits = ix.search([1.0, 0.0], k=3)
    assert [k for k, _, _ in hits] == ["a", "b", "c"]
    assert round(hits[0][1], 6) == 1.0 and round(hits[1][1], 3) == 0.707 and hits[2][1] == 0.0
    assert [k for k, _, _ in ix.search([1.0, 0.0], k=5, where=lambda m: m["g"] == 1)] == ["a", "c"]
    assert len(ix.search([1.0, 0.0], k=1)) == 1
    ix.upsert("a", [0.0, 1.0], {"g": 1})  # replace
    assert ix.search([0.0, 1.0], k=1)[0][0] in ("a", "c") and ix.get("a")[1] == {"g": 1}
    ix.remove("b")
    ix.remove("missing")
    assert sorted(ix.keys()) == ["a", "c"] and len(ix) == 2
    assert MemoryVectorIndex().search([1.0], k=3) == []
