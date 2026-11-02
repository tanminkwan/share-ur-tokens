"""Generic tools of the basic assistant. A tool is registered, not wired into the assistant: name, description,
argument schema, host-only flag and an async run(assistant, ctx, state, **args). No tool knows any kind of event."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from ...crypto import h
from .state import commit_hash, nonce


def _obj(**props):
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


S = {"type": "string"}
PARTY = _obj(pub=S, url=S)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: dict | None                       # JSON schema of the arguments, None = no arguments
    run: Callable[..., Awaitable[dict]]     # run(assistant, ctx, state, **args)
    host_only: bool = False
    participant_only: bool = False
    after_close: bool = False               # still usable once the event is closed
    element: str | None = None              # a built-in element's tool: offered only where the event switched it on


# ---------------- implementations ----------------
async def ledger_tag(ctx, st) -> dict:
    """{"ledger_id": ...} for payloads recorded on this event's ledger (binds the signature to that ledger)"""
    lid = await ctx.ledger_id(st.recorder_url)
    return {"ledger_id": lid} if lid else {}


async def _record(A, ctx, st, kind, payload):
    payload = {**payload, **(await ledger_tag(ctx, st))}
    r = await ctx.recorder(st.recorder_url).record(kind, payload, {ctx.pub: ctx.sign(payload)})
    if r.get("ok"):
        ctx.receipts.keep(r, kind, payload, expected_recorder=st.recorder_pub)
    return r


async def ask_owner(A, ctx, st, question):
    a = await ctx.owner.ask(question, st.rules)
    ctx.log.emit("decide", ctx.pen, f"소유자에게 물음 '{question[:40]}' → {'예' if a.yes else '아니오'}: {a.why}")
    return {"yes": a.yes, "why": a.why}


async def join_event(A, ctx, st):
    if st.role == "host":
        return {"error": "개최자는 참가 신청하지 않는다"}
    st.joined = True
    r = await A.send(ctx, st, st.issuer_url, "참가 신청", {"type": "join", "rules_hash": st.rules_hash})
    if not r.get("ok"):
        st.joined = False
    return r


async def contract(A, ctx, st, role, peer):
    peer_pub, peer_url = await A.resolve_peer(ctx, st, peer)
    if not peer_pub or not peer_url:
        return {"ok": False, "error": f"{peer}를 찾지 못했다(필명이나 공개키를 확인)"}
    if peer_pub not in st.applicants and not await A.offers_role(ctx, peer_pub, role):
        # enforced by code: peers whose signed join carried this event's rules hash, or peers whose profile offers the role
        return {"ok": False, "error": f"참가 신청한 peer나 그 역할을 프로필에 내건 peer만 계약할 수 있다(신청자: {len(st.applicants)}명)"}
    c = {"event_id": st.event_id, "role": role, "issuer": ctx.pub, "contractor": peer_pub, "nonce": nonce(peer_pub, role),
         "group_id": st.group_id, "rules_hash": st.rules_hash, **(await ledger_tag(ctx, st))}
    eng = await ctx.call(peer_url, {"op": "engage", "role": role, "contract": c, "request": {"event_id": st.event_id, "rules_hash": st.rules_hash}},
                         group=st.group_id, event=st.event_id)
    if not eng.get("ok"):
        return {"ok": False, "error": eng.get("error")}
    r = await ctx.recorder(st.recorder_url).record("contract", c, {ctx.pub: ctx.sign(c), peer_pub: eng["sig"]})
    if r.get("ok"):
        st.peers[peer_pub] = peer_url
        st.contracts.append([role, peer_pub])
    return {"ok": bool(r.get("ok")), "hash": r.get("hash"), "error": r.get("error"), "contracts_so_far": len(st.contracts)}


async def call_service(A, ctx, st, peer, op, input=None):
    """call an API-providing peer; the code checks the signed receipt and keeps it (P6-A5)"""
    from ...sdk.service import verify_service_receipt
    pub, _ = await A.resolve_peer(ctx, st, peer, need_url=False)
    if not pub:
        return {"ok": False, "error": f"{peer}를 찾지 못했다"}
    req = {"op": op, "input": input if isinstance(input, dict) else {}}
    r = await ctx.call_peer(pub, req, group=st.group_id, event=st.event_id)  # a2a or api, by the peer's profile
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    bad = verify_service_receipt(r, req, pub)
    if bad:
        return {"ok": False, "error": f"서비스 영수증이 맞지 않는다(코드 확인): {bad}"}
    st.service_receipts.append({"peer": pub, "op": op, "receipt": r["receipt"], "receipt_sig": r["receipt_sig"]})
    return {"ok": True, "result": r["result"]}


async def contact(A, ctx, st, peer):
    """the human connection of a peer, for the owner to use themselves: never sent automatically (P6-A8)"""
    pub, _ = await A.resolve_peer(ctx, st, peer, need_url=False)
    prof = await ctx.profile_of(pub) if pub else None
    humans = [c["contact"] for c in (prof or {}).get("connections", []) if c.get("kind") == "human"]
    if not humans:
        return {"ok": False, "error": f"{peer}는 사람 연락처를 공개하지 않았다"}
    return {"ok": True, "contact": humans, "note": "사람끼리 연결: 플랫폼은 대신 보내지 않는다. 소유자에게 알려 직접 연락하게 하라"}


async def send(A, ctx, st, to, text, data=None, attach_reveals=()):
    data = dict(data or {}) if isinstance(data, dict) else {"data": data}
    for r in A.reveal_records(data):  # enforced by code: my own reveal travels exactly as committed, never retyped
        if r.get("author") == ctx.pub and r != await my_reveal(A, ctx, st, r.get("label")):
            return {"ok": False, "error": f"손으로 옮긴 내 공개값(라벨 {r.get('label')})이 내 기록과 다르다. 보내지 않았다. "
                                          "공개값은 attach_reveals에 라벨을 넣어 코드가 붙이게 하라"}
    for label in attach_reveals or ():
        rec = await my_reveal(A, ctx, st, label)
        if "error" in rec:
            return {"ok": False, "error": rec["error"]}
        data.setdefault("reveals", []).append(rec)
    pub, url = await A.resolve_peer(ctx, st, to)
    if not url:
        return {"ok": False, "error": f"{to}의 주소를 찾지 못했다"}
    r = await A.send(ctx, st, url, text, data)
    if r.get("ok"):
        for label in attach_reveals or ():
            st.sent_reveals.setdefault(label, [])
            if pub and pub not in st.sent_reveals[label]:
                st.sent_reveals[label].append(pub)
    return r


async def solicit(A, ctx, st, targets, text, data=None):
    urls = []
    for t in targets:
        _, url = await A.resolve_peer(ctx, st, t)
        if not url:
            return {"error": f"{t}의 주소를 찾지 못했다"}
        urls.append(url)
    targets = urls
    req = {"request_id": f"{st.event_id}-{nonce(text)[:8]}", "event_id": st.event_id, "text": text, "data": data or {},
           "issuer_pub": ctx.pub, "issuer_url": ctx.url, "until": ctx.clock() + ctx.settings.event_request_ttl_sec, "group_id": st.group_id}
    acks = await ctx.solicit(list(targets), req)
    return {"request_id": req["request_id"], "acks": {u: bool(a.get("ok")) for u, a in acks.items()}}


async def publish_text(A, ctx, st, text):
    p = {"author": ctx.pub, "content_hash": h(str(text).encode()), "event_id": st.event_id, "group_id": st.group_id}
    r = await _record(A, ctx, st, "publish", p)
    return {"ok": bool(r.get("ok")), "content_hash": p["content_hash"], "publish_hash": r.get("hash"), "error": r.get("error")}


async def commit(A, ctx, st, label, value):
    allowed = st.policy.get("reveal_values")
    if allowed and value not in allowed:  # enforced by code; the ledger refuses such a reveal too
        return {"error": f"값은 이벤트가 정한 것 중 하나여야 한다: {', '.join(allowed)} (받은 값: {value})"}
    if label in st.secrets:
        return {"error": f"라벨 {label}은 이미 먼저 등록했다", **{k: st.secrets[label][k] for k in ("commit", "publish_hash")}}
    salt = nonce(label)
    c = commit_hash(label, value, salt, ctx.pub)
    p = {"author": ctx.pub, "content_hash": c, "event_id": st.event_id, "group_id": st.group_id, "label": label}  # the label is public, the value is not
    r = await _record(A, ctx, st, "publish", p)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    st.secrets[label] = {"value": value, "salt": salt, "commit": c, "publish_hash": r["hash"]}
    return {"ok": True, "label": label, "commit": c, "publish_hash": r["hash"]}


async def reveal(A, ctx, st, label):
    """open my registration on the ledger: the code fills value and salt, the ledger checks them against the sealed hash"""
    s = st.secrets.get(label)
    if not s:
        return {"error": f"먼저 등록한 라벨 {label}이 없다"}
    if s.get("reveal_hash"):
        return {"ok": True, "hash": s["reveal_hash"], "note": "이미 원장에 공개했다"}
    p = {"author": ctx.pub, "label": label, "value": s["value"], "salt": s["salt"], "commit": s["publish_hash"],
         "event_id": st.event_id, "group_id": st.group_id}
    r = await _record(A, ctx, st, "reveal", p)
    if r.get("ok"):
        s["reveal_hash"] = r["hash"]
    return {"ok": bool(r.get("ok")), "label": label, "value": s["value"], "hash": r.get("hash"), "error": r.get("error")}


async def my_reveal(A, ctx, st, label):
    """a reveal record in the platform's fixed shape, so the receiving side's code can check it against the ledger"""
    s = st.secrets.get(label)
    if not s:
        return {"error": f"먼저 등록한 라벨 {label}이 없다"}
    return {"author": ctx.pub, "label": label, "value": s["value"], "salt": s["salt"], "publish_hash": s["publish_hash"]}


async def check_reveal(A, ctx, st, publish_hash, author, label, value, salt):
    author_pub, _ = await A.resolve_peer(ctx, st, author, need_url=False)
    v = await ctx.recorder(st.recorder_url).verify(publish_hash)
    if not (v.get("exists") and v.get("type") == "publish" and v.get("author") == author_pub and v.get("event_id") == st.event_id):
        return {"match": False, "reason": "그 등록이 원장에 없거나 다른 사람·다른 이벤트의 등록"}
    ok = v.get("content_hash") == commit_hash(label, value, salt, author_pub)
    return {"match": ok, **({} if ok else {"reason": "공개값이 먼저 등록한 해시와 맞지 않음"})}


async def verify_entry(A, ctx, st, hash):
    v = await ctx.recorder(st.recorder_url).verify(hash)
    if v.get("exists"):
        return v
    held = next((e for e in await A.progress_entries(ctx, st) if e.get("content_hash") == hash), None)  # a content hash, not an entry hash?
    if held:
        v["content_of"] = {k: held[k] for k in ("hash", "type", "author", "label") if k in held}
        v["note"] = "이 값은 원장 항목 해시가 아니라 내용 해시다. 그 내용을 담은 원장 항목은 content_of.hash"
    return v


async def event_progress(A, ctx, st):
    return {"ok": True, "note": A.SETTLED_NOTE, "progress": await A.progress_lines(ctx, st)}


async def propose_attest(A, ctx, st, kind, subject, value, parties):
    resolved = []
    for x in parties:
        pub, url = await A.resolve_peer(ctx, st, x, need_url=(x not in (ctx.pub, ctx.pen)))
        if not pub:
            return {"error": f"당사자 {x}를 찾지 못했다"}
        resolved.append({"pub": pub, "url": url})
    parties = resolved
    value, missing = await A.fill_reveals(ctx, st, value)  # "공개:<handle>:<label>" -> the reveal record, by code
    if missing:
        return {"error": f"이런 공개값이 없다(내가 등록했거나 받아서 코드가 확인한 것만 쓸 수 있다): {', '.join(missing)}"}
    bad = [why for ok, why in await A.verify_reveals(ctx, st, value) if not ok]
    if bad:  # enforced by code: never propose a result whose reveals do not match the ledger
        return {"error": f"value 안의 공개값이 원장과 맞지 않는다(코드 확인): {'; '.join(bad)}"}
    pubs = [x["pub"] for x in parties]
    refused = await A.attest_precheck(ctx, st, kind, subject, pubs)
    if refused:  # what the ledger would refuse is refused here, before anyone is asked to sign
        return {"error": refused}
    p = {"event_id": st.event_id, "kind": kind, "subject": subject, "value": value, "parties": pubs, "nonce": nonce(kind, subject),
         "group_id": st.group_id, **(await ledger_tag(ctx, st))}
    if pubs == [ctx.pub]:
        r = await _record(A, ctx, st, "attest", p)
        return {"ok": bool(r.get("ok")), "hash": r.get("hash"), "error": r.get("error")}
    if ctx.pub not in pubs:
        return {"error": "제안하는 나도 당사자여야 한다"}
    rid = f"{st.event_id}-{nonce(subject)[:8]}"
    st.proposals[rid] = {"payload": p, "sigs": {ctx.pub: ctx.sign(p)}}
    acks = {}
    for x in parties:
        if x["pub"] != ctx.pub:
            acks[x["pub"][:8]] = bool((await A.post(ctx, st, x["url"], "attest_request", {"request_id": rid, "payload": p})).get("ok"))
    return {"request_id": rid, "sent": acks}


async def cosign(A, ctx, st, request_id):
    req = st.pending.get(request_id)
    if not req:
        return {"error": f"서명 요청 {request_id}이 없다"}
    if req.get("reveals_ok") is False:  # enforced by code
        return {"error": "이 요청의 공개값이 원장과 맞지 않아 서명할 수 없다(코드 확인). decline으로 거절하라"}
    st.pending.pop(request_id)
    return await A.post(ctx, st, req["from_url"], "attest_signature", {"request_id": request_id, "attest_sig": ctx.sign(req["payload"])})


async def decline(A, ctx, st, request_id, reason):
    req = st.pending.pop(request_id, None)
    if not req:
        return {"error": f"서명 요청 {request_id}이 없다"}
    return await A.post(ctx, st, req["from_url"], "attest_signature", {"request_id": request_id, "declined": True, "reason": reason})


async def assign(A, ctx, st, subjects):
    if not isinstance(subjects, dict) or not subjects:
        return {"error": "subjects_json은 {주제: [필명, ...]} 모양의 JSON 객체여야 한다"}
    out = {}
    for k, parties in subjects.items():
        pubs = []
        for x in parties if isinstance(parties, list) else [parties]:
            pub, _ = await A.resolve_peer(ctx, st, x, need_url=False)
            if not pub:
                return {"error": f"{x}를 찾지 못했다"}
            pubs.append(pub)
        out[str(k)] = pubs
    p = {"event_id": st.event_id, "issuer": ctx.pub, "subjects": out, "group_id": st.group_id}
    r = await _record(A, ctx, st, "assign", p)
    if r.get("ok"):
        st.assignments.update(out)
    return {"ok": bool(r.get("ok")), "hash": r.get("hash"), "error": r.get("error")}


async def close_event(A, ctx, st, result_hash):
    v = await ctx.recorder(st.recorder_url).verify(result_hash)  # checked by code: the result must be on the ledger, in this event
    if not (v.get("exists") and v.get("event_id") == st.event_id):
        return {"error": "result_hash는 이 이벤트의 원장 항목이어야 한다(결과를 먼저 원장에 기록한 뒤 닫는다)"}
    c = {"event_id": st.event_id, "issuer": ctx.pub, "result_hash": result_hash, "group_id": st.group_id}
    r = await _record(A, ctx, st, "close", c)
    if r.get("ok"):
        st.closed = True
        await ctx.brokers[A.group].close_notice(ctx.identity, st.event_id)
    return {"ok": bool(r.get("ok")), "hash": r.get("hash"), "error": r.get("error")}


async def note(A, ctx, st, text):
    return {"ok": True}


async def wait(A, ctx, st):
    return {"ok": True}


def default_tools() -> list[Tool]:
    return [
        Tool("ask_owner", "{question}: 소유자(사람)에게 예/아니오로 묻는다. 결과 yes, why", _obj(question=S), ask_owner),
        Tool("join_event", "{}: 이 이벤트에 참가 신청을 한다(개최자에게 메시지로 알림)", None, join_event, participant_only=True),
        Tool("contract", "{role, peer}: 그 peer(필명)와 이 이벤트의 역할 계약을 맺어 원장에 기록한다. 계약에는 규칙 해시가 들어간다",
             _obj(role=S, peer=S), contract, host_only=True),
        Tool("send", "{to, text, data_json, attach_reveals?: [라벨...]}: 상대 peer(필명)에게 이 이벤트의 메시지를 보낸다(data_json은 JSON 객체를 담은 문자열). "
             "내 공개값을 보낼 때는 손으로 옮기지 말고 attach_reveals에 라벨을 넣는다. 코드가 공개값 묶음을 data.reveals에 그대로 붙인다",
             dict(_obj(to=S, text=S, data_json=S), properties={"to": S, "text": S, "data_json": S, "attach_reveals": {"type": "array", "items": S}}),
             send),
        Tool("call_service", "{peer, op, input_json}: API를 제공하는 peer(필명)의 op를 부른다(input_json은 JSON 객체 문자열). "
             "결과와 함께 온 서명 영수증은 코드가 확인하고 보관한다", _obj(peer=S, op=S, input_json=S), call_service),
        Tool("contact", "{peer}: 상대 peer(필명)의 사람 연락처(human 연결)를 찾아 알려 준다. 자동으로 보내지 않는다", _obj(peer=S), contact),
        Tool("solicit", "{targets: [필명...], text, data_json}: 고른 peer들에게 직접 요청을 한 번에 보낸다(data_json은 JSON 객체 문자열)",
             _obj(targets={"type": "array", "items": S}, text=S, data_json=S), solicit),
        Tool("publish_text", "{text}: 글을 원장에 먼저 등록한다. 결과 content_hash, publish_hash", _obj(text=S), publish_text),
        Tool("commit", "{label, value}: 값에 비밀값을 붙인 해시를 원장에 먼저 등록하고 값은 숨겨 둔다. 결과 label, commit, publish_hash",
             _obj(label=S, value=S), commit),
        Tool("reveal", "{label}: 내가 먼저 등록한 값을 원장에 공개한다(값과 비밀값은 코드가 채우고, 원장이 먼저 등록한 해시와 맞는지 확인한다). "
             "다른 사람의 공개는 진행 현황(event_progress)에서 보인다", _obj(label=S), reveal),
        Tool("my_reveal", "{label}: 내가 먼저 등록한 값의 공개값 묶음(author, label, value, salt, publish_hash)을 본다. 보낼 때는 send의 attach_reveals를 쓴다",
             _obj(label=S), my_reveal),
        Tool("check_reveal", "{publish_hash, author, label, value, salt}: 상대(필명)가 보낸 공개값이 상대가 먼저 등록한 해시와 맞는지 원장으로 확인한다. 결과 match",
             _obj(publish_hash=S, author=S, label=S, value=S, salt=S), check_reveal),
        Tool("verify", "{hash}: 원장 항목이 있는지와 공개 정보를 확인한다(내용 해시를 넣으면 그 내용을 담은 항목을 알려 준다)", _obj(hash=S), verify_entry, after_close=True),
        Tool("event_progress", "{}: 이 이벤트의 원장 기록(계약, 등록과 이름표, 공동 확인, 닫힘)을 순서대로 본다. 누가 무엇을 했는지 확인할 때 쓴다",
             None, event_progress, after_close=True),
        Tool("propose_attest", "{kind, subject, value_json, parties: [필명...]}: 공동 확인을 제안한다(value_json은 JSON 문자열). "
             "value 안에 공개값 묶음을 넣을 자리에는 \"공개:필명-xxxxxx:라벨\"이라고 쓰면 코드가 확인된 묶음을 그대로 넣는다. "
             "당사자가 나 혼자면 바로 기록하고, 아니면 다른 당사자에게 서명 요청을 보낸다",
             _obj(kind=S, subject=S, value_json=S, parties={"type": "array", "items": S}), propose_attest),
        Tool("cosign", "{request_id}: 받은 서명 요청에 서명해 돌려준다(내용이 내가 본 것과 같을 때만)", _obj(request_id=S), cosign),
        Tool("decline", "{request_id, reason}: 받은 서명 요청을 거절하고 이유를 알린다", _obj(request_id=S, reason=S), decline),
        Tool("assign", "{subjects_json}: 주제(예: 경기 번호)마다 맡을 당사자를 원장에 배정한다. subjects_json은 {\"주제\": [필명, ...]} JSON 문자열. "
             "배정된 종류의 공동 확인은 원장이 배정된 당사자에게서만 받는다", _obj(subjects_json=S), assign, host_only=True),
        Tool("close_event", "{result_hash}: 이 이벤트를 원장에서 닫고 공지를 마감한다", _obj(result_hash=S), close_event, host_only=True),
        Tool("note", "{text}: 나중을 위해 메모를 남긴다", _obj(text=S), note, after_close=True),
        Tool("wait", "{}: 이번 입력에 대해 할 일을 다 했다. 다음 입력을 기다린다", None, wait, after_close=True),
    ]
