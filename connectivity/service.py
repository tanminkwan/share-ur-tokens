"""ConnectivityService: who is attached, the requests waiting for them, and the limits (dev/phase10/design.md 3, 5). One responsibility:
the rules of the tunnel. No I/O and no HTTP: the clock is injected, the API (api.py) only translates.

A server that cannot take inbound calls polls (GET /poll). A caller's request to /r/<key>/... is queued for its
next poll; it answers with POST /reply/<id>; the caller gets that answer. The session is its attachment:
it lives while polls keep coming. Requests and answers are passed through memory and never stored (dev/phase10/design.md 4)."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field


class Refused(Exception):
    """a request the service will not carry out; status is the HTTP code the API answers with"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Tunnel:
    """one request passing through, waiting for its answer"""
    id: str
    method: str
    path: str
    query: str
    headers: dict
    body: bytes
    future: asyncio.Future

    def view(self) -> dict:
        return {"id": self.id, "method": self.method, "path": self.path, "query": self.query, "headers": self.headers}


@dataclass
class Attachment:
    """an attached key's session: it lives while polls keep coming (dev/phase10/design.md 5)"""
    pub: str
    since: float
    last_seen: float
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    inflight: dict = field(default_factory=dict)  # request id -> Tunnel
    polling: int = 0  # polls waiting right now: it is there
    relayed_bytes: int = 0


class RateLimit:
    """at most `per_sec` events per key in any one second"""

    def __init__(self, per_sec: float, clock):
        self.per_sec, self.clock, self.seen = per_sec, clock, {}

    def allow(self, key) -> bool:
        now = self.clock()
        q = self.seen.setdefault(key, deque())
        while q and now - q[0] >= 1.0:
            q.popleft()
        if len(q) >= self.per_sec:
            return False
        q.append(now)
        if len(self.seen) > 4096:  # keys that have gone quiet are dropped
            for k in [k for k, v in self.seen.items() if not v or now - v[-1] >= 1.0]:
                del self.seen[k]
        return True


def load_allow_keys(path: str) -> set | None:
    """public keys allowed to attach, one per line (# starts a comment); None when no file is set (anyone with a valid signature)"""
    if not path:
        return None
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        return {ln.split("#")[0].strip() for ln in f if ln.split("#")[0].strip()}


class ConnectivityService:
    def __init__(self, settings, clock=time.time, allow_keys: set | None = None):
        self.s, self.clock, self.allow_keys = settings, clock, allow_keys
        self.attached: dict[str, Attachment] = {}
        self.limit = RateLimit(settings.rate_per_sec, clock)
        self.relayed_bytes = 0
        self.refused: dict[str, int] = {}
        self.started = clock()
        from .out import OutGateway  # here, not at the top: out.py uses RateLimit from this file
        self.out = OutGateway(settings, clock=clock)
        self.out_calls = self.out_bytes = 0
        self.signatures: dict[str, float] = {}  # signatures already used by /out, until their time window has passed

    def take_signature(self, sig: str) -> bool:
        """True the first time a signature is seen (within its time window), False for a copy of it"""
        now = self.clock()
        for k in [k for k, until in self.signatures.items() if until < now]:
            del self.signatures[k]
        if sig in self.signatures:
            return False
        self.signatures[sig] = now + 2 * self.s.sig_window_sec
        return True

    def refuse(self, status: int, why: str, message: str) -> Refused:
        """a refusal, counted by why (for /health)"""
        self.refused[why] = self.refused.get(why, 0) + 1
        return Refused(status, message)

    # ---- the attached side ----
    def expire(self) -> None:
        """close the sessions of keys that stopped polling; what they were still carrying ends with 503"""
        now = self.clock()
        for pub, a in list(self.attached.items()):
            if not a.polling and now - a.last_seen > self.s.attach_grace_sec:
                del self.attached[pub]
                for t in a.inflight.values():
                    if not t.future.done():
                        t.future.set_exception(self.refuse(503, "detached", "not attached"))

    def touch(self, pub: str) -> Attachment:
        """the key is here (a poll or an answer): its session starts or goes on"""
        self.expire()
        if self.allow_keys is not None and pub not in self.allow_keys:
            raise self.refuse(403, "not_allowed", "this key may not attach")
        a = self.attached.get(pub)
        if a is None:
            if len(self.attached) >= self.s.max_attached:
                raise self.refuse(429, "full", "too many attached keys")
            a = self.attached[pub] = Attachment(pub, since=self.clock(), last_seen=self.clock())
        a.last_seen = self.clock()
        return a

    async def poll(self, pub: str, hold: float) -> list[Tunnel]:
        """the requests for this key, waiting up to `hold` seconds (capped) for one to come"""
        a = self.touch(pub)
        hold = max(0.0, min(hold, self.s.poll_hold_sec))
        a.polling += 1
        try:
            first = await asyncio.wait_for(a.queue.get(), hold)
        except asyncio.TimeoutError:
            return []
        finally:
            a.polling -= 1
            a.last_seen = self.clock()
        items = [first]
        while not a.queue.empty():
            items.append(a.queue.get_nowait())
        return items

    def reply(self, pub: str, request_id: str, status: int, headers: dict, body: bytes) -> bool:
        """the answer to a request this key was given; only the key that was given it can answer it"""
        a = self.attached.get(pub)
        t = a.inflight.get(request_id) if a else None
        if t is None or t.future.done():
            return False
        a.last_seen = self.clock()
        if len(body) > self.s.max_body_bytes:
            t.future.set_exception(self.refuse(502, "big_answer", "the answer is too large"))
            return True
        t.future.set_result((status, headers, body))
        return True

    # ---- the caller's side ----
    async def relay(self, source: str, target: str, method: str, path: str, query: str, headers: dict, body: bytes):
        """pass one request to the attached key `target` and give back its answer (status, headers, body)"""
        self.expire()
        a = self.attached.get(target)
        if a is None:
            raise self.refuse(503, "detached", "not attached")
        if len(body) > self.s.max_body_bytes:
            raise self.refuse(413, "big_request", "request body too large")
        if not self.limit.allow((source, target)):
            raise self.refuse(429, "rate", "too many requests")
        if len(a.inflight) >= self.s.max_inflight:
            raise self.refuse(429, "inflight", "too many requests in flight for this key")
        t = Tunnel(uuid.uuid4().hex, method, path, query, headers, body, asyncio.get_running_loop().create_future())
        a.inflight[t.id] = t
        a.queue.put_nowait(t)
        try:
            status, h, out = await asyncio.wait_for(t.future, self.s.request_timeout_sec)
        except asyncio.TimeoutError:
            raise self.refuse(504, "timeout", "no answer in time") from None
        finally:
            a.inflight.pop(t.id, None)
        n = len(body) + len(out)
        a.relayed_bytes += n
        self.relayed_bytes += n
        return status, h, out

    def health(self) -> dict:
        """counts only: what passes through is never shown (dev/phase10/design.md 4)"""
        self.expire()
        return {"ok": True, "name": "connectivity", "attached": len(self.attached),
                "inflight": sum(len(a.inflight) for a in self.attached.values()), "relayed_bytes": self.relayed_bytes,
                "refused": dict(self.refused), "out_calls": self.out_calls, "out_bytes": self.out_bytes,
                "uptime_sec": round(self.clock() - self.started, 1)}
