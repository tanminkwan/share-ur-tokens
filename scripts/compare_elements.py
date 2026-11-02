"""Compare the same event without and with built-in elements (P6-V3): platform guarantees, completion, time, LLM calls
and tokens, each scenario run N times. The default pair is the two-peer one-round game: natural-language rules only
(tests/live/test_rps_mini.py) against sealed rounds + a judging API peer (tests/live/test_rps_mini_elements.py).

    .venv/bin/python -m scripts.compare_elements --runs 5
"""
from __future__ import annotations

import argparse
import pathlib
import statistics
import sys
import time

from scripts.rps_stability import ROOT, run_many

PAIRS = {"rps-mini": ("tests/live/test_rps_mini.py", "tests/live/test_rps_mini_elements.py")}


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 1) if xs else "-"


def compare_table(without: list[dict], with_: list[dict]) -> str:
    def row(name, rows):
        n = len(rows)
        return (f"| {name} | {sum(r['platform_ok'] for r in rows)}/{n} | {sum(r['llm_finished'] for r in rows)}/{n} | "
                f"{sum(r['llm_error'] for r in rows)}/{n} | {_avg([r['elapsed'] for r in rows])} | {_avg([r['llm_calls'] for r in rows])} | "
                f"{_avg([r['tokens'] for r in rows])} |")
    return "\n".join(["| 방식 | 플랫폼 보장 | 끝까지 감 | LLM 판정 오류 | 평균 시간(초) | 평균 LLM 호출 | 평균 토큰 |",
                      "|---|---|---|---|---|---|---|", row("요소 없이(자연어 규칙만)", without), row("요소를 켜고", with_)])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pair", default="rps-mini", choices=sorted(PAIRS))
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out or ROOT / "data" / "runs" / f"compare-{a.pair}-{time.strftime('%Y%m%d-%H%M%S')}")
    without_test, with_test = PAIRS[a.pair]
    without = run_many(without_test, a.runs, a.timeout, out / "without")
    with_ = run_many(with_test, a.runs, a.timeout, out / "with")
    text = f"# 요소 있을 때와 없을 때: {a.pair}, 각 {a.runs}번 ({time.strftime('%Y-%m-%d %H:%M')})\n\n" + compare_table(without, with_) + "\n"
    (out / "summary.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if all(r["platform_ok"] for r in without + with_) else 1


if __name__ == "__main__":
    sys.exit(main())
