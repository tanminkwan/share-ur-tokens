from arena.search import BM25Searcher, Searcher, tokens


def test_r1_6_tokens_include_words_and_bigrams():
    t = tokens("원장 기록 역할")
    assert "원장" in t and "기록" in t and "원장"[0:2] in t
    assert "기록"[0:2] in t and all(len(x) >= 1 for x in t)


def test_r1_6_korean_query_ranks_related_doc_first(settings):
    s: Searcher = BM25Searcher(k1=settings.bm25_k1, b=settings.bm25_b)
    docs = ["마케팅팀 신입. 사내 SNS 채널을 운영한다.",
            "정보보안 담당. 감사 추적을 위한 기록 보관과 열람 통제를 맡아 왔다. 기록자 역할 가능.",
            "영업 베테랑. 고객 제안과 수주 협상."]
    ranked = s.rank("원장 기록 역할 기록 보관 접근 통제 감사", docs)
    assert ranked[0][0] == 1
    assert ranked[0][1] > ranked[1][1] >= ranked[2][1] >= 0


def test_r1_6_empty_docs_and_no_overlap():
    s = BM25Searcher()
    assert s.rank("x", []) == []
    r = s.rank("zzz", ["가나다", "라마바"])
    assert all(score == 0 for _, score in r) and len(r) == 2
