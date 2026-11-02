"""The foundation peer's role (user 2026-11-02: "특수목적 peer에 agent arena foundation도 추가하자"; "필수는 아니지만
생태계를 견고하게 하기 위해 기본적인 걸 미리 정의하는 거지").

It publishes editions of the code table as `codebook` entries and hands out the document of each edition. It has no
power: its standing is how many events and profiles follow its editions, counted from the ledger. Anyone may run one,
or publish another table; following any edition is optional."""
from __future__ import annotations

from ..codebook import builtin_document, document_hash
from ..crypto import h
from .plugin import BaseApp


class FoundationRole(BaseApp):
    name, version, app_id = "platform.foundation", "1.0", "5c2e8f1a-7d4b-4e93-a6b0-3f9d1c8e2a57"

    def __init__(self, settings, documents: list[dict] | None = None):
        self.s = settings
        self.documents = {d["version"]: d for d in (documents or [builtin_document()])}
        self.published: dict[str, str] = {}   # version -> codebook entry hash

    def offers(self):
        return ["코드표 판"]

    def profile_extra(self):
        return {"codebook_editions": [{"name": d["name"], "version": v, "entry": self.published.get(v)} for v, d in sorted(self.documents.items())]}

    def ops(self):
        return {"codebook.get": self._get}

    async def start(self, ctx) -> None:
        self.published = dict(ctx.state.load().get("published", {}))
        if self.s.foundation_peer_recorder_url:
            for v in sorted(self.documents):
                if v not in self.published:
                    r = await self.publish(ctx, self.s.foundation_peer_recorder_url, v)
                    ctx.log.emit("foundation", ctx.pen, f"코드표 판 {v} 기록: {'#' + r['hash'][:10] if r.get('ok') else r.get('error')}")

    async def publish(self, ctx, recorder_url: str, version: str, supersedes: str | None = None) -> dict:
        """record one edition (signed by this peer) on the ledger at recorder_url"""
        d = self.documents[version]
        lid = await ctx.ledger_id(recorder_url)
        group = self.s.genesis_group_id  # an edition belongs to the whole ledger: the genesis group
        p = {"publisher": ctx.pub, "name": d["name"], "version": version, "content_hash": document_hash(d), "codes": d["codes"],
             "group_id": group, "nonce": h(f"{d['name']}|{version}".encode())[:16], **({"supersedes": supersedes} if supersedes else {}),
             **({"ledger_id": lid} if lid else {})}
        r = await ctx.recorder(recorder_url).record("codebook", p, {ctx.pub: ctx.sign(p)})
        if r.get("ok"):
            self.published[version] = r["hash"]
            ctx.state.save({"published": self.published})
        return r

    async def _get(self, ctx, msg, head):
        """the document of an edition (the latest when no version is asked); its hash is the edition's content_hash"""
        v = msg.get("version") or max(self.documents, key=lambda x: tuple(int(n) for n in x.split(".")))
        d = self.documents.get(v)
        if d is None:
            return {"ok": False, "error": f"no edition {v}"}
        return {"ok": True, "document": d, "content_hash": document_hash(d), "entry": self.published.get(v)}
