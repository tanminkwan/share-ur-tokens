"""BrokerService: the board's rules. Mechanical only: signatures, expiry, audience labels, group grants, BM25.
It never judges who should get an opportunity; matching that needs judgement is a peer's job (recommend role)."""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterable

from ..connections import check_connections, check_operator
from ..config import ConfigError, Settings
from ..crypto import Identity, pen_name, verify
from ..search import BM25Searcher, Searcher
from .neighbors import Caller, HttpNeighbors, NeighborGateway
from .store import BrokerStore, FileBrokerStore, MemoryBrokerStore

log = logging.getLogger("arena.broker")
NOTICE_TEXT_FIELDS = ("title", "text", "kind")  # searched if present; every other notice field is the app's business


class BrokerService:
    def __init__(self, settings: Settings, identity: Identity, searcher: Searcher, neighbors_gw: NeighborGateway,
                 name: str | None = None, neighbors: Iterable[str] | None = None, owner_pub: str | None = None,
                 clock: Callable[[], float] = time.time, group_id: str | None = None, store: BrokerStore | None = None):
        self.settings, self.identity, self.searcher, self.gw, self.clock = settings, identity, searcher, neighbors_gw, clock
        self.name = name or settings.broker_name
        self.group_id = group_id or settings.broker_group_id or settings.genesis_group_id
        self.neighbors = list(settings.broker_neighbors if neighbors is None else neighbors)
        self.owner_pub = owner_pub if owner_pub is not None else settings.broker_owner_pub
        self.profiles: dict[str, dict] = {}
        self.notices: dict[str, dict] = {}
        self.notice_meta: dict[str, dict] = {}  # notice_id -> {"updated_at", "closed"}: kept outside the signed notice
        self.grants: dict[str, float] = {}
        self.store = store or MemoryBrokerStore()
        saved = self.store.load() or {}
        self.profiles.update(saved.get("profiles", {}))
        self.notices.update(saved.get("notices", {}))
        self.notice_meta.update(saved.get("notice_meta", {}))
        self.grants.update(saved.get("grants", {}))
        if self.group_id == settings.genesis_group_id and self.owner_pub is not None:
            raise ConfigError(f"the genesis group {self.group_id!r} is open to everyone and cannot have an owner")

    @classmethod
    def from_settings(cls, settings: Settings) -> "BrokerService":
        return cls(settings, Identity.load_or_create(settings.broker_key_file),
                   BM25Searcher(settings.bm25_k1, settings.bm25_b), HttpNeighbors(settings.neighbor_timeout_sec),
                   store=FileBrokerStore(settings.broker_state_file))

    def _persist(self) -> None:
        self.store.save({"profiles": self.profiles, "notices": self.notices, "notice_meta": self.notice_meta, "grants": self.grants})

    # ---- membership (closed peer group) ----
    @property
    def closed(self) -> bool:
        return self.owner_pub is not None

    def is_member(self, pub: str | None) -> bool:
        if not self.closed:
            return True
        return bool(pub) and (pub == self.owner_pub or self.grants.get(pub, 0) > self.clock())

    async def grant(self, grant: dict, sig: str) -> dict:
        """a membership grant with an expiry, signed by the group owner. No revocation: it just expires."""
        if not self.closed or not verify(self.owner_pub, grant, sig):
            return {"ok": False, "error": "grant must be signed by the group owner"}
        self.grants[grant["pub"]] = float(grant["until"])
        self._persist()
        return {"ok": True}

    # ---- profiles ----
    def _active(self, coll: dict) -> list[dict]:
        now = self.clock()
        return [x for x in coll.values() if x.get("until", 0) > now]

    async def advertise(self, ad: dict) -> dict:
        pub, prof = ad.get("pub", ""), ad.get("profile", {})
        if not verify(pub, prof, ad.get("sig", "")):
            return {"ok": False, "error": "bad signature"}
        bad = check_connections(prof["connections"]) if "connections" in prof else None
        if bad:
            return {"ok": False, "error": f"bad connection information: {bad}"}
        bad = check_operator(prof["operator"]) if "operator" in prof else None
        if bad:
            return {"ok": False, "error": bad}
        cb = prof.get("codebook")
        if cb is not None and (not isinstance(cb, dict) or set(cb) != {"entry", "publisher", "version"}):
            return {"ok": False, "error": "codebook must be {entry, publisher, version}"}
        if not self.is_member(pub):
            return {"ok": False, "error": "members of this peer group only"}
        updated = pub in self.profiles
        self.profiles[pub] = dict(prof, pub=pub)
        self._persist()
        log.info("%s: profile %s %s v%s", self.name, pen_name(pub, self.settings.pen_name_prefix, self.settings.pen_name_len),
                 "updated" if updated else "registered", prof.get("ver"))
        return {"ok": True, "updated": updated}

    async def list_profiles(self, caller: Caller, local: bool = False) -> list[dict] | None:
        if not self.is_member(caller.pub):
            return None
        out = [dict(p, broker=self.name, group_id=self.group_id) for p in self._active(self.profiles)]
        if not local:
            for url in self.neighbors:
                try:
                    out += await self.gw.list_profiles(url, caller)
                except Exception as e:
                    log.warning("%s: neighbor %s failed (%s), answering without it", self.name, url, e)
        return out

    def _k(self, k: int | None) -> int:
        return max(1, min(k or self.settings.search_k, self.settings.search_max_k))

    async def find(self, caller: Caller, q: str, role: str | None = None, labels: Iterable[str] = (),
                   exclude: Iterable[str] = (), k: int | None = None, local: bool = False) -> list[dict] | None:
        if not self.is_member(caller.pub):
            return None
        k, labels, exclude = self._k(k), list(labels), set(exclude)
        cands = [p for p in self._active(self.profiles) if p["pub"] not in exclude
                 and (not role or role in p.get("offers", [])) and all(l in p.get("labels", []) for l in labels)]
        ranked = self.searcher.rank(q, [f"{p['summary']} {' '.join(p.get('offers', []))}" for p in cands])
        s = self.settings
        hits = [dict(cands[i], offers=cands[i].get("offers", []), labels=cands[i].get("labels", []),
                     pen_name=pen_name(cands[i]["pub"], s.pen_name_prefix, s.pen_name_len), score=score, broker=self.name,
                     group_id=self.group_id)
                for i, score in ranked[:k]]
        if not local:
            query = {"q": q, "role": role, "labels": labels, "exclude": list(exclude), "k": k}
            for url in self.neighbors:
                try:
                    hits += await self.gw.find(url, caller, query)
                except Exception as e:
                    log.warning("%s: neighbor %s failed (%s), answering without it", self.name, url, e)
            best = {}
            for x in sorted(hits, key=lambda x: -x["score"]):
                best.setdefault(x["pub"], x)
            hits = list(best.values())[:k]
        return hits

    # ---- notices ----
    def _visible(self, notice: dict, labels: set) -> bool:
        """mechanical audience rule: every label the notice targets must be on the viewer's profile"""
        return all(f"{k}:{v}" in labels for k, v in notice.get("audience", {}).items())

    def _labels_of(self, pub: str) -> set | None:
        p = self.profiles.get(pub)
        return set(p.get("labels", [])) if p and p.get("until", 0) > self.clock() else None

    def _visible_now(self, pub: str) -> list[dict]:
        labels = self._labels_of(pub) or set()
        return [n for n in self._active(self.notices) if self._visible(n, labels)]

    async def post_notice(self, notice: dict, sig: str, shared: bool = False) -> dict:
        if not verify(notice.get("issuer_pub", ""), notice, sig):
            return {"ok": False, "error": "bad signature"}
        if notice.get("group_id") != self.group_id:  # the issuer signs which group the notice belongs to
            return {"ok": False, "error": "notice belongs to another group"}
        old = self.notices.get(notice["notice_id"])
        if old is not None:
            if old == notice:
                return {"ok": True, "visible_to": self._seen_by(notice), "unchanged": True}
            if old["issuer_pub"] != notice["issuer_pub"]:
                return {"ok": False, "error": "not the issuer"}
            if notice.get("ver", 1) <= old.get("ver", 1):
                return {"ok": False, "error": "older or same version"}
        self.notices[notice["notice_id"]] = dict(notice)
        self.notice_meta[notice["notice_id"]] = {"updated_at": self.clock(), "closed": False}
        self._persist()
        seen_by = self._seen_by(notice)
        log.info("%s: notice %s %s, visible to %d", self.name, notice["notice_id"], "received" if shared else "posted", seen_by)
        if not shared:
            for url in self.neighbors:
                try:
                    await self.gw.share_notice(url, notice, sig)
                except Exception as e:
                    log.warning("%s: sharing to %s failed (%s)", self.name, url, e)
        return {"ok": True, "visible_to": seen_by}

    def _seen_by(self, notice) -> int:
        return sum(self._visible(notice, set(p.get("labels", []))) for p in self._active(self.profiles))

    async def changed_notices(self, pub: str, since: float) -> dict | None:
        """notices posted, updated or closed after `since` that this viewer may see (closed ones included, marked)"""
        labels = self._labels_of(pub)
        if labels is None:
            return None
        now = self.clock()
        out = []
        for nid, n in self.notices.items():
            m = self.notice_meta.get(nid, {"updated_at": 0, "closed": False})
            if m["updated_at"] > since and self._visible(n, labels):
                out.append(dict(n, updated_at=m["updated_at"], closed=m["closed"] or n.get("until", 0) <= now))
        return {"notices": sorted(out, key=lambda x: x["updated_at"]), "now": now}

    async def close_notice(self, notice_id: str, sig: str, shared: bool = False) -> dict:
        n = self.notices.get(notice_id)
        if not n or not verify(n["issuer_pub"], {"close": notice_id}, sig):
            return {"ok": False, "error": "not the issuer"}
        n["until"] = self.clock()
        self.notice_meta[notice_id] = {"updated_at": self.clock(), "closed": True}
        self._persist()
        if not shared:
            for url in self.neighbors:
                try:
                    await self.gw.share_close(url, notice_id, sig)
                except Exception as e:
                    log.warning("%s: sharing close to %s failed (%s)", self.name, url, e)
        return {"ok": True}

    async def visible_notices(self, pub: str) -> list[dict] | None:
        """None = refused (no active profile on this broker)"""
        if self._labels_of(pub) is None:
            return None
        return self._visible_now(pub)

    async def search_notices(self, pub: str, q: str, k: int | None = None) -> list[dict] | None:
        visible = await self.visible_notices(pub)
        if visible is None:
            return None
        ranked = self.searcher.rank(q, [" ".join(str(n.get(f, "")) for f in NOTICE_TEXT_FIELDS) for n in visible])
        return [dict(visible[i], score=s) for i, s in ranked[:self._k(k)] if s > 0]

    def health(self) -> dict:
        return {"ok": True, "name": self.name, "group_id": self.group_id, "pub": self.identity.pub, "profiles": len(self._active(self.profiles)),
                "notices": len(self._active(self.notices)), "neighbors": self.neighbors, "closed": self.closed}
