"""The API-providing peer template (P6-A1 ~ A4). A JSON spec file alone makes a service peer: each op is a python
function `async fn(input, ctx) -> dict` or an HTTP route of an existing system. The peer checks who asks (groups,
signed callers), signs a receipt on every answer, takes on event roles it offers, and, for ops marked `record`, writes
its computed result on the ledger as a joint confirmation of that kind (e.g. a judging peer)."""
from __future__ import annotations

import importlib
import json
import os

from ..crypto import canon, h
from ..sdk.adapters import HttpServiceAdapter
from ..sdk.service import make_receipt
from ..signing import SignatureError, verify_message
from .plugin import Decision, MessageHead, is_uuid

SPEC_KEYS = {"name", "version", "app_id", "description", "offers", "roles", "ops", "base_url", "headers_env", "allow_groups", "require_signed"}


def check_spec(spec: dict) -> None:
    if not isinstance(spec, dict) or not set(spec) <= SPEC_KEYS or not {"name", "version", "app_id", "ops"} <= set(spec):
        raise ValueError(f"service spec needs name, version, app_id and ops (allowed keys: {sorted(SPEC_KEYS)})")
    if not is_uuid(spec["app_id"]):
        raise ValueError("service spec app_id must be a UUID")
    if not isinstance(spec["ops"], dict) or not spec["ops"]:
        raise ValueError("service spec needs at least one op")
    for op, d in spec["ops"].items():
        if not isinstance(d, dict) or ("python" in d) == ("http" in d):
            raise ValueError(f"op {op!r}: give exactly one of python or http")
        if "http" in d and not spec.get("base_url"):
            raise ValueError(f"op {op!r}: an http op needs base_url")


def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    check_spec(spec)
    return spec


def _function(ref: str):
    mod, attr = ref.split(":", 1)
    return getattr(importlib.import_module(mod), attr)


class ServiceApp:
    def __init__(self, settings, spec: dict, http=None):
        check_spec(spec)
        self.s, self.spec = settings, spec
        self.name, self.version, self.app_id = spec["name"], spec["version"], spec["app_id"]
        self.sdk = "1"
        routes = {op: (d["http"]["method"], d["http"]["path"]) for op, d in spec["ops"].items() if "http" in d}
        headers = {k: os.environ.get(env, "") for k, env in (spec.get("headers_env") or {}).items()}
        self._http = HttpServiceAdapter(self.name, self.version, spec.get("base_url", ""), routes, app_id=self.app_id, headers=headers,
                                        http=http) if routes else None
        self._fns = {op: _function(d["python"]) for op, d in spec["ops"].items() if "python" in d}

    # ---- capabilities ----
    def offers(self):
        return [f"service:{self.name}", *self.spec.get("offers", []), *self.spec.get("roles", [])]

    def profile_extra(self):
        return {"service": {"name": self.name, "version": self.version, "description": self.spec.get("description", ""),
                            "ops": {op: d.get("description", "") for op, d in self.spec["ops"].items()}}}

    async def accept_role(self, ctx, role, request):
        if role in self.spec.get("roles", []):
            return Decision(True, f"서비스 {self.name}이 맡는 역할")
        return None

    def ops(self):
        return {op: self._handler(op) for op in self.spec["ops"]}

    # ---- one op ----
    def _handler(self, op):
        d = self.spec["ops"][op]

        async def handler(ctx, msg, head: MessageHead):
            allow = self.spec.get("allow_groups")
            if allow is not None and head.group_id not in allow:
                return {"ok": False, "error": f"group {head.group_id} may not use {self.name}"}
            if self.spec.get("require_signed"):
                try:
                    verify_message(msg, now=ctx.clock(), window=ctx.settings.sig_window_sec)
                except SignatureError as e:
                    return {"ok": False, "error": f"signed message required: {e}"}
            data = msg.get("input", {}) or {}
            if op in self._fns:
                result, ok = await self._fns[op](data, ctx), True
            else:
                relayed = await self._http.ops()[op](ctx, {"path": data.get("path", {}), "query": data.get("query"), "body": data.get("body")}, head)
                ok, result = relayed.get("ok", False), {k: v for k, v in relayed.items() if k != "ok"}
            out = {"ok": ok, "result": result}
            if ok and d.get("record"):
                rec = await self._record(ctx, msg, head, d["record"]["kind"], data, result)
                if not rec.get("ok"):
                    return {"ok": False, "error": rec.get("error")}
                out["record"] = rec["hash"]
            receipt = make_receipt(ctx.pub, op, msg, result, ctx.clock())
            ctx.log.emit("service", ctx.pen, f"{self.name}.{op} → {'ok' if ok else 'failed'}")
            return {**out, "receipt": receipt, "receipt_sig": ctx.sign(receipt)}
        return handler

    async def _record(self, ctx, msg, head, kind, data, result) -> dict:
        """the computed result as a joint confirmation by this service alone; the ledger checks it may record that kind"""
        ev, subject, url = msg.get("event_id"), msg.get("subject"), msg.get("recorder_url")
        if not (ev and subject and url):
            return {"ok": False, "error": "recording a result needs event_id, subject and recorder_url"}
        trust = await ctx.recorder_trust(url)
        if not trust["ok"]:
            return {"ok": False, "error": f"recorder not proven: {trust.get('why')}"}
        group = head.group_id or msg.get("group_id")
        if not group:
            first = next((e for e in (await ctx.recorder(url).event_entries(ev)).get("entries", []) if e["type"] == "event"), None)
            group = (await ctx.recorder(url).verify(first["hash"])).get("group_id") if first else None
        p = {"event_id": ev, "kind": kind, "subject": subject, "value": {"input_hash": h(canon(data)), "result": result},
             "parties": [ctx.pub], "nonce": h(canon([ev, kind, subject, ctx.clock()]))[:16], "group_id": group,
             **({"ledger_id": trust["ledger_id"]} if trust.get("ledger_id") else {})}
        return await ctx.recorder(url).record("attest", p, {ctx.pub: ctx.sign(p)})
