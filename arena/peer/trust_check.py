"""RecorderTrust: is the recorder at a url the one this peer's root of trust proves? (P5-G6, G9, G10). One responsibility:
proving recorders. The trunk is proven by the root values in the settings; a branch chain through its chain_link in the
trunk (branches grow only from the trunk, so the proof is always one step). Without root values every recorder passes
(anchored False). A proven answer is kept per url."""
from __future__ import annotations

from typing import Callable

from ..ledger.trust import verify_link_entry, verify_trust


class RecorderTrust:
    def __init__(self, settings_of: Callable, recorder_of: Callable):
        """settings_of() gives the peer's current settings (read when checking, so a peer's settings may change)"""
        self.settings_of, self.recorder_of = settings_of, recorder_of
        self.cache: dict[str, dict] = {}

    @property
    def s(self):
        return self.settings_of()

    def _fail(self, why: str) -> dict:
        return {"ok": False, "anchored": bool(self.s.trust_genesis_hash), "why": why}

    async def check(self, url: str) -> dict:
        """{ok, anchored, recorder, ledger_id, why[, linked_from]}"""
        if url in self.cache:
            return self.cache[url]
        s = self.s
        try:
            doc = await self.recorder_of(url).trust()
        except Exception as e:
            return self._fail(f"{type(e).__name__}: {e}")
        if not s.trust_genesis_hash:
            out = {"ok": True, "anchored": False, "recorder": doc.get("recorder"), "ledger_id": doc.get("ledger_id")}
        elif (doc.get("genesis") or {}).get("hash") == s.trust_genesis_hash:
            ok, why, keys = verify_trust(doc, s.trust_genesis_hash, s.trust_god_pub)
            out = {"ok": ok, "anchored": True, "recorder": keys.get("recorder"), "ledger_id": doc.get("ledger_id") if ok else None, "why": why}
        else:
            out = await self._branch(doc)
        if out["ok"]:
            self.cache[url] = out
        return out

    async def _branch(self, doc: dict) -> dict:
        """a branch chain: its origin must be the trunk, the trunk proven, and the trunk's chain_link must name this chain"""
        s = self.s
        parent = ((doc.get("genesis") or {}).get("payload") or {}).get("parent")
        if not parent:
            return self._fail("not the trunk and not linked into it")
        if parent.get("ledger_id") != s.trust_genesis_hash:
            return self._fail("branches grow only from the trunk; this chain names another chain as its origin")
        pt = await self.check(parent["recorder_url"])
        if not pt["ok"] or pt["ledger_id"] != parent["ledger_id"]:
            return self._fail(f"parent chain not proven: {pt.get('why')}")
        try:
            trunk = self.recorder_of(parent["recorder_url"])
            pdoc = await trunk.trust()
            link = (await trunk.link(doc["genesis"]["hash"])).get("link")
        except Exception as e:
            return self._fail(f"parent recorder: {type(e).__name__}: {e}")
        pok, _, pkeys = verify_trust(pdoc, pt["ledger_id"], (pdoc.get("genesis") or {}).get("payload", {}).get("god", ""))
        bad = None if pok and pkeys.get("recorder") == pt["recorder"] else "the parent's trust document changed"
        bad = bad or verify_link_entry(link, pdoc, doc["genesis"])
        if bad:
            return self._fail(bad)
        ok, why, keys = verify_trust(doc, doc["genesis"]["hash"], doc["genesis"]["payload"]["god"])
        return {"ok": ok, "anchored": True, "recorder": keys.get("recorder"), "ledger_id": doc.get("ledger_id") if ok else None,
                "why": why, "linked_from": parent["ledger_id"]}
