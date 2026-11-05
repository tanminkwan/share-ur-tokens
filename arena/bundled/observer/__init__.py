"""The observer window (bundled app, not required; user 2026-11-05: "관전 peer의 화면은 내가 계속 보고 있을 테니 dashboard 부분은
자동 refresh 되게"). The god peer's screen: what the whole ledger holds, whether every recorder's copy checks out, the latest
entries, the events, and each peer's strengths and track record (the god_snapshot the god role computes). It only reads
(the god cannot write, cannot see content, cannot re-identify anyone) and asks again every ARENA_OBSERVER_POLL_MS, so the
person who keeps it open sees the world change without reloading. A local web window; the peer core has no screen."""
from __future__ import annotations

from ...crypto import pen_name
from ..peer_kinds import kind_view
from ..web import LocalWebApp
from .api import build_observer_api


class ObserverApp(LocalWebApp):
    name, version, app_id = "bundled.observer", "1.0", "025781c4-5cf0-401b-a4bc-5c3d2f7709fb"

    def __init__(self, god, settings, host: str, port: int, token: str, kind: str = "observer"):
        super().__init__(host, port, token)
        self.god, self.s, self.kind = god, settings, kind  # god: the GodRole whose snapshot this window shows
        self._ctx = None

    def web_app(self, ctx):
        self._ctx = ctx
        return build_observer_api(self, self.token)

    def pen(self, pub: str) -> str:
        return pen_name(pub, self.s.pen_name_prefix, self.s.pen_name_len)

    def config(self) -> dict:
        return {"poll_ms": self.s.observer_poll_ms}

    def me(self) -> dict:
        c = self._ctx
        return {"pen": c.pen, "pub": c.identity.pub, "operator": "observer", "llm": False, **kind_view(self.kind)}

    async def view(self) -> dict:
        """the snapshot for the window, with a pen name for every public key it mentions (the window shows names, not keys)"""
        snap = await self.god.snapshot(self._ctx)
        if not snap.get("ok"):
            return {"ok": False, "error": snap.get("error", "no snapshot"), "as_of": self._ctx.clock()}
        pubs = {p["pub"] for p in snap["peers"]} | {e["issuer"] for e in snap["stats"]["events"]}
        pubs |= {x for e in snap["stats"]["events"] for x in e["endorsers"]}
        pubs |= {x for f in snap["stats"]["top_flows"] for x in (f["from"], f["to"])}
        pubs |= {a["reader"] for a in snap["access"]}
        return {"ok": True, "snapshot": snap, "names": {pub: self.pen(pub) for pub in pubs}, "as_of": self._ctx.clock()}
