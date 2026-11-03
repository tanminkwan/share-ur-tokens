"""Reveals: revealed values handled by code, never retyped by the LLM (P5-C32, C33, C35): finding reveal records in a
message, filling "공개:<handle>:<label>" references, checking every record against the ledger. One responsibility."""
from __future__ import annotations

import re

from .handles import Handles
from .ledger_view import LedgerView
from .state import commit_hash


class Reveals:
    KEYS = {"author", "label", "value", "salt", "publish_hash"}
    PARTIAL_KEYS = {"label", "value", "publish_hash"}  # a revealed value with its registration: a reveal record, even with fields missing
    REF = re.compile(r"^공개:(\S+):(\S+)$")

    def __init__(self, settings, handles: Handles, ledger: LedgerView):
        self.s, self.handles, self.ledger = settings, handles, ledger

    def records(self, obj) -> list[dict]:
        """every reveal record (the platform's fixed shape) inside obj, complete or not"""
        if isinstance(obj, dict):
            if self.KEYS <= set(obj) or (self.PARTIAL_KEYS <= set(obj) and set(obj) <= self.KEYS):
                return [obj]
            return [r for v in obj.values() for r in self.records(v)]
        if isinstance(obj, list):
            return [r for v in obj for r in self.records(v)]
        return []

    async def fill(self, ctx, st, obj):
        """"공개:<handle>:<label>" -> my own reveal record or one I received and the code checked; returns (obj, missing refs)"""
        missing = []

        async def one(x):
            if isinstance(x, dict) and self.PARTIAL_KEYS <= set(x) and set(x) <= self.KEYS and not self.KEYS <= set(x):
                ref = self.handles.expand(st, str(x["publish_hash"]).strip())
                prefix = ref[1:] if ref.startswith("#") else ref  # a short ref not seen yet is still the start of the hash
                on_ledger = next((e for e in await self.ledger.progress_entries(ctx, st)
                                  if e["type"] == "reveal" and str(e.get("commit", "")).startswith(prefix) and len(prefix) >= self.s.assistant_ref_len), None)
                if on_ledger:  # a partial record written by hand: completed exactly from the ledger reveal of that registration
                    return {"author": on_ledger["author"], "label": on_ledger["label"], "value": on_ledger["value"],
                            "salt": on_ledger["salt"], "publish_hash": on_ledger["commit"]}
                missing.append(f"불완전한 공개값(라벨 {x.get('label')}): 원장 공개가 없다")
                return x
            if isinstance(x, dict):
                return {k: await one(v) for k, v in x.items()}
            if isinstance(x, list):
                return [await one(v) for v in x]
            m = self.REF.match(x.strip()) if isinstance(x, str) else None
            if not m:
                return x
            who, label = self.handles.expand(st, m.group(1)), m.group(2)
            if who in (ctx.pub, ctx.pen) and label in st.secrets:
                s = st.secrets[label]
                return {"author": ctx.pub, "label": label, "value": s["value"], "salt": s["salt"], "publish_hash": s["publish_hash"]}
            if f"{who}|{label}" in st.reveals:
                return dict(st.reveals[f"{who}|{label}"])
            on_ledger = next((e for e in await self.ledger.progress_entries(ctx, st)
                              if e["type"] == "reveal" and e.get("author") == who and e.get("label") == label), None)
            if on_ledger:  # opened on the ledger: already checked by the ledger against the sealed hash
                return {"author": who, "label": label, "value": on_ledger["value"], "salt": on_ledger["salt"], "publish_hash": on_ledger["commit"]}
            missing.append(x)
            return x
        return await one(obj), missing

    async def verify(self, ctx, st, obj) -> list[tuple[bool, str]]:
        """every reveal record inside obj, checked against the ledger: published by its author, in this event, hash matches"""
        out = []
        for r in self.records(obj):
            if not self.KEYS <= set(r):
                out.append((False, f"라벨 {r.get('label')}: 불완전한 공개값 묶음({', '.join(sorted(self.KEYS - set(r)))} 없음)"))
                continue
            v = await ctx.recorder(st.recorder_url).verify(str(r["publish_hash"]))
            if not (v.get("exists") and v.get("type") == "publish" and v.get("author") == r["author"] and v.get("event_id") == st.event_id):
                out.append((False, f"라벨 {r['label']}: 그 등록이 원장에 없거나 다른 사람·다른 이벤트의 등록"))
            elif v.get("content_hash") != commit_hash(str(r["label"]), r["value"], str(r["salt"]), r["author"]):
                out.append((False, f"라벨 {r['label']}: 공개값이 먼저 등록한 해시와 맞지 않음"))
            else:
                out.append((True, f"라벨 {r['label']}: 일치"))
                if r["author"] != ctx.pub:  # kept by code, so it can be referred to as 공개:<handle>:<label> and never retyped
                    st.reveals[f"{r['author']}|{r['label']}"] = {k: r[k] for k in self.KEYS}
        return out

    def summary(self, ctx, st, obj, results) -> str:
        if not results:
            return ""
        bad = [why for ok, why in results if not ok]
        refs = [f"공개:{self.handles.handle(ctx, st, r['author'])}:{r['label']}" for r in self.records(obj) if f"{r['author']}|{r['label']}" in st.reveals]
        return ((f"\n[코드 확인] 공개값 {len(results)}건 모두 원장과 일치" if not bad
                 else f"\n[코드 확인] 공개값 {len(results)}건 중 원장과 맞지 않음: {'; '.join(bad)}")
                + (f"\n[코드 보관] 공동 확인 값에는 {', '.join(refs)} 처럼 쓰면 코드가 이 공개값 묶음을 그대로 넣는다" if refs else ""))
