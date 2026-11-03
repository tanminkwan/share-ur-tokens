"""Messenger: signed bodies between assistants (protocol 6.4): sign, check, send by the other peer's listed connections.
One responsibility: the wire of event messages."""
from __future__ import annotations

from ...crypto import verify
from ..plugin import MessageHead


class Messenger:
    @staticmethod
    def sign_body(ctx, body: dict) -> dict:
        b = dict(body, pub=ctx.pub, ts=ctx.clock())
        return dict(b, sig=ctx.sign(b))

    @staticmethod
    def check(ctx, msg: dict) -> str | None:
        """the sender's public key if the body is signed by it within the time window"""
        body = {k: v for k, v in msg.items() if k != "sig"}
        ok = (msg.get("pub") and abs(ctx.clock() - float(msg.get("ts", 0))) <= ctx.settings.sig_window_sec
              and verify(msg["pub"], body, msg.get("sig", "")))
        return msg["pub"] if ok else None

    @staticmethod
    def head_ok(st, msg, head: MessageHead) -> bool:
        """group/event inside the signed body must be this event's, and the head (if any) must say the same"""
        if msg.get("group_id") != st.group_id or msg.get("event_id") != st.event_id:
            return False
        return (not head.group_id or head.group_id == st.group_id) and (not head.event_id or head.event_id == st.event_id)

    async def post(self, ctx, st, url, op, body: dict, pub: str | None = None) -> dict:
        """a signed body to another peer: by its listed connections when I know who it is (P6-Q1), else at the address"""
        msg = self.sign_body(ctx, {"op": op, "event_id": st.event_id, "group_id": st.group_id, "url": ctx.url, **body})
        if pub:
            return await ctx.call_peer(pub, msg, group=st.group_id, event=st.event_id, url=url)
        return await ctx.call(url, msg, group=st.group_id, event=st.event_id)

    async def send(self, ctx, st, to_url, text, data, pub: str | None = None) -> dict:
        return await self.post(ctx, st, to_url, "event_message", {"text": text, "data": data}, pub=pub)
