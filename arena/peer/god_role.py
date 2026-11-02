"""The god role (the ctx that starts the ecosystem with the genesis, and its spectator): with a key the recorder allow-listed, it reads whole ledgers,
audits them itself and computes generic statistics and per-ctx strengths and track records. It cannot write, cannot
see content (only hashes are on the ledger) and cannot re-identify anyone."""
from __future__ import annotations

from ..crypto import pen_name
from ..ledger import audit_chain
from ..signing import SignatureError, verify_message
from ..stats import ledger_stats, per_peer
from .plugin import BaseApp, MessageHead


class GodRole(BaseApp):
    name, version, app_id = "god", "1.0", "caaa8085-5e8b-4581-8383-75ba77e30126"

    def __init__(self, settings, viewers=None):
        self.settings = settings
        self.viewers = set(settings.god_viewers if viewers is None else viewers)
        self.recorders: list[dict] = []
        self._cache, self._alerted = (0.0, None), False

    def ops(self):
        return {"god_snapshot": self._op_snapshot}

    def invalidate(self):
        self._cache = (0.0, None)

    async def locate(self, ctx) -> list[dict]:
        found = {}
        for broker in ctx.brokers.values():
            r = await broker.find("record", role="record", k=self.settings.search_max_k, identity=ctx.identity)
            for hit in r.get("peers", []):
                if hit.get("recorder_url"):
                    found[hit["recorder_url"]] = hit
        self.recorders = list(found.values())
        return self.recorders

    async def read(self, ctx, url, identity=None):
        return await ctx.recorder(url).read_chain(identity or ctx.identity)

    async def snapshot(self, ctx) -> dict:
        now = ctx.clock()
        if self._cache[1] is not None and now - self._cache[0] < self.settings.god_cache_sec:
            return self._cache[1]
        if not self.recorders:
            await self.locate(ctx)
        copies, access = [], []
        for rec in self.recorders:
            client = ctx.recorder(rec["recorder_url"])
            r = await client.read_chain(ctx.identity)
            if r.get("ok"):
                copies.append((rec, r["chain"]))
                log = await client.read_access_log(ctx.identity)
                access += [dict(x, recorder=rec["pub"]) for x in log.get("log", [])]
        if not copies:
            return {"ok": False, "error": "no readable recorder"}
        integ = [{"recorder": rec["pub"], "status": audit_chain(ch), "length": len(ch), "head": ch[-1]["hash"] if ch else ""} for rec, ch in copies]
        agree = all(x["status"] == "ok" for x in integ) and len({x["head"] for x in integ}) == 1
        if not agree and not self._alerted:
            self._alerted = True
            ctx.log.emit("god", ctx.pen, f"원장 변조 또는 기록자 간 불일치 탐지: {integ}")
        profiles = []
        for group, broker in ctx.brokers.items():
            r = await broker.list_profiles(identity=ctx.identity)
            profiles += [dict(p, group=group) for p in r.get("profiles", [])]
        chain = copies[0][1]
        pen = lambda pub: pen_name(pub, self.settings.pen_name_prefix, self.settings.pen_name_len)
        snap = {"ok": True, "integrity": {"recorders": integ, "agree": agree},
                "stats": ledger_stats(chain, self.settings.god_top_flows, self.settings.genesis_group_id), "peers": per_peer(chain, profiles, pen),
                "access": access}
        self._cache = (now, snap)
        return snap

    async def _op_snapshot(self, ctx, msg, head: MessageHead):
        try:
            who = verify_message(msg, now=ctx.clock(), window=ctx.settings.sig_window_sec)
        except SignatureError as e:
            return {"ok": False, "error": str(e)}
        if who not in self.viewers:
            return {"ok": False, "error": "not a viewer"}
        return {"ok": True, "snapshot": await self.snapshot(ctx)}
