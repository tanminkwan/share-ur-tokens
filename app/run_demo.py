"""Start every node in one process (each is a separate A2A HTTP server) and serve the dashboard.

  .venv/bin/python -m app.run_demo                      # dashboard on http://127.0.0.1:8000
  .venv/bin/python -m app.run_demo --call "공모 내용"    # headless: post a call, wait, adopt, audit, print, exit
  SUT_OFFLINE=1 ...                                      # force offline templates (no Claude calls)
"""
import argparse
import asyncio
import time

from . import llm
from .common import alias, emit, rpc, serve
from .ledger import contribution
from .nodes import build_all
from .web import build_web


async def main(args):
    c1, c2, broker, me, peers, overseer = build_all()
    for n in (c2, c1):
        await serve(n.app, n.port)
    await serve(broker.app, broker.port)
    await serve(me.app, me.port)
    for p in peers:
        await serve(p.app, p.port)
    await asyncio.gather(*(p.advertise() for p in peers))
    emit("system", "demo", f"{len(peers)}명의 피어, broker 1, 수집가 2 기동. LLM={'Claude '+llm.AGENT_MODEL if llm.live() else '오프라인 템플릿'}")
    await serve(build_web(c1, c2, broker, me, peers, overseer), args.port)
    emit("system", "demo", f"대시보드: http://127.0.0.1:{args.port}")

    if not args.call:
        await asyncio.Event().wait()
        return
    cid = await me.post_call(args.call)
    last, n = time.time(), 0
    while time.time() - last < args.quiet and time.time() - me.calls[cid]["ts"] < args.timeout:
        await asyncio.sleep(1)
        if len(me.ideas) != n:
            n, last = len(me.ideas), time.time()
    await me.agent_run(cid)
    await asyncio.sleep(1)
    print("\n=== 결과 ===")
    for k, v in me.ideas.items():
        print(f"{'★' if k in me.adopted else ' '} {alias(v['author'])}  {v['idea']['title']}")
    print("기여:", {alias(a): v for a, v in contribution(c1.col.chain).items()})
    for node in (c1, c2):
        a = await rpc(f"http://127.0.0.1:{node.port}", {"op": "audit"})
        print(f"audit {node.col.name}: {a['status']} ({a['length']}건) head={a['head'][:10]}")
    from .common import Identity
    print("권한 없는 peer의 원장 열람:", (await overseer.read(overseer.collector_urls[0], Identity()))["error"])
    snap = await overseer.snapshot()
    st = snap["stats"]
    print("절대자 통계:", {k: st[k] for k in ("entries", "by_type", "pseudonyms", "ideas", "adopted", "adoption_rate", "avg_score", "score_hist")})
    print("절대자 무결성:", snap["integrity"])
    c1.col.chain[1]["payload"]["tampered"] = True
    overseer._cache = (0, None)
    print("변조 후 절대자 무결성:", (await overseer.snapshot())["integrity"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--call")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--quiet", type=float, default=20, help="headless: stop waiting after this many idle seconds")
    ap.add_argument("--timeout", type=float, default=240)
    asyncio.run(main(ap.parse_args()))
