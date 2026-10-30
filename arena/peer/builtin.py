"""Platform ops as built-in apps, plugged in exactly like any other app. Their op names are reserved."""
from __future__ import annotations

import asyncio
from collections import deque

from ..crypto import verify
from .plugin import BaseApp, EventApprover, MessageHead, RequestReceiver, RoleAcceptor


class RoleContracts(BaseApp):
    """op engage: a peer is asked to take a role for one event; the app that knows that role decides"""
    name, version = "platform.roles", "1.0"

    def ops(self):
        return {"engage": self._engage}

    async def _engage(self, ctx, msg, head: MessageHead):
        role, contract = msg.get("role"), msg.get("contract", {})
        if role not in ctx.offers() or contract.get("role") != role:
            return {"ok": False, "error": f"role {role} not offered"}
        if contract.get("contractor") != ctx.pub:
            return {"ok": False, "error": "the contract names another contractor"}
        if head.group_id and contract.get("group_id") not in (None, head.group_id):
            return {"ok": False, "error": "the contract's group differs from the head"}
        for app, actx in ctx.apps_with(RoleAcceptor):
            d = await app.accept_role(actx, role, msg.get("request", {}))
            if d is not None:
                ctx.log.emit("contract", ctx.pen, f"'{role}' 역할 계약 {'수락' if d.accept else '거절'}: {d.reason[:80]}")
                return {"ok": True, "sig": ctx.sign(contract), "reason": d.reason} if d.accept else {"ok": False, "error": d.reason}
        return {"ok": False, "error": f"no app decides about role {role}"}


class EventApprovals(BaseApp):
    """op approve: sign an event declaration if I am listed as an approver and an approving app agrees"""
    name, version = "platform.approvals", "1.0"

    def ops(self):
        return {"approve": self._approve}

    async def _approve(self, ctx, msg, head: MessageHead):
        event = msg.get("event", {})
        if ctx.pub not in event.get("approvers", []):
            return {"ok": False, "error": "I am not an approver of this event"}
        for app, actx in ctx.apps_with(EventApprover):
            d = await app.approve_event(actx, event, msg.get("request", {}))
            if d is not None:
                ctx.log.emit("approve", ctx.pen, f"이벤트 {event.get('event_id')} 결재 {'승인' if d.accept else '반려'}: {d.reason[:80]}")
                return {"ok": True, "sig": ctx.sign(event), "reason": d.reason} if d.accept else {"ok": False, "error": d.reason}
        return {"ok": False, "error": "no app approves events here"}


class DirectRequests(BaseApp):
    """op solicit (receive) and send(): signed requests to chosen peers without a notice board; inbox kept across restarts"""
    name, version = "platform.requests", "1.0"

    def __init__(self, settings):
        self.inbox: deque = deque(maxlen=settings.solicit_inbox_size)
        self._loaded = False

    def ops(self):
        return {"solicit": self._receive}

    def load(self, ctx) -> None:
        if not self._loaded:
            self.inbox.extend(ctx.state.load().get("inbox", []))
            self._loaded = True

    async def send(self, ctx, targets: list[str], request: dict) -> dict:
        sig = ctx.sign(request)

        async def one(url):
            try:
                return await ctx.call(url, {"op": "solicit", "request": request, "sig": sig}, group=request.get("group_id"),
                                      event=request.get("event_id"))
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        acks = await asyncio.gather(*(one(u) for u in targets))
        ctx.log.emit("solicit", ctx.pen, f"직접 요청 {request.get('request_id')} → {len(targets)}명 중 {sum(bool(a.get('ok')) for a in acks)}명 수신")
        return dict(zip(targets, acks))

    async def _receive(self, ctx, msg, head: MessageHead):
        self.load(ctx)
        r, sig = msg.get("request", {}), msg.get("sig", "")
        issuer = r.get("issuer_pub", "")
        if not verify(issuer, r, sig):
            return {"ok": False, "error": "bad signature"}
        if r.get("until", 0) <= ctx.clock():
            return {"ok": False, "error": "request expired"}
        if head.group_id and r.get("group_id") not in (None, head.group_id):
            return {"ok": False, "error": "the request's group differs from the head"}
        labels = set(ctx.labels)
        if not all(f"{k}:{v}" in labels for k, v in r.get("audience", {}).items()):  # the broker's audience rule
            return {"ok": False, "error": "audience mismatch"}
        if any(x["request"].get("request_id") == r.get("request_id") and x["sender"] == issuer for x in self.inbox):
            return {"ok": False, "error": "duplicate request"}
        self.inbox.append({"request": r, "sender": issuer, "ts": ctx.clock()})
        ctx.state.save({"inbox": list(self.inbox)})
        ctx.log.emit("solicit", ctx.pen, f"직접 요청 받음 {r.get('request_id')}: {str(r.get('title', ''))[:40]}")
        for app, actx in ctx.apps_with(RequestReceiver):
            asyncio.create_task(app.on_request(actx, r, issuer))
        return {"ok": True, "received": True}


RESERVED_OPS = {"engage", "approve", "solicit"}
