"""Repeat a live acceptance scenario and judge every run on the platform's guarantees (P5-B4, redefined 2026-11-02).

A run keeps the platform's guarantees when the test process did not crash on its own (pytest exit code 0 = passed or
1 = an assertion failed; anything else is an error) and its ledger audits ok. Whether the LLM agents finished the event
is reported for reference only: it is not a platform metric (user 2026-11-02).

    .venv/bin/python -m scripts.rps_stability --runs 5 [--test tests/live/test_rps_mini.py] [--timeout 900]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def judge_run(n: int, exit_code: int, log: str, basetemp: pathlib.Path) -> dict:
    from arena.ledger import audit_chain
    files = sorted(pathlib.Path(basetemp).glob("**/genesis/ledger.jsonl"))
    if files:
        chain = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
        audit = audit_chain(chain)
        entries, closed = len(chain), any(e["type"] == "close" for e in chain)
    else:
        audit, entries, closed = "no ledger", 0, False
    m = re.search(r"elapsed ([0-9.]+)s", log)
    u = re.search(r"^usage: (\{.*\})$", log, re.M)
    usage = json.loads(u.group(1)) if u else {}
    return {"run": n, "exit": exit_code, "audit": audit, "entries": entries, "closed": closed,
            "elapsed": float(m.group(1)) if m else None, "llm_finished": exit_code == 0,
            "platform_ok": exit_code in (0, 1) and audit == "ok",
            "llm_error": "LLM judgement error: yes" in log,
            "llm_calls": usage.get("calls"), "tokens": (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)) if usage else None}


def summarize(rows: list[dict]) -> str:
    n = len(rows)
    out = [f"- 플랫폼 보장 지켜짐: {sum(r['platform_ok'] for r in rows)}/{n}",
           f"- LLM이 끝까지 해냄(참고): {sum(r['llm_finished'] for r in rows)}/{n}",
           f"- LLM 판정 오류(참고): {sum(r['llm_error'] for r in rows)}/{n}", "",
           "| 실행 | 플랫폼 보장 | 원장 감사 | 원장 항목 | 종료 | LLM 완주 | 걸린 시간(초) | pytest 종료 코드 |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['run']} | {'예' if r['platform_ok'] else '아니요'} | {r['audit']} | {r['entries']} | "
                   f"{'예' if r['closed'] else '아니요'} | {'예' if r['llm_finished'] else '아니요'} | {r['elapsed'] or '-'} | {r['exit']} |")
    return "\n".join(out)


def run_many(test: str, runs: int, timeout: int, out: pathlib.Path) -> list[dict]:
    rows = []
    out.mkdir(parents=True, exist_ok=True)
    for n in range(1, runs + 1):
        base = out / f"run{n}"
        cmd = [sys.executable, "-m", "pytest", test, "-q", "-s", "-p", "no:cacheprovider", f"--basetemp={base}"]
        try:
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
            code, log = p.returncode, p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            code, log = -1, f"timeout after {timeout}s\n{e.stdout or ''}"
        (out / f"run{n}.log").write_text(log, encoding="utf-8")
        rows.append(judge_run(n, code, log, base))
        print(f"{test} run {n}: platform_ok={rows[-1]['platform_ok']} llm_finished={rows[-1]['llm_finished']} "
              f"calls={rows[-1]['llm_calls']} tokens={rows[-1]['tokens']}", flush=True)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--test", default="tests/live/test_rps_mini.py")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per run before it is stopped")
    ap.add_argument("--out", default=None, help="folder for logs, ledgers and summary.md (default data/runs/stability-<time>)")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out or ROOT / "data" / "runs" / f"stability-{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    rows = run_many(a.test, a.runs, a.timeout, out)
    text = f"# 반복 안정성: {a.test}, {a.runs}번 ({time.strftime('%Y-%m-%d %H:%M')})\n\n" + summarize(rows) + "\n"
    (out / "summary.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if all(r["platform_ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
