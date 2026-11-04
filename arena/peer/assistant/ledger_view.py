"""LedgerView: the event's progress as the ledger has it, read by code (one responsibility: reading the ledger for the
assistant): entries in public view, the roster, assignments, sealed rounds, open roles, the joint-confirmation precheck."""
from __future__ import annotations

import json

from .directory import Directory
from .handles import HEX64, Handles


class LedgerView:
    PEOPLE = ("author", "contractor", "issuer", "parties", "endorser")
    SIGNED_BY_ALL = ("attest", "contract")  # entries with more than one signer: the ledger records them only with every signature
    SETTLED_NOTE = "원장에 있는 항목은 필요한 서명이 모두 모여 확정된 것이다(코드 확인). 원장에 있는 공동 확인에 더 받을 서명은 없다."
    MINE = ("author", "issuer")
    WAKE_HOST = ("attest",)  # results are what a host collects; its own moves come by message or tool result

    def __init__(self, settings, handles: Handles, directory: Directory):
        self.s, self.handles, self.directory = settings, handles, directory

    async def progress_entries(self, ctx, st) -> list[dict]:
        """this event's entries in public view; everyone named in them joins the roster (so they show as handles)"""
        if not st.on_ledger:
            return []  # a broker group without a ledger: nothing to read
        try:
            r = await ctx.recorder(st.recorder_url).event_entries(st.event_id)
        except Exception:
            return []
        entries = r.get("entries", []) if r.get("ok") else []
        if "sealed" in st.elements:
            st.sealed_view = self.sealed_view(ctx, st, entries)
        if st.role == "host":
            await self.role_offers(ctx, st)
        for e in entries:
            if e["type"] == "assign":
                st.assignments.update(e.get("subjects", {}))
            if e["type"] == "attest":  # settled: requests and proposals I still hold for the same kind and subject are stale
                same = lambda x: x["payload"].get("kind") == e.get("kind") and x["payload"].get("subject") == e.get("subject")
                for box in (st.pending, st.proposals):
                    for k in [k for k, x in box.items() if same(x)]:
                        box.pop(k)
            for k in self.PEOPLE:
                for pub in (e.get(k) if isinstance(e.get(k), list) else [e.get(k)]):
                    if isinstance(pub, str) and HEX64.fullmatch(pub) and pub not in st.roster:
                        st.roster.append(pub)
        return entries

    async def role_offers(self, ctx, st):
        """host: the policy roles nobody holds yet, with the peers whose posted profile offers each (a service peer takes a
        role it advertises without applying; live with-elements run 2: the host never found the referee to contract)"""
        held = {c[0] for c in st.contracts}
        open_roles = [r for r in st.policy.get("roles", []) if r not in held]
        if not open_roles:
            st.role_offers = {}
            return
        profiles = await self.directory.profiles(ctx)
        st.role_offers = {r: [p["pub"] for p in profiles if r in p.get("offers", []) and p["pub"] != ctx.pub] for r in open_roles}

    def sealed_view(self, ctx, st, entries) -> list[str]:
        """for each sealed label of a subject I am assigned to: how many registered, and whether it may open (P6-D3)"""
        asg = {e2: v for e in entries if e["type"] == "assign" for e2, v in e.get("subjects", {}).items()}
        out = []
        for subject, parties in asg.items():
            if ctx.pub not in parties:
                continue
            labels = sorted({e["label"] for e in entries if e["type"] == "publish" and e.get("label")
                             and (e["label"] == subject or e["label"].rpartition("-")[0] == subject and e["label"].rpartition("-")[2].isdigit())})
            for label in labels:
                regs = {e["author"] for e in entries if e["type"] == "publish" and e.get("label") == label} & set(parties)
                opened = {e["author"] for e in entries if e["type"] == "reveal" and e.get("label") == label}
                state = f"공개 {len(opened)}/{len(parties)}" if opened else ("공개 가능" if len(regs) == len(parties) else "공개 기다림")
                out.append(f"봉인 {label}: 등록 {len(regs)}/{len(parties)}, {state}")
        return out

    async def progress_lines(self, ctx, st) -> list[str]:
        """one short line per entry, the latest ones only; handles and short refs instead of 64-hex"""
        return [self.progress_line(ctx, st, e) for e in (await self.progress_entries(ctx, st))[-self.s.assistant_progress_max:]]

    def progress_line(self, ctx, st, e) -> str:
        rest = {k: v for k, v in e.items() if k not in ("seq", "type", "hash", "rules_hash", "salt") and v not in (None, [], "")}
        mark = " · 서명 완료(당사자 전원, 원장 확정)" if e["type"] in self.SIGNED_BY_ALL else ""
        return self.handles.shorten(ctx, st, f"{e['seq']} {e['type']} {json.dumps(rest, ensure_ascii=False)}{mark} (항목 {e['hash']})")

    def concerns_me(self, ctx, st, e) -> bool:
        """a new ledger entry worth a turn: one naming me, or (host) a joint confirmation, or (participant, when the event has
        assignments) one by someone I share an assignment with or by the issuer; without assignments, every entry"""
        named = [e.get("contractor"), *(e.get("parties") or []), *[p for v in (e.get("subjects") or {}).values() for p in v]]
        if ctx.pub in named:
            return True
        if st.role == "host":
            return e["type"] in self.WAKE_HOST
        mates = {p for v in st.assignments.values() if ctx.pub in v for p in v} - {ctx.pub}
        if not st.assignments:
            return True
        return e.get("author") in mates or e.get("issuer") == st.issuer_pub or bool(set(e.get("parties") or []) & mates)

    async def attest_precheck(self, ctx, st, kind, subject, pubs) -> str | None:
        """the event policy's rules for a joint confirmation, checked by code before any signature request goes out"""
        pol, hd = st.policy, self.handles
        if pol.get("attest_kinds") and kind not in pol["attest_kinds"]:
            return f"이 이벤트가 허용하는 공동 확인 종류(kind)가 아니다: {kind} (허용: {', '.join(pol['attest_kinds'])})"
        need = pol.get("attest_roles", {}).get(kind)
        if need == "issuer" and pubs != [st.issuer_pub]:
            return f"'{kind}'는 개최자(issuer)가 혼자 기록하는 종류다. parties에는 개최자 한 명만 넣는다"
        entries = await self.progress_entries(ctx, st)  # contracts and assignments, as the ledger has them
        if need and need != "issuer":
            roles = {}
            for e in entries:
                if e["type"] == "contract" and e.get("contractor"):
                    roles.setdefault(e["contractor"], set()).add(e.get("role"))
            lacking = [hd.handle(ctx, st, p) for p in pubs if need not in roles.get(p, set())]
            if lacking:
                return f"'{kind}'의 당사자는 모두 '{need}' 역할 계약이 있어야 한다(role): {', '.join(lacking)}"
        if kind in pol.get("assigned_kinds", []):
            assigned = st.assignments.get(subject)
            if assigned is None:
                return f"'{subject}'는 배정(assign)되지 않은 주제다. 배정된 주제: {', '.join(st.assignments) or '없음'}"
            if sorted(pubs) != sorted(assigned):
                return (f"당사자가 '{subject}'에 배정(assign)된 사람과 다르다. 배정: "
                        f"{'·'.join(hd.handle(ctx, st, p) for p in assigned)}")
        return None
