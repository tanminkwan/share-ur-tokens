"""The submission element, peer side (P6-B2 ~ B4). The receiving peer's IntakeDesk checks a submission by code (content
hash, the submitter's signature on the share, recipient, size, audience), co-signs and records the share on the ledger
(where the element's rules check recipient, deadline, the per-author limit and conflicting roles) and keeps it.
Assistant tools: submit (participants) and submissions (the host)."""
from __future__ import annotations

from ...crypto import h, verify
from ..assistant.tools import S, Tool, _obj, _record, ledger_tag
from ..assistant.state import nonce
from ..plugin import BaseApp, MessageHead
from . import PeerElement, register_peer_element


class IntakeDesk(BaseApp):
    name, version, app_id = "platform.intake", "1.0", "8d3c1f5a-2b6e-4a9d-b7c1-4e0f9a2d6b38"

    def __init__(self, settings):
        self.s = settings
        self.items: dict[str, list] = {}  # event_id -> submissions kept

    def load(self, ctx) -> None:
        self.items = dict(ctx.state.load().get("items", {}))

    async def start(self, ctx):
        self.load(ctx)

    def ops(self):
        return {"intake.submit": self._submit}  # element ops carry the element's name, so they never collide with apps

    def list(self, event_id: str) -> list:
        return list(self.items.get(event_id, []))

    async def _submit(self, ctx, msg, head: MessageHead):
        ev, content, sp, sig, url = msg.get("event_id"), msg.get("content"), msg.get("share") or {}, msg.get("sig", ""), msg.get("recorder_url")
        if not isinstance(content, str) or len(content.encode("utf-8")) > self.s.intake_max_content_bytes:
            return {"ok": False, "error": f"제출 내용은 {self.s.intake_max_content_bytes}바이트 이하의 글이어야 한다"}
        if sp.get("consumer") != ctx.pub or sp.get("terms") != "submission" or sp.get("event_id") != ev:
            return {"ok": False, "error": "이 제출은 이 peer에게 온 이 이벤트의 제출이 아니다"}
        if h(content.encode("utf-8")) != sp.get("content_hash"):
            return {"ok": False, "error": "내용이 먼저 등록한 해시와 맞지 않는다"}
        if not verify(sp.get("provider", ""), sp, sig):
            return {"ok": False, "error": "제출한 사람의 서명이 맞지 않는다"}
        trust = await ctx.recorder_trust(url) if url else {"ok": False, "why": "recorder_url 없음"}
        if not trust["ok"]:
            return {"ok": False, "error": f"기록자를 믿을 수 없다: {trust.get('why')}"}
        decl = next((e for e in (await ctx.recorder(url).event_entries(ev)).get("entries", []) if e["type"] == "event"), None)
        cfg = ((decl or {}).get("elements") or {}).get("intake")
        if cfg is None:
            return {"ok": False, "error": "이 이벤트는 제출 받기를 켜지 않았다"}
        if cfg.get("audience"):
            prof = await ctx.profile_of(sp["provider"]) or {}
            if not set(prof.get("labels", [])) & set(cfg["audience"]):
                return {"ok": False, "error": f"응모 대상({', '.join(cfg['audience'])})이 아니다"}
        r = await ctx.recorder(url).record("share", sp, {sp["provider"]: sig, ctx.pub: ctx.sign(sp)})
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error")}
        self.items.setdefault(ev, []).append({"author": sp["provider"], "content_hash": sp["content_hash"], "content": content,
                                             "share_hash": r["hash"], "at": ctx.clock()})
        ctx.state.save({"items": self.items})
        ctx.log.emit("intake", ctx.pen, f"[{ev}] 제출 받음({len(self.items[ev])}번째)")
        return {"ok": True, "hash": r["hash"], "seq": r["seq"], "seal": r["seal"]}


# ---------------- assistant tools ----------------
async def _receiver(A, ctx, st) -> str | None:
    who = st.elements["intake"]["receiver"]
    if who == "issuer":
        return st.issuer_pub
    return next((e["contractor"] for e in await A.progress_entries(ctx, st) if e["type"] == "contract" and e.get("role") == who), None)


async def submit(A, ctx, st, text):
    to = await _receiver(A, ctx, st)
    if not to:
        return {"ok": False, "error": "제출을 받을 사람이 아직 없다"}
    ch = h(str(text).encode("utf-8"))
    r = await _record(A, ctx, st, "publish", {"author": ctx.pub, "content_hash": ch, "event_id": st.event_id, "group_id": st.group_id})
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    sp = {"provider": ctx.pub, "consumer": to, "content_hash": ch, "terms": "submission", "nonce": nonce(ch), "event_id": st.event_id,
          "group_id": st.group_id, **(await ledger_tag(ctx, st))}
    out = await ctx.call_peer(to, {"op": "intake.submit", "event_id": st.event_id, "content": str(text), "share": sp, "sig": ctx.sign(sp),
                                   "recorder_url": st.recorder_url}, group=st.group_id, event=st.event_id)
    if out.get("ok"):
        ctx.receipts.keep(out, "share", sp, expected_recorder=st.recorder_pub)
    return {"ok": bool(out.get("ok")), "share_hash": out.get("hash"), "error": out.get("error")}


async def submissions(A, ctx, st):
    items = await ctx.submissions(st.event_id)
    return {"ok": True, "count": len(items), "submissions": [{"author": A.handle(ctx, st, x["author"]), "content": x["content"]} for x in items]}


register_peer_element(PeerElement("intake", app=IntakeDesk, tools=(
    Tool("submit", "{text}: 이 이벤트에 글을 제출한다(코드가 먼저 등록하고, 받는 사람에게 보내고, 받은 쪽 서명 영수증을 보관한다)",
         _obj(text=S), submit, participant_only=True, element="intake"),
    Tool("submissions", "{}: 받은 제출 목록(작성자 필명, 내용)을 본다", None, submissions, host_only=True, element="intake"),
)))
