"""The advanced search role (a default serving ctx): keeps broker profiles and notices as embedding vectors and finds
the closest ones for a query. Visibility follows the broker's own rules: closed groups only for their members, notices
only for askers whose profile labels match the notice audience."""
from __future__ import annotations

import asyncio

from ..crypto import canon, h
from ..embedding import EmbedError, Embedder
from ..signing import SignatureError, verify_message
from ..vector import MemoryVectorIndex, VectorIndex
from .plugin import BaseApp, MessageHead

ROLE = "search"
SEP = "|"


def profile_text(p: dict) -> str:
    return " ".join(x for x in (p.get("summary", ""), " ".join(p.get("offers", [])), " ".join(p.get("labels", []))) if x)


def notice_text(n: dict) -> str:
    return " ".join(str(n[f]) for f in ("title", "text", "kind") if n.get(f))


def visible(notice: dict, labels) -> bool:
    return all(f"{k}:{v}" in labels for k, v in notice.get("audience", {}).items())


class SearchRole(BaseApp):
    name, version, app_id = "search", "1.0", "494f468e-1a43-4341-b63a-fb4d92e824ff"

    def __init__(self, embedder: Embedder, settings, index: VectorIndex | None = None):
        self.embedder, self.settings, self.index = embedder, settings, index or MemoryVectorIndex()
        self.closed: dict[str, bool] = {}
        self.synced_at: dict[str, float] = {}

    def offers(self):
        return [ROLE]

    def ops(self):
        return {"search_profiles": self._search_profiles, "search_notices": self._search_notices, "search_status": self._status}

    async def start(self, ctx):
        async def loop():
            while True:
                try:
                    await self.sync(ctx)
                except Exception as e:  # keep serving with the index we have
                    ctx.log.emit("search", ctx.pen, f"색인 갱신 실패: {type(e).__name__}: {e}")
                await asyncio.sleep(self.settings.search_sync_sec)
        self._task = asyncio.create_task(loop())

    # ---- indexing ----
    async def _fetch(self, ctx, group, broker):
        self.closed[group] = bool((await broker.health()).get("closed"))
        pr = await broker.list_profiles(identity=ctx.identity)
        if not pr.get("ok"):
            raise RuntimeError(pr.get("error"))
        ns = await broker.list_notices(ctx.identity)
        items = {f"{group}{SEP}profile{SEP}{p['pub']}": ("profile", p, str(p.get("ver")), profile_text(p)) for p in pr["profiles"]}
        items.update({f"{group}{SEP}notice{SEP}{n['notice_id']}": ("notice", n, h(canon(n)), notice_text(n)) for n in ns.get("notices", [])})
        return items

    async def sync(self, ctx) -> dict:
        report = {}
        for group, broker in ctx.brokers.items():
            r = report[group] = {"added": 0, "updated": 0, "removed": 0}
            try:
                items = await self._fetch(ctx, group, broker)
            except Exception as e:
                r["error"] = f"{type(e).__name__}: {e}"
                continue
            prefix = group + SEP
            stale = [k for k in self.index.keys() if k.startswith(prefix) and k not in items]
            todo = [(k, v) for k, v in items.items() if (self.index.get(k) or (None, {}))[1].get("stamp") != v[2]]
            try:
                vecs = await self.embedder.embed([v[3] for _, v in todo]) if todo else []
            except EmbedError as e:
                r["error"] = str(e)
                ctx.log.emit("search", ctx.pen, f"임베딩 서비스 실패, 색인 갱신을 미룸: {e}")
                continue
            for (k, (kind, item, stamp, _)), vec in zip(todo, vecs):
                r["updated" if self.index.get(k) else "added"] += 1
                self.index.upsert(k, vec, {"group": group, "kind": kind, "item": item, "stamp": stamp})
            for k in stale:
                self.index.remove(k)
                r["removed"] += 1
            self.synced_at[group] = ctx.clock()
        return report

    # ---- queries ----
    def _caller(self, ctx, msg, required):
        if not required and "sig" not in msg:
            return None
        return verify_message(msg, now=ctx.clock(), window=ctx.settings.sig_window_sec)

    def _profile_in(self, group, pub):
        row = self.index.get(f"{group}{SEP}profile{SEP}{pub}") if pub else None
        return row[1]["item"] if row else None

    def _groups(self, ctx, caller, asked):
        return [g for g in ctx.brokers if (not asked or g == asked) and (not self.closed.get(g) or self._profile_in(g, caller))]

    async def _query(self, q, k, where):
        k = max(1, min(int(k or self.settings.search_k), self.settings.search_max_k))
        vec = (await self.embedder.embed([q]))[0]
        return [(score, meta) for _, score, meta in self.index.search(vec, k, where) if score >= self.settings.search_min_score]

    async def _search_profiles(self, ctx, msg, head: MessageHead):
        try:
            caller = self._caller(ctx, msg, required=False)
        except SignatureError as e:
            return {"ok": False, "error": str(e)}
        groups = set(self._groups(ctx, caller, msg.get("group")))
        role, labels = msg.get("role"), set(msg.get("labels", []))
        exclude = set(msg.get("exclude", [])) | {ctx.pub}  # the search peer is found on the broker by role, not here

        def where(m):
            p = m["item"]
            return (m["kind"] == "profile" and m["group"] in groups and p["pub"] not in exclude
                    and (not role or role in p.get("offers", [])) and labels <= set(p.get("labels", [])))
        try:
            hits = await self._query(msg.get("q", ""), msg.get("k"), where)
        except EmbedError as e:
            return {"ok": False, "error": f"embedding failed: {e}"}
        return {"ok": True, "hits": [dict(m["item"], score=round(s, 4), group=m["group"]) for s, m in hits]}

    async def _search_notices(self, ctx, msg, head: MessageHead):
        try:
            caller = self._caller(ctx, msg, required=True)
        except SignatureError as e:
            return {"ok": False, "error": f"signed request required: {e}"}
        labels = {g: set(p.get("labels", [])) for g in self._groups(ctx, caller, msg.get("group")) if (p := self._profile_in(g, caller))}

        def where(m):
            return m["kind"] == "notice" and m["group"] in labels and visible(m["item"], labels[m["group"]])
        try:
            hits = await self._query(msg.get("q", ""), msg.get("k"), where) if labels else []
        except EmbedError as e:
            return {"ok": False, "error": f"embedding failed: {e}"}
        return {"ok": True, "hits": [dict(m["item"], score=round(s, 4), group=m["group"]) for s, m in hits]}

    async def _status(self, ctx, msg, head: MessageHead):
        groups = {}
        for g in ctx.brokers:
            keys = [k for k in self.index.keys() if k.startswith(g + SEP)]
            groups[g] = {"profiles": sum(f"{SEP}profile{SEP}" in k for k in keys), "notices": sum(f"{SEP}notice{SEP}" in k for k in keys),
                         "closed": self.closed.get(g), "synced_at": self.synced_at.get(g)}
        return {"ok": True, "groups": groups, "dim": getattr(self.embedder, "dim", None)}
