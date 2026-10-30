"""Platform acceptance check: a rock-paper-scissors event between peers (dev/acceptance-rps.md).
Test-only apps. The game rules live here, never in the platform; everything else is platform API."""
from __future__ import annotations

import asyncio
import itertools
import random
import time

from arena.crypto import canon, h
from arena.llm import ask_json
from arena.peer.app import Decision, PeerApp

KIND = "가위바위보"
MOVES = ("가위", "바위", "보")
BEATS = {"가위": "보", "바위": "가위", "보": "바위"}
POLICY = {"roles": ["player"], "attest_roles": {"match": "player", "forfeit": "issuer", "ranking": "issuer"}}
MAX_TIES = 3
MOVE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["move"],
               "properties": {"move": {"type": "string", "enum": list(MOVES)}}}


def nonce(*parts):
    return h(canon([*parts, time.time(), random.random()]))[:16]


def commit_of(match_id, rnd, move, salt, pub):
    return h(canon({"match": match_id, "round": rnd, "move": move, "salt": salt, "pub": pub}))


def winner(move_a, move_b, a, b):
    return None if move_a == move_b else (a if BEATS[move_a] == move_b else b)


def ranking_from(results: dict, players: list) -> list:
    """results: match_id -> {"a","b","winner"(pub|None)}; win rate = wins / games, ties broken by wins then key"""
    rec = {p: {"pub": p, "wins": 0, "games": 0} for p in players}
    for v in results.values():
        for p in (v["a"], v["b"]):
            rec[p]["games"] += 1
        if v["winner"]:
            rec[v["winner"]]["wins"] += 1
    for r in rec.values():
        r["rate"] = round(r["wins"] / r["games"], 4) if r["games"] else 0.0
    return sorted(rec.values(), key=lambda r: (-r["rate"], -r["wins"], r["pub"]))


def ranking_from_chain(chain: list, event_id: str) -> list:
    """what anyone (the god peer) recomputes from the ledger alone"""
    results, players = {}, set()
    for e in chain:
        p = e["payload"]
        if e["type"] == "contract" and p.get("event_id") == event_id and p.get("role") == "player":
            players.add(p["contractor"])
        if e["type"] == "attest" and p.get("event_id") == event_id and p["kind"] in ("match", "forfeit"):
            results[p["subject"]] = {"a": p["value"]["a"], "b": p["value"]["b"], "winner": p["value"]["winner"]}
    return ranking_from(results, sorted(players))


class RpsHost(PeerApp):
    """opens the event, contracts players, schedules a round robin, checks results, notarizes the ranking, closes"""
    name = "rps-host"

    def __init__(self, group="public"):
        self.group, self.players, self.results, self.forfeits, self.ev = group, {}, {}, set(), None

    def ops(self):
        return {"join": self._join, "result": self._result, "report": self._report}

    async def open(self, peer, recorder_hit, title="peer 가위바위보 대회"):
        self.gid = await peer.group_id(self.group)
        self.R, self.rec = peer.recorder(recorder_hit["recorder_url"]), recorder_hit
        self.ev = "rps-" + nonce(title)[:8]
        event = {"event_id": self.ev, "issuer": peer.identity.pub, "kind": KIND, "policy": POLICY, "approvers": [], "group_id": self.gid}
        r = await self.R.record("event", event, {peer.identity.pub: peer.sign(event)})
        assert r["ok"], r
        self.notice = {"notice_id": self.ev, "kind": KIND, "title": title, "text": f"{title}: 참가자끼리 한 번씩 겨루고 승률로 순위를 공증합니다",
                       "until": time.time() + 600, "issuer_pub": peer.identity.pub, "issuer_url": peer.config.url, "event_hash": r["hash"],
                       "recorder_pub": recorder_hit["pub"], "recorder_url": recorder_hit["recorder_url"], "group_id": self.gid}
        assert (await peer.brokers[self.group].post_notice(peer.identity, self.notice))["ok"]
        return self.ev

    async def _join(self, peer, msg):
        if msg.get("event_id") != self.ev or not self.ev:
            return {"ok": False, "error": "unknown event"}
        pub, url = msg["pub"], msg["url"]
        c = {"event_id": self.ev, "role": "player", "issuer": peer.identity.pub, "contractor": pub, "nonce": nonce(pub), "group_id": self.gid}
        eng = await peer.call(url, {"op": "engage", "role": "player", "contract": c, "request": {"event_id": self.ev}})
        if not eng.get("ok"):
            return {"ok": False, "error": eng.get("error")}
        r = await self.R.record("contract", c, {peer.identity.pub: peer.sign(c), pub: eng["sig"]})
        if r.get("ok"):
            self.players[pub] = url
        return {"ok": bool(r.get("ok")), "contract_hash": r.get("hash")}

    async def schedule(self, peer):
        pubs = sorted(self.players)
        self.matches = [{"match_id": f"{self.ev}-m{i}", "a": a, "a_url": self.players[a], "b": b, "b_url": self.players[b]}
                        for i, (a, b) in enumerate(itertools.combinations(pubs, 2))]
        doc = {"event_id": self.ev, "matches": [{k: m[k] for k in ("match_id", "a", "b")} for m in self.matches]}
        p = {"author": peer.identity.pub, "content_hash": h(canon(doc)), "event_id": self.ev, "group_id": self.gid}
        assert (await self.R.record("publish", p, {peer.identity.pub: peer.sign(p)}))["ok"]
        req = {"request_id": f"{self.ev}-schedule", "kind": "schedule", "event_id": self.ev, "matches": self.matches,
               "schedule_hash": p["content_hash"], "issuer_pub": peer.identity.pub, "issuer_url": peer.config.url,
               "recorder_url": self.rec["recorder_url"], "recorder_pub": self.rec["pub"], "group_id": self.gid, "until": time.time() + 600}
        return await peer.solicit(list(self.players.values()), req)

    async def _result(self, peer, msg):
        v = await self.R.verify(msg["attest_hash"])
        m = next((x for x in self.matches if x["match_id"] == msg["match_id"]), None)
        if not (m and v["exists"] and v["seal_ok"] and v["type"] == "attest" and v["kind"] == "match" and v["subject"] == m["match_id"]
                and v["event_id"] == self.ev and v["parties"] == [m["a"], m["b"]]):
            return {"ok": False, "error": "result not on the ledger as a co-signed match"}
        self.results.setdefault(m["match_id"], {**v["value"], "hash": msg["attest_hash"]})
        return {"ok": True}

    async def _report(self, peer, msg):
        """a player says the opponent's reveal does not match its commit: check on the ledger, then rule a forfeit alone"""
        m = next((x for x in self.matches if x["match_id"] == msg["match_id"]), None)
        v = await self.R.verify(msg["publish_hash"])
        bad = msg["offender"]
        if not m or bad not in (m["a"], m["b"]) or v.get("author") != bad or v.get("type") != "publish":
            return {"ok": False, "error": "report does not check out"}
        rv = msg["reveal"]
        if commit_of(m["match_id"], msg["round"], rv["move"], rv["salt"], bad) == v["content_hash"]:
            return {"ok": False, "error": "the reveal matches the commit: no forfeit"}
        honest = m["b"] if bad == m["a"] else m["a"]
        p = {"event_id": self.ev, "kind": "forfeit", "subject": m["match_id"], "parties": [peer.identity.pub], "nonce": nonce(m["match_id"]),
             "value": {"a": m["a"], "b": m["b"], "winner": honest, "offender": bad, "commit": v["content_hash"], "reveal": rv}, "group_id": self.gid}
        r = await self.R.record("attest", p, {peer.identity.pub: peer.sign(p)})
        if r.get("ok"):
            self.results[m["match_id"]] = {**p["value"], "hash": r["hash"]}
            self.forfeits.add(m["match_id"])
        return {"ok": bool(r.get("ok")), "error": r.get("error")}

    async def finish(self, peer, timeout=60.0):
        end = time.time() + timeout
        while len(self.results) < len(self.matches) and time.time() < end:
            await asyncio.sleep(0.05)
        ranking = ranking_from(self.results, sorted(self.players))
        p = {"event_id": self.ev, "kind": "ranking", "subject": "final", "parties": [peer.identity.pub], "nonce": nonce("ranking"),
             "value": {"ranking": ranking, "results": sorted(r["hash"] for r in self.results.values())}, "group_id": self.gid}
        ra = await self.R.record("attest", p, {peer.identity.pub: peer.sign(p)})
        assert ra["ok"], ra
        c = {"event_id": self.ev, "issuer": peer.identity.pub, "result_hash": ra["hash"], "group_id": self.gid}
        rc = await self.R.record("close", c, {peer.identity.pub: peer.sign(c)})
        assert rc["ok"], rc
        await peer.brokers[self.group].close_notice(peer.identity, self.ev)
        return {"ranking": ranking, "ranking_hash": ra["hash"], "close_hash": rc["hash"]}


class RpsPlayer(PeerApp):
    """asks its person whether to join; plays matches directly with the opponent (commit, reveal, co-sign)"""
    name = "rps-player"

    def __init__(self, group="public", rng=None, cheat=False, use_llm=False):
        self.group, self.rng, self.cheat, self.use_llm = group, rng or random.Random(), cheat, use_llm
        self.joined, self.matches, self.rounds, self.done, self.seen = set(), {}, {}, {}, set()

    def offers(self):
        return ["player"]

    def ops(self):
        return {"rps_challenge": self._challenge, "rps_reveal": self._reveal, "rps_sign": self._sign}

    async def accept_role(self, peer, role, request):
        if role != "player":
            return None
        ok = request.get("event_id") in self.joined
        return Decision(ok, "소유자가 참가를 정함" if ok else "참가하지 않기로 한 이벤트")

    # ---- joining: the person decides ----
    async def consider_notices(self, peer):
        for n in (await peer.brokers[self.group].list_notices(peer.identity)).get("notices", []):
            if n.get("kind") != KIND or n["notice_id"] in self.seen:
                continue
            self.seen.add(n["notice_id"])
            a = await peer.owner.ask(f"'{n['title']}'에 참가할까요?", n["text"])
            peer.log.emit("decide", peer.pen, f"소유자(가상의 사람)의 참가 결정: {'참가' if a.yes else '불참'} - {a.why}")
            if a.yes:
                self.joined.add(n["notice_id"])
                r = await peer.call(n["issuer_url"], {"op": "join", "event_id": n["notice_id"], "pub": peer.identity.pub, "url": peer.config.url})
                if not r.get("ok"):
                    self.joined.discard(n["notice_id"])

    # ---- the schedule arrives as a direct request ----
    async def on_request(self, peer, request, sender):
        if request.get("kind") != "schedule" or request["event_id"] not in self.joined:
            return
        self.ctx = request
        mine = [m for m in request["matches"] if peer.identity.pub in (m["a"], m["b"])]
        for m in mine:
            self.matches[m["match_id"]] = m
        await asyncio.gather(*(self.play(peer, m) for m in mine if m["a"] == peer.identity.pub))

    async def choose(self, peer, m):
        if self.use_llm:
            d = await ask_json(peer.llm, peer.log, peer.pen, fallback=lambda: {"move": self.rng.choice(MOVES)},
                               system="당신은 가위바위보를 하는 에이전트입니다. 가위, 바위, 보 중 하나를 고르세요.",
                               user=f"경기 {m['match_id'][-3:]}의 수를 고르세요.", schema=MOVE_SCHEMA)
            return d["move"] if d.get("move") in MOVES else self.rng.choice(MOVES)
        return self.rng.choice(MOVES)

    async def _commit(self, peer, m, rnd):
        move, salt = await self.choose(peer, m), nonce(peer.identity.pub)
        c = commit_of(m["match_id"], rnd, move, salt, peer.identity.pub)
        p = {"author": peer.identity.pub, "content_hash": c, "event_id": self.ctx["event_id"], "group_id": self.ctx["group_id"]}
        r = await peer.recorder(self.ctx["recorder_url"]).record("publish", p, {peer.identity.pub: peer.sign(p)})
        assert r["ok"], r
        self.rounds[(m["match_id"], rnd)] = {"me": {"move": move, "salt": salt, "commit": c, "publish_hash": r["hash"]}}
        return c, r["hash"]

    async def _check_commit(self, peer, publish_hash, author, commit):
        v = await peer.recorder(self.ctx["recorder_url"]).verify(publish_hash)
        return v["exists"] and v["seal_ok"] and v["type"] == "publish" and v["author"] == author and v["content_hash"] == commit

    async def play(self, peer, m):
        """I am a: commit -> challenge -> reveal -> (tie? again) -> co-sign"""
        rounds = []
        for rnd in range(MAX_TIES + 1):
            c, ph = await self._commit(peer, m, rnd)
            r = await peer.call(m["b_url"], {"op": "rps_challenge", "match_id": m["match_id"], "round": rnd, "commit": c, "publish_hash": ph})
            if not r.get("ok") or not await self._check_commit(peer, r["publish_hash"], m["b"], r["commit"]):
                return
            me = self.rounds[(m["match_id"], rnd)]["me"]
            mv = {"move": me["move"], "salt": me["salt"]}
            if self.cheat:
                mv = {"move": BEATS[BEATS[me["move"]]], "salt": me["salt"]}
            rv = await peer.call(m["b_url"], {"op": "rps_reveal", "match_id": m["match_id"], "round": rnd, **mv})
            if not rv.get("ok"):
                return
            if commit_of(m["match_id"], rnd, rv["move"], rv["salt"], m["b"]) != r["commit"]:
                await peer.call(self.ctx["issuer_url"], {"op": "report", "match_id": m["match_id"], "round": rnd, "offender": m["b"],
                                                        "publish_hash": r["publish_hash"], "reveal": {"move": rv["move"], "salt": rv["salt"]}})
                return
            rounds.append({"round": rnd, "move_a": me["move"], "salt_a": me["salt"], "commit_a": c,
                           "move_b": rv["move"], "salt_b": rv["salt"], "commit_b": r["commit"]})
            w = winner(me["move"], rv["move"], m["a"], m["b"])
            if w or rnd == MAX_TIES:
                break
        value = {"a": m["a"], "b": m["b"], "rounds": rounds, "winner": w}
        p = {"event_id": self.ctx["event_id"], "kind": "match", "subject": m["match_id"], "value": value, "parties": [m["a"], m["b"]],
             "nonce": nonce(m["match_id"]), "group_id": self.ctx["group_id"]}
        s = await peer.call(m["b_url"], {"op": "rps_sign", "payload": p})
        if not s.get("ok"):
            return
        rec = await peer.recorder(self.ctx["recorder_url"]).record("attest", p, {peer.identity.pub: peer.sign(p), m["b"]: s["sig"]})
        if rec.get("ok"):
            self.done[m["match_id"]] = value
            await peer.call(self.ctx["issuer_url"], {"op": "result", "match_id": m["match_id"], "attest_hash": rec["hash"]})

    # ---- I am b ----
    async def _challenge(self, peer, msg):
        m = self.matches.get(msg["match_id"])
        if not m or not await self._check_commit(peer, msg["publish_hash"], m["a"], msg["commit"]):
            return {"ok": False, "error": "no such match or the commit is not on the ledger"}
        self.rounds[(m["match_id"], msg["round"])] = {"them": {"commit": msg["commit"], "publish_hash": msg["publish_hash"]}}
        c, ph = await self._commit(peer, m, msg["round"])
        self.rounds[(m["match_id"], msg["round"])]["them"] = {"commit": msg["commit"], "publish_hash": msg["publish_hash"]}
        return {"ok": True, "commit": c, "publish_hash": ph}

    async def _reveal(self, peer, msg):
        m, rnd = self.matches.get(msg["match_id"]), msg["round"]
        st = self.rounds.get((msg["match_id"], rnd), {})
        if not m or "them" not in st:
            return {"ok": False, "error": "no commit for this round"}
        if commit_of(m["match_id"], rnd, msg["move"], msg["salt"], m["a"]) != st["them"]["commit"]:
            await peer.call(self.ctx["issuer_url"], {"op": "report", "match_id": m["match_id"], "round": rnd, "offender": m["a"],
                                                    "publish_hash": st["them"]["publish_hash"], "reveal": {"move": msg["move"], "salt": msg["salt"]}})
            return {"ok": False, "error": "your reveal does not match your commit"}
        st["them"].update(move=msg["move"], salt=msg["salt"])
        mv = {"move": st["me"]["move"], "salt": st["me"]["salt"]}
        if self.cheat:
            mv = {"move": BEATS[BEATS[st["me"]["move"]]], "salt": st["me"]["salt"]}
        return {"ok": True, **mv}

    async def _sign(self, peer, msg):
        p = msg["payload"]
        m = self.matches.get(p.get("subject"))
        if not m or p["parties"] != [m["a"], m["b"]] or p["kind"] != "match":
            return {"ok": False, "error": "not my match"}
        for r in p["value"]["rounds"]:  # the result must agree with what I saw
            st = self.rounds.get((m["match_id"], r["round"]), {})
            if st.get("me", {}).get("commit") != r["commit_b"] or st.get("them", {}).get("commit") != r["commit_a"] or st["them"].get("move") != r["move_a"]:
                return {"ok": False, "error": "the result does not match what I saw"}
        last = p["value"]["rounds"][-1]
        if p["value"]["winner"] != winner(last["move_a"], last["move_b"], m["a"], m["b"]):
            return {"ok": False, "error": "wrong winner"}
        self.done[m["match_id"]] = p["value"]
        return {"ok": True, "sig": peer.sign(p)}
