"""Adapters: make things that know nothing about arena apps plug in as apps.

    function_app        plain functions                    -> an app with exactly those capabilities
    HttpServiceAdapter  an existing HTTP service / core business system endpoint -> ops that relay to it (service peer)
    A2AAgentAdapter     any A2A agent (not an arena peer)   -> an op that asks it in plain text
"""
from __future__ import annotations

from typing import Awaitable, Callable

import httpx

from ..a2a import ask_agent
from ..peer.plugin import Decision, MessageHead
from ..signing import SignatureError, verify_message


def function_app(name: str, version: str = "1.0", *, app_id: str, ops: dict | None = None, offers: list[str] | None = None,
                 accept_role: Callable[..., Awaitable[Decision | None]] | None = None,
                 endorse_event: Callable[..., Awaitable[Decision | None]] | None = None,
                 on_request: Callable[..., Awaitable[None]] | None = None, profile_extra: dict | None = None,
                 start: Callable[..., Awaitable[None]] | None = None, sdk: str = "1"):
    """build an app from functions; it has only the capabilities you give it"""
    ns: dict = {"name": name, "version": version, "app_id": app_id, "sdk": sdk}
    if ops is not None:
        ns["ops"] = lambda self: dict(ops)
    if offers is not None:
        ns["offers"] = lambda self: list(offers)
    if accept_role is not None:
        async def _accept(self, ctx, role, request):
            return await accept_role(ctx, role, request)
        ns["accept_role"] = _accept
    if endorse_event is not None:
        async def _endorse(self, ctx, body, request):
            return await endorse_event(ctx, body, request)
        ns["endorse_event"] = _endorse
    if on_request is not None:
        async def _on_request(self, ctx, request, sender):
            await on_request(ctx, request, sender)
        ns["on_request"] = _on_request
    if profile_extra is not None:
        ns["profile_extra"] = lambda self: dict(profile_extra)
    if start is not None:
        async def _start(self, ctx):
            await start(ctx)
        ns["start"] = _start
    return type(f"FunctionApp[{name}]", (), ns)()


class HttpServiceAdapter:
    """relay ops to an existing HTTP API without changing it (the service-peer model).
    routes: {op: (method, path)}; a message {"path": {...}, "query": {...}, "body": {...}} fills the request.
    The peer does what the system cannot: check who asks (optional signed messages), which group asks, and be found."""

    def __init__(self, name: str, version: str, base_url: str, routes: dict[str, tuple[str, str]], *, app_id: str, offers: list[str] | None = None,
                 headers: dict | None = None, timeout: float = 30.0, allow_groups: list[str] | None = None,
                 require_signed: bool = False, http: httpx.AsyncClient | None = None, sdk: str = "1"):
        self.name, self.version, self.app_id, self.sdk = name, version, app_id, sdk
        self.base_url, self.routes, self.headers, self.timeout = base_url.rstrip("/"), dict(routes), headers or {}, timeout
        self._offers = list(offers if offers is not None else [f"service:{name}"])
        self.allow_groups, self.require_signed, self._http = allow_groups, require_signed, http

    def offers(self):
        return list(self._offers)

    def profile_extra(self):
        return {"service": {"name": self.name, "version": self.version, "ops": sorted(self.routes)}}

    def ops(self):
        return {op: self._relay(op, method, path) for op, (method, path) in self.routes.items()}

    def _relay(self, op, method, path):
        async def handler(ctx, msg, head: MessageHead):
            if self.allow_groups is not None and head.group_id not in self.allow_groups:
                return {"ok": False, "error": f"group {head.group_id} may not use {self.name}"}
            if self.require_signed:
                try:
                    verify_message(msg, now=ctx.clock(), window=ctx.settings.sig_window_sec)
                except SignatureError as e:
                    return {"ok": False, "error": f"signed message required: {e}"}
            url = self.base_url + path.format(**msg.get("path", {}))
            kw = dict(params=msg.get("query"), json=msg.get("body"), headers=self.headers)
            try:
                if self._http is not None:
                    r = await self._http.request(method, url, **kw)
                else:
                    async with httpx.AsyncClient(timeout=self.timeout) as hc:
                        r = await hc.request(method, url, **kw)
            except httpx.HTTPError as e:
                return {"ok": False, "error": f"{self.name} unreachable: {type(e).__name__}"}
            try:
                result = r.json()
            except ValueError:
                result = r.text
            ctx.log.emit("service", ctx.pen, f"{self.name}.{op} → {r.status_code}")
            return {"ok": r.is_success, "status": r.status_code, "result": result}
        return handler


class A2AAgentAdapter:
    """let arena peers use any A2A agent: op `ask` sends {"text"} to the agent in plain text and returns its reply"""

    def __init__(self, name: str, version: str, agent_url: str, *, app_id: str, op: str = "ask", offers: list[str] | None = None,
                 timeout: float = 60.0, ask=ask_agent, sdk: str = "1"):
        self.name, self.version, self.app_id, self.sdk = name, version, app_id, sdk
        self.agent_url, self.op, self.timeout, self._ask = agent_url, op, timeout, ask
        self._offers = list(offers if offers is not None else [f"agent:{name}"])

    def offers(self):
        return list(self._offers)

    def ops(self):
        async def handler(ctx, msg, head: MessageHead):
            try:
                reply = await self._ask(self.agent_url, str(msg.get("text", "")), self.timeout, head.event_id)
            except Exception as e:
                return {"ok": False, "error": f"agent unreachable: {type(e).__name__}: {e}"}
            return {"ok": True, "reply": reply}
        return {self.op: handler}
