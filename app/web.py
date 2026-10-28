"""Dashboard (single page, polling) + control API. Runs in the same process as the demo nodes."""
import json
import time

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import llm
from .common import EVENTS, STORE, alias, emit, rpc

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
.k-p2p{color:#0a7d4b}.k-ledger{color:#7a3db8}.k-broker{color:#b26a00}.k-award{color:#c0392b;font-weight:600}.k-assist{color:#2d6cdf}.k-profile{color:#0a7d4b}.k-overseer{color:#c0392b;font-weight:600}.k-review{color:#8a6d00;font-weight:600}
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
<section><h3>④ 증명 원장 <small>(기록자 역할 peer가 보관 · 내용 없이 해시·가명·서명 · 설계상 분산, 시연은 기록자 1명)</small></h3><div id=ledger style="max-height:260px;overflow:auto"></div></section>
<section class=wide><h3>⑤ 절대자 peer의 통계 <small id=ovr></small> <small>(원장 열람 권한을 가진 읽기 전용 peer. 내용·실명은 못 봄)</small></h3><div id=stats></div></section>
<section class=wide><h3>⑥ 피어의 자기소개 <small>(각 peer의 작업 영역을 비서가 자동 요약해 게시하고, 경험이 쌓이면 스스로 갱신. 사람이 편집할 수도 있으나 시연은 자동)</small></h3><div id=profiles style="max-height:220px;overflow:auto"></div></section>
<section><h3>⑦ 감사 · 접근 통제</h3><div id=contrib></div><hr>
<button onclick="audit()">감사: 기록자 원장 검증</button>
<button class=s onclick="intr()">권한 없는 peer의 열람 시도</button><div id=introut></div>
<button class=r onclick="tamper()">원장 변조 시연</button>
<div id=auditout class=mono></div><hr>
<input id=reason placeholder="실명 확인 사유" size=20><button class=s onclick="reid()">감사 담당 실명 확인</button>
<div id=reidout></div></section>
</main>
<script>
const $=id=>document.getElementById(id);
async function post(u,b){await fetch(u,{method:'POST',body:JSON.stringify(b)});}
async function audit(){const r=await (await fetch('/api/audit')).json();$('auditout').innerHTML=r.map(x=>'기록자 '+x.name+': '+x.status+' ('+x.length+'건, head '+x.head.slice(0,10)+')').join('<br>')}
async function intr(){const r=await (await fetch('/api/intruder',{method:'POST'})).json();$('introut').textContent=r.granted?'열람됨(문제!)':'거부됨: '+r.error}
async function tamper(){await post('/api/tamper',{});audit()}
async function reid(){const r=await (await fetch('/api/reidentify?reason='+encodeURIComponent($('reason').value))).json();$('reidout').innerHTML=r.error?r.error:r.map(x=>x.alias+' = '+x.name).join('<br>')}
async function tick(){const s=await (await fetch('/api/state')).json();
$('mode').textContent=s.live?'LLM: '+s.model:'오프라인(템플릿)';$('mode').className='tag'+(s.live?'':' off');
$('cnt').textContent='피어 '+s.peers+'명 · 아이디어 '+s.ideas.length+'건 · 원장 '+s.ledger.length+'건';
$('ev').innerHTML=s.events.map(e=>`<div class=k-${e.kind}>${new Date(e.ts*1000).toLocaleTimeString()} [${e.kind}] ${e.actor}: ${e.text}</div>`).join('');$('ev').scrollTop=1e9;
$('sheet').innerHTML=s.sheet.length?' 전달된 피어 '+s.sheet.length+'명 (broker 답변지)':'';
$('ideas').innerHTML=s.ideas.map(i=>`<div class="idea ${i.adopted?'ad':''}"><b>${i.title}</b> <span class=mono>${i.author}</span>${i.adopted?' ★채택':''}${i.review?` <span class=tag>심사 ${i.review.score}점</span>`:''}<br>${i.idea}<br><small>첫 단계: ${i.first_step} / 위험: ${i.risk}</small>${i.review?'<br><small>심사 의견('+i.review.judge+'): '+i.review.comment+'</small>':''}${i.adopted?'<br><small>채택 이유: '+i.reason+'</small>':`<br><button class=s onclick="post('/api/adopt',{h:'${i.hash}'})">채택</button>`}</div>`).join('')||'아직 없음';
$('ledger').innerHTML='<table><tr><th>#<th>종류<th>가명<th>해시<th>기록자 서명</tr>'+s.ledger.map(l=>`<tr><td>${l.seq}<td>${l.type}<td class=mono>${l.who}<td class=mono>${l.hash}<td class=mono>${l.sealed_by}`).join('')+'</table>';
const st=s.stats,ig=s.integrity;$('ovr').textContent=s.overseer;
if(st){const bars=Object.entries(st.score_hist).map(([k,v])=>k+'점 '+'█'.repeat(v)+' '+v).join('<br>');
$('stats').innerHTML=`<table><tr><td>원장 항목 <b>${st.entries}</b> (${Object.entries(st.by_type).map(([k,v])=>k+' '+v).join(', ')})<td>가명 <b>${st.pseudonyms}</b>개<td>아이디어 <b>${st.ideas}</b> · 채택 <b>${st.adopted}</b> (${Math.round(st.adoption_rate*100)}%)<td>심사 <b>${st.reviews}</b>건 · 평균 <b>${st.avg_score??'-'}</b><td>경과 ${st.span_sec}초</tr></table>
<div style="display:flex;gap:24px;flex-wrap:wrap"><div><b>심사 점수 분포</b><br><span class=mono>${bars||'-'}</span></div>
<div><b>기여 상위</b> <small>(역할 수행도 기여)</small><table><tr><th>가명<th>받은 사람<th>채택<th>역할</tr>${st.contribution.slice(0,8).map(c=>`<tr><td class=mono>${c.who}<td>${c.received_by}<td>${c.adopted}<td>${c.roles}`).join('')}</table></div>
<div><b>공유 흐름 상위</b><table>${st.top_flows.map(f=>`<tr><td class=mono>${f.frm} → ${f.to}<td>${f.n}`).join('')}</table></div>
<div><b>무결성 (절대자가 직접 검증)</b><br>${(ig.recorders||[]).map(x=>'기록자 '+x.who+': '+x.status+' ('+x.length+'건)').join('<br>')}<br>${ig.agree?'✅ 해시 체인·서명·기록자 서명 정상':'⚠ 변조 또는 불일치'}</div></div>`}
$('profiles').innerHTML='<table><tr><th>가명<th>v<th>역할<th>게시된 자기 요약</tr>'+(s.profiles||[]).map(p=>`<tr><td class=mono>${p.who}<td>${p.ver}<td>${p.offers.join(',')}<td>${p.summary}`).join('')+'</table>';
$('contrib').innerHTML=(s.access||[]).map(a=>`<div class=mono>${a.name}: ${a.reader} 열람 ${a.granted?'허용':'<b>거부</b>'}</div>`).join('')}
setInterval(tick,1500);tick();
</script>"""


def build_web(broker, me, peers, overseer):
    recorders = [p for p in peers if "record" in p.can]
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
        snap = await overseer.snapshot()  # the dashboard sees the ledger only through the overseer peer
        return JSONResponse(dict(live=llm.live(), model=llm.describe(), peers=len(broker.ads), ideas=ideas,
                                 ledger=snap.get("ledger", []), stats=snap.get("stats"), integrity=snap.get("integrity"),
                                 overseer=alias(overseer.id.pub), access=[dict(name=alias(c.id.pub), **a) for c in recorders for a in c.access_log[-3:]],
                                 profiles=[dict(who=alias(a["pub"]), ver=a.get("ver", 1), summary=a["summary"], offers=a.get("offers", [])) for a in broker.ads.values()],
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
        for n in recorders:
            res = await rpc(n.url, {"op": "audit"})
            out.append(dict(name=alias(n.id.pub), status=res["status"], head=res["head"], length=res["length"]))
        return JSONResponse(out)

    async def intruder(_):  # someone without a reader key tries to read the ledger
        from .common import Identity
        if not overseer.recorders:
            await overseer.locate()
        res = await overseer.read(overseer.recorders[0]["peer_url"], identity=Identity())
        return JSONResponse({"granted": res.get("ok", False), "error": res.get("error")})

    async def tamper(_):
        ch = recorders[0].ledger.chain
        if ch:
            ch[min(1, len(ch) - 1)]["payload"]["tampered"] = True  # the recorder's operator edits history behind everyone's back
            overseer._cache = (0, None)
            emit("ledger", "시연", "기록자 원장의 과거 항목을 몰래 수정했습니다")
        return JSONResponse({"ok": True})

    async def reidentify(r):
        reason = r.query_params.get("reason", "").strip()
        if not reason:
            return JSONResponse({"error": "사유를 입력해야 실명을 확인할 수 있습니다"})
        reid_log.append({"ts": time.time(), "reason": reason})
        emit("audit", "감사 담당", f"실명 확인(사유: {reason}) - 접근 기록 {len(reid_log)}건")
        return JSONResponse([dict(alias=alias(k), name=v) for k, v in names.items() if any(i["author"] == k for i in me.ideas.values())])

    return Starlette(routes=[
        Route("/", lambda r: HTMLResponse(PAGE)), Route("/api/state", state),
        Route("/api/call", post_call, methods=["POST"]), Route("/api/close", close, methods=["POST"]),
        Route("/api/adopt", adopt, methods=["POST"]), Route("/api/audit", audit),
        Route("/api/tamper", tamper, methods=["POST"]), Route("/api/intruder", intruder, methods=["POST"]), Route("/api/reidentify", reidentify)])
