"""Events: announcing one (ledger declaration + notice, naming the app that runs it and how), and the built-in event
router that reads every broker group's changes and hands each event to the app it names."""
from __future__ import annotations

import asyncio
import os
import time

from ..crypto import canon, h
from .plugin import ASSISTANT_APP_ID, BaseApp, EventHandler, app_fingerprint, assistant_spec, valid_app_spec, version_ok


def _nonce(*parts) -> str:
    return h(canon([*parts, time.time(), os.urandom(8).hex()]))[:10]


async def announce_event(ctx, *, group: str, title: str, kind: str, rules: str, policy: dict, app: dict, audience: dict | None = None,
                         recorder: dict | None = None, text: str | None = None) -> dict:
    """declare the event on the ledger (rules hash + app spec, notarized) and post its notice on the group's broker"""
    if not valid_app_spec(app):
        raise ValueError(f"bad app spec: {app}")
    broker = ctx.brokers[group]
    gid = await ctx.group_id(group)
    rec = recorder or (await broker.find("기록", role="record", identity=ctx.identity))["peers"][0]
    ev = "ev-" + _nonce(title)
    rules_hash = h(rules.encode())
    decl = {"event_id": ev, "issuer": ctx.pub, "kind": kind, "policy": policy, "approvers": [], "group_id": gid, "rules_hash": rules_hash, "app": app}
    r = await ctx.recorder(rec["recorder_url"]).record("event", decl, {ctx.pub: ctx.sign(decl)})
    if not r.get("ok"):
        raise RuntimeError(f"event declaration refused: {r.get('error')}")
    notice = {"notice_id": ev, "kind": kind, "title": title, "text": text or f"{title}: 규칙은 rules, 처리하는 앱과 방식은 app에 있다",
              "rules": rules, "policy": policy, "app": app, "until": ctx.clock() + ctx.settings.event_notice_ttl_sec, "issuer_pub": ctx.pub,
              "issuer_url": ctx.url, "event_hash": r["hash"], "recorder_pub": rec["pub"], "recorder_url": rec["recorder_url"], "group_id": gid,
              **({"audience": audience} if audience else {})}
    posted = await broker.post_notice(ctx.identity, notice)
    if not posted.get("ok"):
        raise RuntimeError(f"notice refused: {posted.get('error')}")
    return {"event_id": ev, "notice": notice, "event_hash": r["hash"], "recorder": rec, "group_id": gid, "rules_hash": rules_hash}


class EventRouter(BaseApp):
    """reads changes on every broker group I belong to; checks each event against its ledger declaration; hands it to
    the app the event names (by app_id, version and optional code hash) according to its mode"""
    name, version, app_id = "platform.events", "1.0", "342bb084-0d25-4d70-b2b3-10f3e77dacb5"

    def __init__(self, settings):
        self.s = settings
        self.since: dict[str, float] = {}
        self.seen: set[str] = set()
        self.routes: dict[str, dict] = {}  # event_id -> {"app_id", "ver", "closed"}

    async def start(self, ctx):
        self.load(ctx)

        async def loop():
            while True:
                try:
                    await self.watch_once(ctx)
                except Exception as e:
                    ctx.log.emit("events", ctx.pen, f"게시판 확인 실패: {type(e).__name__}: {e}")
                await asyncio.sleep(self.s.event_watch_sec)
        self._task = asyncio.create_task(loop())

    def load(self, ctx):
        st = ctx.state.load()
        self.since.update(st.get("since", {}))
        self.seen |= set(st.get("seen", []))
        self.routes.update(st.get("routes", {}))

    def _save(self, ctx):
        ctx.state.save({"since": self.since, "seen": sorted(self.seen), "routes": self.routes})

    async def watch_once(self, ctx):
        for group, broker in ctx.brokers.items():
            r = await broker.changed_notices(ctx.identity, self.since.get(group, 0.0))
            if not r.get("ok"):
                continue
            self.since[group] = r["now"]
            for n in r["notices"]:
                await self._route(ctx, n)
        self._save(ctx)

    def choose(self, ctx, spec: dict):
        """the app that runs an event of this spec here, or (None, reason)"""
        def named():
            app = ctx.app_by_id(spec["id"])
            if app is None:
                return None, f"앱 {spec.get('name', '')}({spec['id']})이 설치되어 있지 않음"
            if not version_ok(app.version, spec["version"]):
                return None, f"앱 {app.name} 버전 {app.version}이 요구 버전 {spec['version']}에 맞지 않음"
            if spec.get("hash") and app_fingerprint(app) != spec["hash"]:
                return None, f"앱 {app.name}의 코드가 이벤트가 지정한 코드와 다름"
            return app, None
        assistant = ctx.app_by_id(ASSISTANT_APP_ID)
        if spec["mode"] == "assistant":
            return (assistant, None) if assistant else (None, "기본 비서가 없음")
        app, why = named()
        if spec["mode"] == "app" or app is not None:
            return app, why
        return (assistant, None) if assistant else (None, why)

    async def _route(self, ctx, n):
        ev = n["notice_id"]
        known = self.routes.get(ev)
        if known is not None:
            app = ctx.app_by_id(known["app_id"])
            if app is None:
                return
            if n.get("closed") and not known.get("closed"):
                known["closed"] = True
                await app.on_event(ctx.ctx_of(app), n, "closed")
            elif n.get("ver", 1) > known.get("ver", 1):
                known["ver"] = n.get("ver", 1)
                await app.on_event(ctx.ctx_of(app), n, "updated")
            return
        if ev in self.seen or n.get("issuer_pub") == ctx.pub or n.get("closed") or not ("rules" in n or "app" in n):
            return
        self.seen.add(ev)
        spec = n.get("app") or assistant_spec()
        if not valid_app_spec(spec):
            ctx.log.emit("events", ctx.pen, f"이벤트 {ev}: 앱 지정이 잘못됨 → 무시")
            return
        v = await ctx.recorder(n["recorder_url"]).verify(n["event_hash"])
        rules_ok = "rules" not in n or v.get("rules_hash") == h(n["rules"].encode())
        app_ok = v.get("app") == n.get("app")
        if not (v.get("exists") and v.get("type") == "event" and v.get("event_id") == ev and v.get("issuer") == n["issuer_pub"] and rules_ok and app_ok):
            ctx.log.emit("events", ctx.pen, f"이벤트 {ev}: 공지의 규칙·앱 지정이 원장에 공증된 것과 다름 → 무시")
            return
        app, why = self.choose(ctx, spec)
        if app is None or not isinstance(app, EventHandler):
            ctx.log.emit("events", ctx.pen, f"이벤트 {ev} '{n.get('title', '')}' 처리 불가: {why or '이벤트를 받는 앱이 아님'}")
            return
        self.routes[ev] = {"app_id": app.app_id, "ver": n.get("ver", 1), "closed": False}
        ctx.log.emit("events", ctx.pen, f"이벤트 {ev} → 앱 {app.name} (방식 {spec['mode']})")
        await app.on_event(ctx.ctx_of(app), n, "new")
