"""The link peer's role (user 2026-11-03): a permanent, API-serving special-purpose peer. The ledger names a link of this
peer, which never changes; this peer keeps where the content is now, and only the publisher changes it (every version
signed by the owner, or the owner's current key after key rotation, asked of a recorder). It cannot change a link
itself: a reader checks the owner's signature. Anyone may run one and earns standing by being used.

    link.info                 -> {pub}: a ref names this link as {kind: link, peer: <this pub>, link_id}
    link.set {link}           a new version, signed (arena/content/links.py); ver = the last + 1
    link.get {id}             -> {link}: the newest version
    link.history {id}         -> {versions}: every version kept, oldest first"""
from __future__ import annotations

import os

from ..content.links import record_error, signer_allowed
from .link_store import LinkStore, SqliteLinkStore
from .plugin import BaseApp


class LinkRole(BaseApp):
    name, version, app_id = "platform.links", "1.0", "4e8d2a6c-1f3b-4c7e-9a5d-8b2f6e1c3a97"

    def __init__(self, settings, store: LinkStore | None = None):
        """store: where the links are kept (default: SQLite in this app's data folder, opened at start)"""
        self.s, self.store = settings, store

    async def start(self, ctx) -> None:
        if self.store is None:
            self.store = SqliteLinkStore(os.path.join(ctx.data_dir, "links.sqlite"))

    def offers(self):
        return ["영구 link"]

    def profile_extra(self):
        return {"link_peer": {"versions_kept": self.s.link_peer_history_max}}

    def ops(self):
        return {"link.info": self._info, "link.set": self._set, "link.get": self._get, "link.history": self._history}

    def _key_of(self, ctx):
        url = self.s.link_peer_recorder_url
        return (lambda pub: ctx.recorder(url).key(pub)) if url else None

    async def _info(self, ctx, msg, head):
        return {"ok": True, "pub": ctx.pub}

    async def _set(self, ctx, msg, head):
        rec = msg.get("link")
        bad = record_error(rec, self.s)
        if bad:
            return {"ok": False, "error": bad}
        versions = self.store.versions(rec["id"])
        last = versions[-1] if versions else None
        if rec["ver"] != (last["ver"] + 1 if last else 1):
            return {"ok": False, "error": f"ver must be {(last['ver'] + 1) if last else 1} (the last kept + 1)"}
        if last and (rec["owner"], rec["name"], rec.get("content_hash")) != (last["owner"], last["name"], last.get("content_hash")):
            return {"ok": False, "error": "a link keeps its owner, name and content hash; only its targets change"}
        if not last and self.store.count() >= self.s.link_peer_links_max:
            return {"ok": False, "error": "this link peer keeps no more links"}
        if not await signer_allowed(rec["owner"], rec["signer"], self._key_of(ctx)):
            return {"ok": False, "error": "only the link's owner (or the owner's current key) may change it"}
        self.store.append(rec, self.s.link_peer_history_max)
        ctx.log.emit("links", ctx.pen, f"link {rec['id'][:10]} v{rec['ver']} ({len(rec['targets'])}곳)")
        return {"ok": True, "id": rec["id"], "ver": rec["ver"], "peer": ctx.pub}

    def _versions(self, ctx, link_id) -> list:
        return self.store.versions(link_id) if isinstance(link_id, str) else []

    async def _get(self, ctx, msg, head):
        v = self._versions(ctx, msg.get("id"))
        return {"ok": True, "link": v[-1]} if v else {"ok": False, "error": "no such link here"}

    async def _history(self, ctx, msg, head):
        v = self._versions(ctx, msg.get("id"))
        return {"ok": True, "versions": v} if v else {"ok": False, "error": "no such link here"}
