"""The spectator overseer role (a default serving peer): with a key the recorder allow-listed, it reads whole ledgers,
audits them itself and computes generic statistics and per-peer strengths and track records. It cannot write, cannot
see content (only hashes are on the ledger) and cannot re-identify anyone."""
from __future__ import annotations

from ..crypto import pen_name
from ..ledger import audit_chain
from ..signing import SignatureError, verify_message
from ..stats import ledger_stats, per_peer
from .app import PeerApp


class OverseerRole(PeerApp):
    name = "overseer"

    def __init__(self, settings, viewers=None):
        self.settings = settings
        self.viewers = set(settings.overseer_viewers if viewers is None else viewers)
        self.recorders: list[dict] = []
        self._cache, self._alerted = (0.0, None), False

    def ops(self):
        return {"overseer_snapshot": self._op_snapshot}

    def invalidate(self):
        self._cache = (0.0, None)

    async def locate(self, peer) -> list[dict]:
        found = {}
        for broker in peer.brokers.values():
            r = await broker.find("record", role="record", k=self.settings.search_max_k, identity=peer.identity)
            for hit in r.get("peers", []):
                if hit.get("recorder_url"):
                    found[hit["recorder_url"]] = hit
        self.recorders = list(found.values())
        return self.recorders

    async def read(self, peer, url, identity=None):
        return await peer.recorder(url).read_chain(identity or peer.identity)

    async def snapshot(self, peer) -> dict:
        now = peer.clock()
        if self._cache[1] is not None and now - self._cache[0] < self.settings.overseer_cache_sec:
            return self._cache[1]
        if not self.recorders:
            await self.locate(peer)
        copies, access = [], []
        for rec in self.recorders:
            client = peer.recorder(rec["recorder_url"])
            r = await client.read_chain(peer.identity)
            if r.get("ok"):
                copies.append((rec, r["chain"]))
                log = await client.read_access_log(peer.identity)
                access += [dict(x, recorder=rec["pub"]) for x in log.get("log", [])]
        if not copies:
            return {"ok": False, "error": "no readable recorder"}
        integ = [{"recorder": rec["pub"], "status": audit_chain(ch), "length": len(ch), "head": ch[-1]["hash"] if ch else ""} for rec, ch in copies]
        agree = all(x["status"] == "ok" for x in integ) and len({x["head"] for x in integ}) == 1
        if not agree and not self._alerted:
            self._alerted = True
            peer.log.emit("overseer", peer.pen, f"원장 변조 또는 기록자 간 불일치 탐지: {integ}")
        profiles = []
        for group, broker in peer.brokers.items():
            r = await broker.list_profiles(identity=peer.identity)
            profiles += [dict(p, group=group) for p in r.get("profiles", [])]
        chain = copies[0][1]
        pen = lambda pub: pen_name(pub, self.settings.pen_name_prefix, self.settings.pen_name_len)
        snap = {"ok": True, "integrity": {"recorders": integ, "agree": agree},
                "stats": ledger_stats(chain, self.settings.overseer_top_flows), "peers": per_peer(chain, profiles, pen),
                "access": access}
        self._cache = (now, snap)
        return snap

    async def _op_snapshot(self, peer, msg):
        try:
            who = verify_message(msg, now=peer.clock(), window=peer.settings.sig_window_sec)
        except SignatureError as e:
            return {"ok": False, "error": str(e)}
        if who not in self.viewers:
            return {"ok": False, "error": "not a viewer"}
        return {"ok": True, "snapshot": await self.snapshot(peer)}
