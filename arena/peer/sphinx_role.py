"""The sphinx's role (dev/founding/requirements.md, user 2026-11-04: a special-purpose peer, the sphinx; "지금은 신청을 받으면
사람이 대면하고 OK를 하면 그룹생성을 해주는 역할").

A sphinx is a person's peer. Someone who wants to found a branch group applies with the key that will be its god
(signed, so the key is theirs), a short purpose and how to reach them. The person behind the sphinx meets them outside the
platform (a video call or face to face, through that contact) and says yes or no on the owner desk. Yes: a founding pass
(arena/ledger/founding.py) for that founder key only. The sphinx gives at most ARENA_SPHINX_CAP_COUNT passes in
ARENA_SPHINX_CAP_DAYS. Nothing personal goes on a ledger; the application stays in this peer's home.

    sphinx.info                                   -> {pub, cap, policy, delegated, issued_in_window, waiting}

The rules it follows (how many passes in how many days, how long a pass holds) come from the foundation when one is set
(ARENA_SPHINX_FOUNDATION_URL and _PUB: a signed founding policy, op founding.policy), else from this peer's settings: the
ledger does not enforce them, this code does (dev/founding requirements FG-A5, F7). Whether the trunk takes its passes
depends on god's delegate entry for its key line; it looks that up (ARENA_SPHINX_TRUNK_RECORDER_URL, F8) and tells its
person (a notice card) and its applicants.
    sphinx.apply {application: {founder, purpose, contact, ts}, sig}   sig: the founder key over application
                                                  -> {application_id, status: waiting}
    sphinx.status {application_id}                -> {status: waiting | passed | rejected | expired, pass?, why?}"""
from __future__ import annotations

import asyncio
import inspect
import os

from ..crypto import pen_name, verify
from ..ledger.founding import HEX64, make_pass, pass_body, policy_error
from .plugin import BaseApp

DAY = 86400.0
CHECKS = "확인할 것: 살아 있는 사람인가, 그 자리에서 한 요청(오늘의 말, 손동작, 주변 비추기 등)을 따랐는가, 목적이 플랫폼 규약에 어긋나지 않는가"


class SphinxRole(BaseApp):
    name, version, app_id = "platform.sphinx", "1.0", "5c7e2a91-4b3d-4f6e-9a18-2d7c0b5e8f34"

    def __init__(self, settings):
        self.s = settings
        self._tasks: dict[str, asyncio.Task] = {}
        self._from_foundation: dict | None = None   # the last founding policy that checked out
        self.delegated: bool | None = None          # None: not known (no trunk recorder set, or it did not answer)
        self._looked_at = float("-inf")
        self._told = None                           # what the person was last told, so a card comes only on a change

    def offers(self):
        return ["그룹 생성 허락"]

    def profile_extra(self):
        p = self.policy()
        return {"sphinx": {"found_branch": True, "cap": p["cap"], "pass_days": p["pass_days"], "policy": p["source"], "delegated": self.delegated}}

    # ---- the rules it follows, and whether the trunk takes its passes ----
    def policy(self) -> dict:
        """{cap: {count, days}, pass_days, source: foundation | settings, foundation?}"""
        f = self._from_foundation
        if f is not None:
            return {"cap": dict(f["cap"]), "pass_days": f["pass_days"], "source": "foundation", "foundation": f["foundation"]}
        return {"cap": {"count": self.s.sphinx_cap_count, "days": self.s.sphinx_cap_days}, "pass_days": self.s.sphinx_pass_days, "source": "settings"}

    async def refresh(self, ctx, force: bool = False) -> None:
        """ask the foundation for its policy and the trunk for this key's delegation, at most every ARENA_SPHINX_POLICY_REFRESH_SEC"""
        now = ctx.clock()
        if not force and now - self._looked_at < self.s.sphinx_policy_refresh_sec:
            return
        self._looked_at = now
        if self.s.sphinx_foundation_url:
            try:
                r = await ctx.call(self.s.sphinx_foundation_url, {"op": "founding.policy"})
                doc = r.get("policy")
                why = r.get("error") if not r.get("ok") else policy_error(doc, foundation=self.s.sphinx_foundation_pub)
            except Exception as e:  # noqa: BLE001  (an unreachable foundation leaves the last policy that checked out)
                why = type(e).__name__
            if why:
                ctx.log.emit("sphinx", ctx.pen, f"foundation 기준을 받지 못함: {why}")
            else:
                self._from_foundation = doc["body"]
        if self.s.sphinx_trunk_recorder_url:
            try:
                d = await ctx.recorder(self.s.sphinx_trunk_recorder_url).delegates()
                self.delegated = any(x["current"] == ctx.pub and x["scope"] == "found_branch" for x in d.get("delegates", [])) if d.get("ok") else None
            except Exception:  # noqa: BLE001
                self.delegated = None
        self._tell(ctx)

    def _tell(self, ctx) -> None:
        p = self.policy()
        told = (p["source"], p.get("foundation"), p["cap"]["count"], p["cap"]["days"], p["pass_days"], self.delegated)
        if told == self._told or not hasattr(ctx.owner, "notify"):
            return
        if not (self.s.sphinx_foundation_url or self.s.sphinx_trunk_recorder_url):
            return  # nothing to tell: its own settings, delegation unknown (the window shows that in sphinx.info)
        self._told = told
        where = f"foundation {self._pen(ctx, p['foundation'])}" if p["source"] == "foundation" else "이 peer의 설정"
        state = {True: "위임됨: 뿌리 원장이 이 스핑크스의 통과 증명서를 받는다", False: "위임 안 됨: 뿌리 원장이 이 스핑크스의 증명서를 받지 않는다",
                 None: "위임 여부를 알 수 없음(뿌리 기록자 주소가 없거나 답하지 않음)"}[self.delegated]
        ctx.owner.notify("notice", f"스핑크스 · {state.split(':')[0]}",
                         f"{state}\n기준: {where} · {p['cap']['days']:g}일에 {p['cap']['count']}개 · 증명서 {p['pass_days']:g}일")

    def ops(self):
        return {"sphinx.info": self._info, "sphinx.apply": self._apply, "sphinx.status": self._status}

    async def start(self, ctx):
        """after a restart, the person is asked again about applications still waiting (desk questions closed then)"""
        await self.refresh(ctx, force=True)
        for aid, a in ctx.state.load().get("applications", {}).items():
            if a["status"] == "waiting":
                self._decide_later(ctx, aid)

    # ---- the state ----
    def _issued_in_window(self, state: dict, now: float) -> int:
        since = now - self.policy()["cap"]["days"] * DAY
        return sum(1 for t in state.get("issued", []) if t > since)

    def _application_error(self, ctx, app, sig) -> str | None:
        if not isinstance(app, dict) or set(app) != {"founder", "purpose", "contact", "ts"}:
            return "an application is {founder, purpose, contact, ts}, signed by the founder key"
        if not isinstance(app["founder"], str) or not HEX64.fullmatch(app["founder"]):
            return "founder is the public key that will be the branch's god"
        for k in ("purpose", "contact"):
            if not isinstance(app[k], str) or not app[k].strip() or len(app[k]) > self.s.sphinx_purpose_max:
                return f"{k} is a short text (1..{self.s.sphinx_purpose_max} characters)"
        if not isinstance(app["ts"], (int, float)) or abs(ctx.clock() - app["ts"]) > self.s.sig_window_sec:
            return "the application must be signed now"
        if not verify(app["founder"], app, sig or ""):
            return "the application must be signed by the founder key"
        return None

    # ---- ops ----
    async def _info(self, ctx, msg, head):
        state = ctx.state.load()
        waiting = sum(1 for a in state.get("applications", {}).values() if a["status"] == "waiting")
        await self.refresh(ctx)
        p = self.policy()
        return {"ok": True, "pub": ctx.pub, "cap": p["cap"], "policy": p, "delegated": self.delegated,
                "issued_in_window": self._issued_in_window(state, ctx.clock()), "waiting": waiting}

    async def _apply(self, ctx, msg, head):
        app, sig = msg.get("application"), msg.get("sig")
        bad = self._application_error(ctx, app, sig)
        if bad:
            return {"ok": False, "error": bad}
        await self.refresh(ctx)
        cap = self.policy()["cap"]
        state = ctx.state.load()
        apps = state.setdefault("applications", {})
        same = next((k for k, a in apps.items() if a["founder"] == app["founder"] and a["status"] == "waiting"), None)
        if same:
            return {"ok": True, "application_id": same, "status": "waiting", "note": "already waiting for this founder"}
        held = next((k for k, a in apps.items() if a["founder"] == app["founder"] and a["status"] == "passed"
                     and a["pass"]["body"]["until"] > ctx.clock()), None)
        if held:
            return {"ok": True, "application_id": held, "status": "passed", "note": "this founder already holds a valid pass"}
        if self._issued_in_window(state, ctx.clock()) >= cap["count"]:
            return {"ok": False, "error": f"this sphinx has given its {cap['count']} passes for {cap['days']:g} days; apply later"}
        aid = os.urandom(8).hex()
        apps[aid] = {**app, "status": "waiting", "applied_at": ctx.clock()}
        ctx.state.save(state)
        ctx.log.emit("sphinx", ctx.pen, f"그룹 생성 신청 {aid}: {self._pen(ctx, app['founder'])}")
        self._decide_later(ctx, aid)
        note = "the person behind this sphinx will reach you through your contact and meet you before deciding"
        if self.delegated is False:
            note += "; this sphinx is not delegated now, so the trunk would not take its pass"
        return {"ok": True, "application_id": aid, "status": "waiting", "note": note}

    async def _status(self, ctx, msg, head):
        a = ctx.state.load().get("applications", {}).get(msg.get("application_id"))
        if a is None:
            return {"ok": False, "error": "no such application"}
        return {"ok": True, "status": a["status"], **{k: a[k] for k in ("pass", "why") if k in a}}

    # ---- the person decides ----
    def _pen(self, ctx, pub: str) -> str:
        return pen_name(pub, self.s.pen_name_prefix, self.s.pen_name_len)

    def _decide_later(self, ctx, aid: str) -> None:
        if aid not in self._tasks or self._tasks[aid].done():
            self._tasks[aid] = asyncio.create_task(self._decide(ctx, aid))

    async def _ask(self, ctx, question: str, context: str):
        ask = ctx.owner.ask
        if "timeout" in inspect.signature(ask).parameters:  # the desk waits as long as a meeting may take
            return await ask(question, context, timeout=self.s.sphinx_decide_wait_sec)
        return await ask(question, context)

    async def _decide(self, ctx, aid: str) -> None:
        a = ctx.state.load()["applications"][aid]
        answer = await self._ask(ctx, f"그룹 생성 신청: {self._pen(ctx, a['founder'])}. 신청자를 직접 만나 확인했습니까? 승인할까요?",
                                 f"founder 공개키: {a['founder']}\n목적: {a['purpose']}\n연락처: {a['contact']}\n\n"
                                 f"연락처로 신청자에게 연락해 영상 통화나 대면으로 만난 뒤 정합니다. {CHECKS}")
        state = ctx.state.load()  # read again: other applications may have changed meanwhile
        a, now = state["applications"][aid], ctx.clock()
        if not getattr(answer, "answered", True):
            a["status"], a["why"] = "expired", "the person did not decide in time; apply again"
        elif not answer.yes:
            a["status"], a["why"] = "rejected", answer.why
        elif self._issued_in_window(state, now) >= self.policy()["cap"]["count"]:
            a["status"], a["why"] = "rejected", "the passes of this period are used up; apply later"
        else:
            body = pass_body(a["founder"], ctx.pub, now, now + self.policy()["pass_days"] * DAY, os.urandom(16).hex())
            a["status"], a["pass"] = "passed", make_pass(body, ctx.sign(body))
            state.setdefault("issued", []).append(now)
        a["decided_at"] = now
        ctx.state.save(state)
        ctx.log.emit("sphinx", ctx.pen, f"그룹 생성 신청 {aid}: {a['status']}")
