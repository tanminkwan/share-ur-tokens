"""LinkPeers (one job): keep a work's permanent link at one or more link peers, move it, and find where it is now.

The link id comes from the author's key and the work's name, so it is the same at every link peer. Moving the work
signs a new version at each one (each keeps its own version count). Finding it asks every link peer, keeps only
versions the owner's current key signed, and takes the newest by its signed time: a link peer that serves an old
version, forges one or is unreachable is outvoted and named in the answer."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..crypto import Identity
from .links import KeyOf, link_id, make_link, verify_link

Ask = Callable[[dict], Awaitable[dict]]


@dataclass(frozen=True)
class LinkPeer:
    ask: Ask                 # one message to the link peer (its api or a2a binding)
    via: str | None = None   # where it is reached now (a hint written next to the link)


class LinkPeers:
    def __init__(self, peers: list[LinkPeer], settings, clock: Callable[[], float] = time.time):
        if not peers:
            raise ValueError("at least one link peer")
        self.peers, self.s, self.clock = list(peers), settings, clock

    @staticmethod
    async def _try(peer: LinkPeer, msg: dict) -> dict:
        try:
            return await peer.ask(msg)
        except Exception as e:  # noqa: BLE001  (one link peer down must not stop the others)
            return {"ok": False, "error": f"unreachable: {type(e).__name__}: {e}"}

    async def _put(self, peer: LinkPeer, me: Identity, owner: str, name: str, targets: list[dict], content_hash: str | None) -> dict:
        cur = await self._try(peer, {"op": "link.get", "id": link_id(owner, name)})
        ver = cur["link"]["ver"] + 1 if cur.get("ok") else 1
        return await self._try(peer, {"op": "link.set", "link": make_link(me, owner, name, ver, targets, self.clock(), content_hash)})

    async def create(self, me: Identity, name: str, targets: list[dict], content_hash: str | None = None) -> dict:
        """-> {ok, links: [{peer, id, via?}], places: the ref's storage entries} (ok when at least one link peer took it)"""
        links, failed = [], []
        for p in self.peers:
            info = await self._try(p, {"op": "link.info"})
            r = await self._put(p, me, me.pub, name, targets, content_hash) if info.get("ok") else info
            if r.get("ok"):
                links.append({"peer": info["pub"], "id": r["id"], **({"via": p.via} if p.via else {})})
            else:
                failed.append({"via": p.via, "error": r.get("error")})
        if not links:
            return {"ok": False, "error": "no link peer took the link: " + "; ".join(f"{f['via']}: {f['error']}" for f in failed)}
        places = [{"kind": "link", "peer": x["peer"], "link_id": x["id"], **({"via": x["via"]} if x.get("via") else {})} for x in links]
        return {"ok": True, "links": links, "places": places, **({"failed": failed} if failed else {})}

    async def move(self, me: Identity, the_link_id: str, targets: list[dict]) -> dict:
        """the author moves the work: a new signed version at every link peer; the ledger does not change"""
        found = await self.find(the_link_id)
        if not found.get("ok"):
            return found
        owner, name, ch = found["link"]["owner"], found["link"]["name"], found["link"].get("content_hash")
        results = []
        for p in self.peers:
            r = await self._put(p, me, owner, name, targets, ch)
            results.append({"via": p.via, "ok": bool(r.get("ok")), **({"ver": r["ver"]} if r.get("ok") else {"error": r.get("error")})})
        return {"ok": any(x["ok"] for x in results), "id": the_link_id, "peers": results}

    async def find(self, the_link_id: str, expected_owner: str | None = None, key_of: KeyOf | None = None) -> dict:
        """where the work is now: the newest version the owner's current key signed, across all link peers"""
        good, report = [], []
        for p in self.peers:
            r = await self._try(p, {"op": "link.get", "id": the_link_id})
            bad = r.get("error") if not r.get("ok") else await verify_link(r["link"], self.s, expected_owner, key_of)
            report.append({"via": p.via, "ok": not bad, **({"error": bad} if bad else {"ver": r["link"]["ver"], "ts": r["link"]["ts"]})})
            if not bad:
                good.append(r["link"])
        if not good:
            return {"ok": False, "error": "no link peer gave a version its owner signed", "peers": report}
        best = max(good, key=lambda x: x["ts"])
        return {"ok": True, "targets": best["targets"], "ver": best["ver"], "owner": best["owner"], "signer": best["signer"],
                "ts": best["ts"], "link": best, "peers": report}
