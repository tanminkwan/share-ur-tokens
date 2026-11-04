"""Platform ops as built-in apps, plugged in exactly like any other app. Their op names are reserved."""
from __future__ import annotations

import asyncio
import re
from collections import deque

from ..crypto import verify
from ..ledger.envelope import body_of
from .plugin import BaseApp, EventEndorser, MessageHead, RequestReceiver, RoleAcceptor


HEX64 = re.compile(r"^[0-9a-f]{64}$")


class RoleContracts(BaseApp):
    """op engage: a peer is asked to take a role for one event; the app that knows that role decides"""
    name, version, app_id = "platform.roles", "1.0", "5211b58e-dac1-4ea9-be56-97781d20fee6"

    def ops(self):
        return {"engage": self._engage}

    async def _engage(self, ctx, msg, head: MessageHead):
        role, contract, body = msg.get("role"), msg.get("contract", {}), msg.get("body")
        if body is None:
            body = contract  # nothing private
        if body_of(contract, body) is None:  # protocol 3: sign only a body that commits to the full contract I was shown
            return {"ok": False, "error": "the body to sign does not match the contract"}
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
                return {"ok": True, "sig": ctx.sign(body), "reason": d.reason} if d.accept else {"ok": False, "error": d.reason}
        return {"ok": False, "error": f"no app decides about role {role}"}


class EventEndorsements(BaseApp):
    """op endorse: another peer asks me to co-sign its event (user 2026-11-04: weight for an event, never a gate). I check
    the body names me and an event really declared by that issuer, an app of mine decides, and I sign the body. The
    issuer then appends it to the ledger or keeps it with the notice (arena/ledger/endorse.py)"""
    name, version, app_id = "platform.endorsements", "1.0", "2de7bd30-f595-426d-a073-6dd3f9400c1f"

    def ops(self):
        return {"endorse": self._endorse}

    async def _endorse(self, ctx, msg, head: MessageHead):
        from ..ledger.endorse import HOWS, body_error
        body = msg.get("body")
        bad = body_error(body) or (None if msg.get("how", "ledger") in HOWS else f"how must be one of {', '.join(HOWS)}")
        if bad:
            return {"ok": False, "error": bad}
        if body["endorser"] != ctx.pub:
            return {"ok": False, "error": "the endorsement names another endorser"}
        if msg.get("recorder_url"):  # never co-sign an event that is not there
            v = await ctx.recorder(msg["recorder_url"]).verify(body["event_hash"])
            if not (v.get("exists") and v.get("type") == "event" and v.get("event_id") == body["event_id"] and v.get("issuer") == body["issuer"]):
                return {"ok": False, "error": "the ledger has no such event by that issuer"}
        for app, actx in ctx.apps_with(EventEndorser):
            d = await app.endorse_event(actx, body, msg.get("request", {}))
            if d is not None:
                ctx.log.emit("endorse", ctx.pen, f"이벤트 {body['event_id']} 공동 서명 {'함' if d.accept else '안 함'}: {d.reason[:80]}")
                return {"ok": True, "sig": ctx.sign(body), "reason": d.reason} if d.accept else {"ok": False, "error": d.reason}
        return {"ok": False, "error": "no app here decides about endorsements"}


class DirectRequests(BaseApp):
    """op solicit (receive) and send(): signed requests to chosen peers without a notice board; inbox kept across restarts"""
    name, version, app_id = "platform.requests", "1.0", "678ebd71-aa0c-4718-9a76-4aa7948e5950"

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

        async def one(target):
            msg = {"op": "solicit", "request": request, "sig": sig}
            try:
                if HEX64.fullmatch(target):  # a public key: by its listed connections (P6-Q1)
                    return await ctx.call_peer(target, msg, group=request.get("group_id"), event=request.get("event_id"))
                return await ctx.call(target, msg, group=request.get("group_id"), event=request.get("event_id"))
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


RESERVED_OPS = {"engage", "endorse", "solicit"}
