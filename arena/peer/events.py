"""Events: announcing one (ledger declaration + notice, naming the app that runs it and how), and the built-in event
router that reads every broker group's changes and hands each event to the app it names."""
from __future__ import annotations

import asyncio
import os
import time

from ..crypto import canon, h
from .plugin import ASSISTANT_APP_ID, BaseApp, EventHandler, app_fingerprint, valid_run, version_ok


def _nonce(*parts) -> str:
    return h(canon([*parts, time.time(), os.urandom(8).hex()]))[:10]


async def announce_event(ctx, *, group: str, title: str, kind: str, rules: str, policy: dict, mode: str, apps: list | None = None,
                         audience: dict | None = None, recorder: dict | None = None, text: str | None = None,
                         elements: dict | None = None) -> dict:
    """declare the event on the ledger and post its notice. Separate blocks: rules (natural language), policy (roles),
    mode (how it runs) and apps (the app list block); the rules hash, mode and app list are notarized"""
    apps = list(apps or [])
    if not valid_run(mode, apps):
        raise ValueError(f"bad mode or app list: {mode} {apps}")
    broker = ctx.brokers[group]
    gid = await ctx.group_id(group)
    rec = recorder or (await broker.find("기록", role="record", identity=ctx.identity))["peers"][0]
    ev = "ev-" + _nonce(title)
    rules_hash = h(rules.encode())
    lid = await ctx.ledger_id(rec["recorder_url"])
    decl = {"event_id": ev, "issuer": ctx.pub, "kind": kind, "policy": policy, "approvers": [], "group_id": gid, "rules_hash": rules_hash,
            "mode": mode, "apps": apps, **({"elements": elements} if elements else {}), **({"ledger_id": lid} if lid else {})}
    r = await ctx.recorder(rec["recorder_url"]).record("event", decl, {ctx.pub: ctx.sign(decl)})
    if not r.get("ok"):
        raise RuntimeError(f"event declaration refused: {r.get('error')}")
    notice = {"notice_id": ev, "kind": kind, "title": title, "text": text or f"{title}: 규칙은 rules, 실행 방식은 mode, 쓰는 앱은 apps에 있다",
              "rules": rules, "policy": policy, "mode": mode, "apps": apps, "elements": dict(elements or {}), "until": ctx.clock() + ctx.settings.event_notice_ttl_sec, "issuer_pub": ctx.pub,
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

    def __init__(self, settings, installer=None):
        self.s = settings
        self.installer = installer  # optional: fetches apps an event names but this peer lacks (app_install.AppInstaller)
        self.since: dict[str, float] = {}
        self.seen: set[str] = set()
        self.routes: dict[str, dict] = {}  # event_id -> {"app_id", "ver", "closed"}

    async def start(self, ctx):
        self.load(ctx)
        if self.installer is not None:
            n = await self.installer.reload(ctx)
            if n:
                ctx.log.emit("apps", ctx.pen, f"설치해 둔 앱 {n}개를 다시 확인하고 불러옴")

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

    def choose(self, ctx, mode: str, apps: list) -> tuple[list, str | None]:
        """pure code, no LLM: which installed apps run an event of this mode and app list, or ([], reason)"""
        assistant = ctx.app_by_id(ASSISTANT_APP_ID)
        if mode == "assistant":
            return ([assistant], None) if assistant else ([], "기본 비서가 없음")
        ready, problems = [], []
        for ref in apps:
            app = ctx.app_by_id(ref["id"])
            if app is None:
                why = f"앱 {ref.get('name', '')}({ref['id']})이 설치되어 있지 않음"
            elif not version_ok(app.version, ref["version"]):
                why = f"앱 {app.name} 버전 {app.version}이 요구 버전 {ref['version']}에 맞지 않음"
            elif ref.get("hash") and app_fingerprint(app) != ref["hash"]:
                why = f"앱 {app.name}의 코드가 이벤트가 지정한 코드와 다름"
            else:
                ready.append(app)
                continue
            if ref.get("required", True):
                problems.append(why)
        handlers = [a for a in ready if isinstance(a, EventHandler)]
        if not problems and handlers:
            return handlers, None
        why = "; ".join(problems) or "목록에 이벤트를 받는 앱이 없음"
        if mode == "app_or_assistant" and assistant:
            return [assistant], None
        return [], why

    async def _route(self, ctx, n):
        ev = n["notice_id"]
        known = self.routes.get(ev)
        if known is not None:
            apps = [a for a in (ctx.app_by_id(i) for i in known["app_ids"]) if a is not None]
            change = None
            if n.get("closed") and not known.get("closed"):
                known["closed"], change = True, "closed"
            elif n.get("ver", 1) > known.get("ver", 1):
                known["ver"], change = n.get("ver", 1), "updated"
            for app in apps if change else []:
                await app.on_event(ctx.ctx_of(app), n, change)
            return
        if ev in self.seen or n.get("issuer_pub") == ctx.pub or n.get("closed") or not ("rules" in n or "mode" in n):
            return
        self.seen.add(ev)
        mode, apps = n.get("mode", "assistant"), n.get("apps", [])
        if not valid_run(mode, apps):
            ctx.log.emit("events", ctx.pen, f"이벤트 {ev}: 실행 방식이나 앱 목록이 잘못됨 → 무시")
            return
        trust = await ctx.recorder_trust(n["recorder_url"])
        if not trust["ok"] or (trust["anchored"] and n.get("recorder_pub") != trust["recorder"]):
            ctx.log.emit("events", ctx.pen, f"이벤트 {ev}: 기록자가 뿌리 신뢰로 증명되지 않음({trust.get('why') or '공지의 기록자 키가 지금 키와 다름'}) → 무시")
            return
        v = await ctx.recorder(n["recorder_url"]).verify(n["event_hash"])
        rules_ok = "rules" not in n or v.get("rules_hash") == h(n["rules"].encode())
        run_ok = ("mode" not in n) or (v.get("mode") == mode and v.get("apps") == apps)
        run_ok = run_ok and (v.get("elements") or {}) == (n.get("elements") or {})  # the elements block is notarized too
        if not (v.get("exists") and v.get("type") == "event" and v.get("event_id") == ev and v.get("issuer") == n["issuer_pub"] and rules_ok and run_ok):
            ctx.log.emit("events", ctx.pen, f"이벤트 {ev}: 공지의 규칙·실행 방식·앱 목록이 원장에 공증된 것과 다름 → 무시")
            return
        handlers, why = self.choose(ctx, mode, apps)
        missing = [r for r in apps if r.get("required", True) and ctx.app_by_id(r["id"]) is None]
        if not handlers and missing and self.installer is not None and mode != "assistant":
            if await self.installer.ensure(ctx, missing, n):
                handlers, why = self.choose(ctx, mode, apps)
        if not handlers:
            ctx.log.emit("events", ctx.pen, f"이벤트 {ev} '{n.get('title', '')}' 처리 불가: {why}")
            return
        self.routes[ev] = {"app_ids": [a.app_id for a in handlers], "ver": n.get("ver", 1), "closed": False}
        ctx.log.emit("events", ctx.pen, f"이벤트 {ev} → 앱 {', '.join(a.name for a in handlers)} (방식 {mode})")
        for app in handlers:
            await app.on_event(ctx.ctx_of(app), n, "new")
