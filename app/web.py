"""Dashboard (single page, polling) + control API. Runs in the same process as the demo nodes."""
import json
import time

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import llm
from .common import EVENTS, STORE, alias, emit, rpc
from .ledger import contribution

PAGE = """<!doctype html><meta charset=utf-8><title>사내 아이디어 공모 p2p+a2a</title>
<style>
body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f5f6f8;color:#1c2330}
header{background:#1c2330;color:#fff;padding:10px 16px;display:flex;gap:16px;align-items:center}
header b{font-size:16px}.tag{background:#2d6cdf;border-radius:4px;padding:1px 8px;font-size:12px}.off{background:#b26a00}
main{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px}
section{background:#fff;border:1px solid #dde1e7;border-radius:8px;padding:10px 12px;min-height:80px}
h3{margin:0 0 6px;font-size:14px}textarea{width:100%;height:64px;box-sizing:border-box}
button{background:#2d6cdf;color:#fff;border:0;border-radius:5px;padding:5px 12px;cursor:pointer;margin:2px}
button.s{background:#6b7686}button.r{background:#c0392b}
.ev{font:12px/1.4 ui-monospace,monospace;max-height:300px;overflow:auto}.ev div{border-bottom:1px solid #eef0f3;padding:2px 0}
.k-p2p{color:#0a7d4b}.k-ledger{color:#7a3db8}.k-broker{color:#b26a00}.k-award{color:#c0392b;font-weight:600}.k-assist{color:#2d6cdf}.k-review{color:#8a6d00;font-weight:600}
.idea{border:1px solid #dde1e7;border-radius:6px;padding:6px 8px;margin:6px 0}.idea.ad{border-color:#c0392b;background:#fff6f5}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid #eef0f3;padding:2px 4px;text-align:left}
.wide{grid-column:1/3}.mono{font-family:ui-monospace,monospace}
</style>
<header><b>사내 아이디어 공모 · p2p + a2a</b><span id=mode class=tag></span><span id=cnt></span></header>
<main>
<section class=wide><h3>① 아이디어 공모 올리기 (요청자 = 나)</h3>
<textarea id=text>신입 사원이 입사 첫 달에 회사에 빨리 적응하도록 돕는 아이디어를 모집합니다.</textarea>
<button onclick="post('/api/call',{text:text.value})">공모 올리기</button>
<button class=s onclick="post('/api/close',{})">마감하고 AI 비서에게 맡기기</button>
<span id=sheet></span></section>
<section><h3>② 진행 로그</h3><div class=ev id=ev></div></section>
<section><h3>③ 도착한 아이디어 (p2p 직접 전달)</h3><div id=ideas></div></section>
<section><h3>④ 증명 원장 (collector-1, 내용 없이 해시·가명·서명)</h3><div id=ledger style="max-height:260px;overflow:auto"></div></section>
<section><h3>⑤ 기여 집계 · 감사</h3><div id=contrib></div><hr>
<button onclick="audit()">감사: 두 수집가 검증</button>
<button class=r onclick="tamper()">원장 변조 시연</button>
<div id=auditout class=mono></div><hr>
<input id=reason placeholder="재식별 사유" size=20><button class=s onclick="reid()">감사 담당 재식별</button>
<div id=reidout></div></section>
</main>
<script>
const $=id=>document.getElementById(id);
async function post(u,b){await fetch(u,{method:'POST',body:JSON.stringify(b)});}
async function audit(){const r=await (await fetch('/api/audit')).json();$('auditout').innerHTML=r.map(x=>x.name+': '+x.status+' ('+x.length+'건)').join('<br>')+(r[0].head==r[1].head?'<br>두 수집가의 head 일치':'<br><b>head 불일치</b>')}
async function tamper(){await post('/api/tamper',{});audit()}
async function reid(){const r=await (await fetch('/api/reidentify?reason='+encodeURIComponent($('reason').value))).json();$('reidout').innerHTML=r.error?r.error:r.map(x=>x.alias+' = '+x.name).join('<br>')}
async function tick(){const s=await (await fetch('/api/state')).json();
$('mode').textContent=s.live?'Claude 연결: '+s.model:'오프라인(템플릿)';$('mode').className='tag'+(s.live?'':' off');
$('cnt').textContent='피어 '+s.peers+'명 · 아이디어 '+s.ideas.length+'건 · 원장 '+s.ledger.length+'건';
$('ev').innerHTML=s.events.map(e=>`<div class=k-${e.kind}>${new Date(e.ts*1000).toLocaleTimeString()} [${e.kind}] ${e.actor}: ${e.text}</div>`).join('');$('ev').scrollTop=1e9;
$('sheet').innerHTML=s.sheet.length?' 전달된 피어 '+s.sheet.length+'명 (broker 답변지)':'';
$('ideas').innerHTML=s.ideas.map(i=>`<div class="idea ${i.adopted?'ad':''}"><b>${i.title}</b> <span class=mono>${i.author}</span>${i.adopted?' ★채택':''}${i.review?` <span class=tag>심사 ${i.review.score}점</span>`:''}<br>${i.idea}<br><small>첫 단계: ${i.first_step} / 위험: ${i.risk}</small>${i.review?'<br><small>심사 의견('+i.review.judge+'): '+i.review.comment+'</small>':''}${i.adopted?'<br><small>채택 이유: '+i.reason+'</small>':`<br><button class=s onclick="post('/api/adopt',{h:'${i.hash}'})">채택</button>`}</div>`).join('')||'아직 없음';
$('ledger').innerHTML='<table><tr><th>#<th>종류<th>가명<th>해시</tr>'+s.ledger.map(l=>`<tr><td>${l.seq}<td>${l.type}<td class=mono>${l.who}<td class=mono>${l.hash}`).join('')+'</table>';
$('contrib').innerHTML='<table><tr><th>가명<th>받은 사람 수<th>채택</tr>'+s.contrib.map(c=>`<tr><td class=mono>${c.who}<td>${c.received_by}<td>${c.adopted}`).join('')+'</table>'}
setInterval(tick,1500);tick();
</script>"""


def build_web(c1, c2, broker, me, peers):
    reid_log = []
    names = {p.id.pub: p.p["name"] for p in peers}

    def last_call():
        return list(me.calls.items())[-1] if me.calls else (None, None)

    async def state(_):
        cid, call = last_call()
        ideas = [dict(hash=k, author=alias(v["author"]), title=v["idea"]["title"], idea=v["idea"]["idea"], first_step=v["idea"]["first_step"],
                      risk=v["idea"]["risk"], adopted=k in me.adopted, reason=v.get("reason", ""),
                      review=me.reviews.get(k))
                 for k, v in me.ideas.items() if v["call_id"] == cid]
        ledger = [dict(seq=e["seq"], type=e["type"], hash=e["hash"][:10],
                       who=alias(e["payload"].get("author") or e["payload"].get("provider") or e["payload"].get("evaluator")))
                  for e in c1.col.chain]
        contrib = [dict(who=alias(a), **v) for a, v in contribution(c1.col.chain).items()]
        return JSONResponse(dict(live=llm.live(), model=llm.AGENT_MODEL, peers=len(broker.ads), ideas=ideas, ledger=ledger, contrib=contrib,
                                 sheet=(call or {}).get("sheet", []), events=EVENTS[-120:]))

    async def body(r):
        raw = await r.body()
        return json.loads(raw or b"{}")

    async def post_call(r):
        import asyncio
        text = (await body(r))["text"]
        asyncio.create_task(me.post_call(text))
        return JSONResponse({"ok": True})

    async def close(r):
        import asyncio
        cid, _ = last_call()
        if cid:
            asyncio.create_task(me.agent_run(cid))
        return JSONResponse({"ok": True})

    async def adopt(r):
        return JSONResponse({"ok": await me.adopt((await body(r))["h"])})

    async def audit(_):
        out = []
        for n in (c1, c2):
            res = await rpc(f"http://127.0.0.1:{n.port}", {"op": "audit"})
            out.append(dict(name=n.col.name, status=res["status"], head=res["head"], length=res["length"]))
        return JSONResponse(out)

    async def tamper(_):
        if c1.col.chain:
            c1.col.chain[min(1, len(c1.col.chain) - 1)]["payload"]["tampered"] = True  # admin edits history on collector-1 only
            emit("ledger", "시연", "collector-1의 과거 항목을 몰래 수정했습니다")
        return JSONResponse({"ok": True})

    async def reidentify(r):
        reason = r.query_params.get("reason", "").strip()
        if not reason:
            return JSONResponse({"error": "사유를 입력해야 재식별할 수 있습니다"})
        reid_log.append({"ts": time.time(), "reason": reason})
        emit("audit", "감사 담당", f"재식별 수행(사유: {reason}) - 접근 기록 {len(reid_log)}건")
        return JSONResponse([dict(alias=alias(k), name=v) for k, v in names.items() if any(i["author"] == k for i in me.ideas.values())])

    return Starlette(routes=[
        Route("/", lambda r: HTMLResponse(PAGE)), Route("/api/state", state),
        Route("/api/call", post_call, methods=["POST"]), Route("/api/close", close, methods=["POST"]),
        Route("/api/adopt", adopt, methods=["POST"]), Route("/api/audit", audit),
        Route("/api/tamper", tamper, methods=["POST"]), Route("/api/reidentify", reidentify)])
