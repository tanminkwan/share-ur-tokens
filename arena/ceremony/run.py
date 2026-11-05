"""ceremony run (P8-A2, A3, A5, A6, B1, C1): one process makes the keys, asks the offline god for its signatures round by
round, seals entry 0 with a first recorder key that lives in memory only, hands over to the operating recorder key and
then lets the first key go. The folder it leaves is what arena.genesis takes over (design.md 2, 4.1, 4.2).

Why rounds: the key_rotate payload god signs names the ledger_id, the hash of entry 0, known only once entry 0 is sealed.
The trunk takes two rounds (genesis; key_rotate), a branch three (genesis; chain_link + key_rotate; parent_link)."""
from __future__ import annotations

import asyncio
import glob
import json
import os
import time
from typing import Callable

from ..crypto import Identity
from ..genesis import genesis_payload
from ..ledger import JsonlStore
from ..ledger.trust import anchor_block, branch_parent, chain_link_payload, parent_link_payload
from ..ledger.types import current_keys
from ..recorder.service import RecorderService
from . import formats as F
from .offline import GOD_PUB

STEPS = ("keys-made", "request-written", "signatures-taken", "signatures-refused", "sealed", "chain-linked", "parent-linked",
         "rotated", "first-key-gone", "anchor-written", "declaration-drafted")
LEDGER, RECORDER_KEY, BROKER_KEY, OBSERVER_KEY = "ledger.jsonl", "recorder.key", "broker.key", "observer.key"
ANCHOR, DECLARATION, LOG, ROUNDS = "trust-anchor.md", "retirement.json", "ceremony-log.jsonl", "rounds"


class Aborted(Exception):
    """the ceremony stopped; its first recorder key is gone with the process, so the folder is to be thrown away"""


class CeremonyLog:
    """what was done and when, public values only (keys' public halves, hashes, seqs): never a private key or passphrase"""

    def __init__(self, path: str, clock: Callable[[], float]):
        self.path, self.clock = path, clock

    def write(self, step: str, **values) -> None:
        if step not in STEPS:
            raise ValueError(f"unknown step {step}")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": self.clock(), "step": step, "values": values}, ensure_ascii=False) + "\n")


class Rounds:
    """the request files written for the offline machine and the signature files that come back"""

    def __init__(self, folder: str, settings, log: CeremonyLog, clock, sleep, say):
        self.dir, self.s, self.log, self.clock, self.sleep, self.say = os.path.join(folder, ROUNDS), settings, log, clock, sleep, say
        os.makedirs(self.dir, exist_ok=True)

    def request_path(self, n: int) -> str:
        return os.path.join(self.dir, f"round-{n}.request.json")

    def write(self, req: dict) -> str:
        path = self.request_path(req["round"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(req, f, ensure_ascii=False, indent=2)
        self.log.write("request-written", round=req["round"], request=F.request_hash(req), items=[x["name"] for x in req["items"]])
        self.say(f"round {req['round']}: sign {path} offline (python -m arena.ceremony sign) and put the result next to it as "
                 f"round-{req['round']}.signatures.json")
        return path

    async def wait(self, req: dict) -> dict:
        """{item name: {signer: sig}} once every item is signed by every signer; a wrong file is set aside, not used"""
        n, until = req["round"], self.clock() + self.s.ceremony_timeout_sec
        while True:
            good = []
            for path in sorted(glob.glob(os.path.join(self.dir, f"round-{n}.signatures*.json"))):
                try:
                    with open(path, encoding="utf-8") as f:
                        doc = json.load(f)
                except (OSError, ValueError):
                    continue  # still being written
                _, err = F.collect(req, [doc])
                if err and "still needs" not in err:
                    os.replace(path, path + ".refused")
                    self.log.write("signatures-refused", round=n, file=os.path.basename(path), why=err)
                    self.say(f"round {n}: refused {os.path.basename(path)}: {err}")
                    continue
                good.append(doc)
            got, err = F.collect(req, good)
            if got is not None:
                self.log.write("signatures-taken", round=n, signers=sorted({d["signer"] for d in good}))
                return got
            if self.clock() > until:
                raise Aborted(f"round {n} was not signed in time ({err}); the first recorder key is gone: start again in a new folder")
            await self.sleep(self.s.ceremony_poll_sec)


def _fresh(folder: str) -> None:
    if os.path.exists(os.path.join(folder, LEDGER)):
        raise Aborted(f"{folder} already holds a ledger: one ceremony per folder")
    os.makedirs(folder, exist_ok=True)


def _witnesses(witnesses: list[str], settings) -> list[str]:
    w = list(witnesses)
    if len(set(w)) != len(w) or not all(len(x) == 64 and all(c in "0123456789abcdef" for c in x) for x in w):
        raise Aborted("witnesses are distinct public keys (hex)")
    if len(w) < settings.ceremony_min_witnesses:
        raise Aborted(f"name at least {settings.ceremony_min_witnesses} witnesses before the ceremony starts")
    return w


async def run(settings, god_pub: str, folder: str, witnesses: list[str], parent=None, parent_url: str | None = None,
              name: str | None = None, note: str = "", clock: Callable[[], float] = time.time, sleep=asyncio.sleep,
              say: Callable[[str], None] = print) -> dict:
    """parent: the trunk's RecorderAPI when this ceremony starts a branch chain (with its address, parent_url)"""
    _fresh(folder)
    w = _witnesses(witnesses, settings)
    log = CeremonyLog(os.path.join(folder, LOG), clock)
    rounds = Rounds(folder, settings, log, clock, sleep, say)
    chain_kind = "branch" if parent is not None else "trunk"
    first, operating = Identity.generate(), Identity.generate()  # the first key is never saved (P8-A2)
    broker, observer = Identity.generate(), Identity.generate()
    broker.save(os.path.join(folder, BROKER_KEY))
    observer.save(os.path.join(folder, OBSERVER_KEY))
    with open(os.path.join(folder, GOD_PUB), "w", encoding="utf-8") as f:
        f.write(god_pub + "\n")
    log.write("keys-made", god=god_pub, first_recorder=first.pub, recorder=operating.pub, broker=broker.pub, observer=observer.pub)
    svc = RecorderService.build(settings, first, JsonlStore(os.path.join(folder, LEDGER)), readers=[observer.pub], key_file=None)

    # round 1: entry 0
    pdoc = await parent.trust() if parent is not None else None
    if pdoc is not None and not pdoc.get("ok"):
        raise Aborted(f"parent recorder: {pdoc.get('error')}")
    par = branch_parent(pdoc, parent_url) if pdoc is not None else None
    g = genesis_payload(settings, god_pub, broker.pub, first.pub, par)
    req = F.request(1, chain_kind, None, god_pub, [F.item("genesis", "genesis", g, [god_pub])], clock())
    rounds.write(req)
    sig = (await rounds.wait(req))["genesis"][god_pub]
    r = await svc.record("genesis", g, {god_pub: sig})
    if not r["ok"]:
        raise Aborted(f"entry 0 refused: {r['error']}")
    chain = svc.ledger.chain
    ledger_id = chain[0]["hash"]
    log.write("sealed", seq=0, hash=ledger_id)

    # round 2: (a branch's chain_link) and the handover to the operating key
    rot = svc.rotation_request("recorder", operating.pub)
    items = [F.item("key_rotate", "key_rotate", rot, [god_pub])]
    link_p = None
    if par is not None:
        link_p = chain_link_payload(pdoc, chain, god_pub, first.pub, name or "branch")
        items.insert(0, F.item("chain_link", "chain_link", link_p, [god_pub]))
    req = F.request(2, chain_kind, ledger_id, god_pub, items, clock())
    rounds.write(req)
    sigs = await rounds.wait(req)
    if link_p is not None:
        r = await parent.record("chain_link", link_p, {god_pub: sigs["chain_link"][god_pub], first.pub: first.sign(link_p)})
        if not r.get("ok"):
            raise Aborted(f"the trunk refused the chain_link: {r.get('error')}")
        log.write("chain-linked", hash=r["hash"], seq=r["seq"])
        link = (await parent.link(ledger_id)).get("link") or {}
        pl = parent_link_payload(chain, god_pub, link)
        req = F.request(3, chain_kind, ledger_id, god_pub, [F.item("parent_link", "parent_link", pl, [god_pub])], clock())
        rounds.write(req)
        r = await svc.record("parent_link", pl, {god_pub: (await rounds.wait(req))["parent_link"][god_pub]})
        if not r["ok"]:
            raise Aborted(f"parent_link refused: {r['error']}")
        log.write("parent-linked", hash=r["hash"], seq=r["seq"])
    r = await svc.rotate_key(operating, rot, sigs["key_rotate"][god_pub])
    if not r["ok"]:
        raise Aborted(f"the handover was refused: {r['error']}")
    handover = r["hash"]
    log.write("rotated", hash=handover, seq=r["seq"], old=first.pub, new=operating.pub)

    # the first key goes only once the ledger shows it handed over (P8-C1)
    chain = svc.ledger.chain
    handed = any(e["type"] == "key_rotate" and e["payload"].get("role") == "recorder" and e["payload"].get("old") == first.pub for e in chain)
    if current_keys(chain)["recorder"] != operating.pub or not handed:
        raise Aborted("the ledger does not show the first recorder key handed over; it is not let go")
    operating.save(os.path.join(folder, RECORDER_KEY))  # the first time a recorder key touches the disk
    first_pub = first.pub
    del first
    log.write("first-key-gone", key=first_pub, method="memory-only")
    with open(os.path.join(folder, ANCHOR), "w", encoding="utf-8") as f:
        f.write(anchor_block(chain))
    log.write("anchor-written", ledger_id=ledger_id)
    head = {"seq": chain[-1]["seq"], "hash": chain[-1]["hash"]}
    d = F.declaration(first_pub, "recorder", ledger_id, handover, head, "memory-only", clock(), w, note)
    with open(os.path.join(folder, DECLARATION), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    log.write("declaration-drafted", hash=F.declaration_hash(d), witnesses=w)
    say(f"done: ledger {ledger_id}. Witnesses sign {os.path.join(folder, DECLARATION)} (python -m arena.ceremony witness)")
    say(f"keep a copy of {RECORDER_KEY} offline, encrypted: losing the operating recorder key stops the chain until phase 7 "
        "(dev/chain-policy.md 7.1)")
    return {"ok": True, "chain": chain_kind, "ledger_id": ledger_id, "god": god_pub, "first_recorder": first_pub, "recorder": operating.pub,
            "broker": broker.pub, "observer": observer.pub, "entries": len(chain), "handover": handover, "folder": folder}
