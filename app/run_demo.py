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
from .nodes import build_all
from .web import build_web


async def main(args):
    brokers, me, peers, overseer, review_members = build_all()
    for b in brokers:
        await serve(b.app, b.port)
    await serve(me.app, me.port)
    for p in peers:
        await serve(p.app, p.port)
    for m in review_members:  # the review group's owner (event peer) grants time-limited membership
        g = {"pub": m.id.pub, "until": time.time() + 86400}
        await rpc(me.review_broker_url, {"op": "grant", "grant": g, "sig": me.id.sign(g)})
    await asyncio.gather(*(p.advertise() for p in peers))
    from .common import Identity
    outsider, ts = Identity(), time.time()
    res = await rpc(me.review_broker_url, {"op": "find", "text": "심사", "pub": outsider.pub, "ts": ts, "sig": outsider.sign({"op": "find", "ts": ts})})
    emit("system", "demo", f"응모 그룹 쪽 peer가 심사 그룹 broker를 조회해 보면: {res.get('error') or '조회됨(문제)'}")
    for p in peers:  # every peer looks at the board on its own; the recommender peer also recommends
        asyncio.create_task(p.watch())
    emit("system", "demo", f"{len(peers)}명의 피어, peer 그룹 2개(응모 그룹: broker A·B·C 공지 공유, 심사 그룹: broker D) 기동. "
         + ", ".join(f"{b.name}: 기본 peer {len(b.ads)}명" for b in brokers) + f". LLM={llm.describe()}")
    await serve(build_web(brokers, me, peers, overseer), args.port)
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
    recorder = next(p for p in peers if "record" in p.can)
    a = await rpc(recorder.url, {"op": "audit"})
    print(f"audit 기록자 {alias(recorder.id.pub)}: {a['status']} ({a['length']}건) head={a['head'][:10]}")
    from .common import Identity
    await overseer.locate()
    print("권한 없는 peer의 원장 열람:", (await overseer.read(recorder.url, Identity()))["error"])
    snap = await overseer.snapshot()
    st = snap["stats"]
    print("절대자 통계:", {k: st[k] for k in ("entries", "by_type", "pseudonyms", "ideas", "adopted", "adoption_rate", "avg_score", "score_hist")})
    print("기여:", [(c["who"], c["received_by"], c["adopted"], c["roles"]) for c in st["contribution"]])
    print("절대자 무결성:", snap["integrity"])
    recorder.ledger.chain[1]["payload"]["tampered"] = True
    overseer._cache = (0, None)
    print("변조 후 절대자 무결성:", (await overseer.snapshot())["integrity"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--call")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--quiet", type=float, default=20, help="headless: stop waiting after this many idle seconds")
    ap.add_argument("--timeout", type=float, default=240)
    asyncio.run(main(ap.parse_args()))
