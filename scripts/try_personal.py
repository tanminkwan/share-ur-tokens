"""Bring up a small local world to try the sample personal peer by hand (no app, no demo: the platform's own programs).

    .venv/bin/python -m scripts.try_personal                 # genesis + two human peers (no LLM): 사람 모드 창구 화면
    .venv/bin/python -m scripts.try_personal --agent         # + one agent peer with the chat window (uses ARENA_LLM_* in .env)
    .venv/bin/python -m scripts.try_personal --peers human-a,agent   # choose the peers: human-a, human-b, agent (default: human-a,human-b)
    .venv/bin/python -m scripts.try_personal --web-host 0.0.0.0   # open the windows to other machines (default 127.0.0.1)

The god's observer window (a screen that refreshes itself) opens at base-port + 4 (default 9304).
Everything lives under --dir (default data/try). Ctrl-C stops all. The windows' addresses (with their token) are printed."""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = sys.executable


def spawn(module: str, env: dict, log: pathlib.Path) -> subprocess.Popen:
    f = open(log, "w", encoding="utf-8")
    return subprocess.Popen([PY, "-m", module], cwd=ROOT, env={**os.environ, **env}, stdout=f, stderr=subprocess.STDOUT)


def wait_up(url: str, seconds: float = 60) -> None:
    t = time.time()
    while time.time() - t < seconds:
        try:
            httpx.get(url, timeout=2)
            return
        except httpx.HTTPError:
            time.sleep(0.5)
    raise SystemExit(f"{url} did not come up (see the logs)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="data/try")
    ap.add_argument("--agent", action="store_true", help="also start an agent peer with the chat window (needs ARENA_LLM_* in .env)")
    ap.add_argument("--peers", default="human-a,human-b", help="comma list from human-a, human-b, agent (agent needs ARENA_LLM_* in .env)")
    ap.add_argument("--web-host", default="127.0.0.1")
    ap.add_argument("--fresh", action="store_true", help="start from an empty world")
    ap.add_argument("--base-port", type=int, default=9300)
    a = ap.parse_args(argv)
    b = a.base_port
    known = {"human-a": ("human-a", "human", "none", b + 10), "human-b": ("human-b", "human", "none", b + 20), "agent": ("agent", "agent", None, b + 30)}
    names = [n.strip() for n in a.peers.split(",") if n.strip()] + (["agent"] if a.agent else [])
    bad = [n for n in names if n not in known]
    if bad or not names:
        raise SystemExit(f"--peers: choose from {', '.join(known)} (got {bad or 'none'})")
    peers = [known[n] for n in dict.fromkeys(names)]  # fixed ports per name, so a peer keeps its ports whichever others run
    d = ROOT / a.dir
    if a.fresh and d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    gen = {"ARENA_GENESIS_DIR": str(d / "genesis"), "ARENA_GENESIS_BROKER_PORT": str(b), "ARENA_GENESIS_RECORDER_PORT": str(b + 1),
           "ARENA_GENESIS_RECORDER_API_PORT": str(b + 2), "ARENA_GENESIS_GOD_PORT": str(b + 3), "ARENA_RECORDER_REQUIRE_GROUP": "true",
           "ARENA_GENESIS_GOD_WEB_PORT": str(b + 4), "ARENA_GENESIS_GOD_WEB_HOST": a.web_host}  # the observer window: base + 4
    procs = [spawn("arena.genesis", gen, d / "genesis.log")]
    wait_up(f"http://127.0.0.1:{b + 3}/.well-known/agent-card.json")
    for name, mode, llm, port in peers:
        env = {"ARENA_PERSONAL_MODE": mode, "ARENA_PERSONAL_PEER_HOME": str(d / name), "ARENA_PERSONAL_PEER_PORT": str(port),
               "ARENA_PERSONAL_DESK_PORT": str(port + 1), "ARENA_PERSONAL_CHAT_PORT": str(port + 2), "ARENA_PERSONAL_CONSOLE_PORT": str(port + 3),
               "ARENA_PERSONAL_WEB_HOST": a.web_host,
               "ARENA_PERSONAL_PEER_BROKERS": f"public=http://127.0.0.1:{b}", "ARENA_PERSONAL_PEER_LABELS": f"이름:{name}"}
        if llm:
            env["ARENA_LLM_BACKEND"] = llm
        procs.append(spawn("arena.peers.personal", env, d / f"{name}.log"))
    time.sleep(1)
    host = a.web_host if a.web_host != "0.0.0.0" else "<이 기계의 주소>"
    print("에이전트 아레나 시험 세계가 떴다. 화면:", flush=True)
    for name, mode, _, port in peers:
        tok = None
        for _ in range(60):
            p = d / name / "web-token"
            if p.exists():
                tok = p.read_text().strip()
                break
            time.sleep(0.5)
        print(f"  {name:8} ({mode}) 콘솔: http://{host}:{port + 3}/#token={tok}", flush=True)  # the integrated window, both modes
    tok = None
    for _ in range(60):  # the observer window (the god's screen, refreshes itself)
        p = d / "genesis" / "homes" / "god" / "web-token"
        if p.exists():
            tok = p.read_text().strip()
            break
        time.sleep(0.5)
    print(f"  {'god':8} (관전)  관전 창: http://{host}:{b + 4}/#token={tok}", flush=True)
    print(f"기록: {d}/*.log   멈추기: Ctrl-C", flush=True)
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
