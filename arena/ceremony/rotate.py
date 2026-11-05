"""Handing a key over later (P8-B1, B3, B4): the operating recorder key to the next one, or the god key to a new god key,
with the same offline signing as the ceremony. It works on a stopped recorder's folder (the genesis folder): the recorder
key lives inside the running process, so there is no API to change it from outside. Stop, hand over, start again."""
from __future__ import annotations

import glob
import json
import os
import time

from ..crypto import Identity
from ..ledger import JsonlStore
from ..ledger.types import current_keys
from ..recorder.service import RecorderService
from . import formats as F
from .offline import GOD_PUB, write_private
from .run import LEDGER, RECORDER_KEY, ROUNDS, CeremonyLog, LOG

NEXT_KEY = "recorder.next.key"


def _service(settings, folder: str, key_file: str | None = None) -> RecorderService:
    me = Identity.load(os.path.join(folder, RECORDER_KEY))
    return RecorderService.build(settings, me, JsonlStore(os.path.join(folder, LEDGER)), readers=[], key_file=key_file)


def _next_round(folder: str) -> int:
    nums = [int(os.path.basename(p).split("-")[1].split(".")[0]) for p in glob.glob(os.path.join(folder, ROUNDS, "round-*.request.json"))]
    return max(nums, default=0) + 1


def _write(folder: str, req: dict) -> str:
    os.makedirs(os.path.join(folder, ROUNDS), exist_ok=True)
    path = os.path.join(folder, ROUNDS, f"round-{req['round']}.request.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(req, f, ensure_ascii=False, indent=2)
    return path


def _chain_kind(chain) -> str:
    return "branch" if "parent" in chain[0]["payload"] else "trunk"


def recorder_request(settings, folder: str, clock=time.time) -> dict:
    """a new operating key (kept in recorder.next.key until the handover) and the request god signs offline"""
    svc = _service(settings, folder)
    nxt = Identity.generate()
    write_private(os.path.join(folder, NEXT_KEY), nxt.private_hex() + "\n")
    p = svc.rotation_request("recorder", nxt.pub)
    chain = svc.ledger.chain
    req = F.request(_next_round(folder), _chain_kind(chain), chain[0]["hash"], p["god"], [F.item("key_rotate", "key_rotate", p, [p["god"]])], clock())
    CeremonyLog(os.path.join(folder, LOG), clock).write("request-written", round=req["round"], request=F.request_hash(req), items=["key_rotate"])
    return {"ok": True, "request": _write(folder, req), "new": nxt.pub}


async def recorder_apply(settings, folder: str, req: dict, docs: list[dict], clock=time.time) -> dict:
    got, err = F.collect(req, docs)
    if err:
        return {"ok": False, "error": err}
    item = req["items"][0]
    svc = _service(settings, folder, key_file=os.path.join(folder, RECORDER_KEY))
    nxt = Identity.load(os.path.join(folder, NEXT_KEY))
    old = svc.identity.pub
    r = await svc.rotate_key(nxt, item["payload"], got["key_rotate"][item["payload"]["god"]])
    if not r["ok"]:
        return r
    os.remove(os.path.join(folder, NEXT_KEY))  # recorder.key now holds the new key; the old one was overwritten in place
    CeremonyLog(os.path.join(folder, LOG), clock).write("rotated", hash=r["hash"], seq=r["seq"], old=old, new=nxt.pub)
    return {"ok": True, "entry": r["hash"], "seq": r["seq"], "old": old, "new": nxt.pub}


def god_request(settings, folder: str, new_god_pub: str, clock=time.time) -> dict:
    """the god key to a new one (when the god key leaked): both the old and the new god key sign offline"""
    svc = _service(settings, folder)
    p = svc.rotation_request("god", new_god_pub)
    chain = svc.ledger.chain
    req = F.request(_next_round(folder), _chain_kind(chain), chain[0]["hash"], p["old"],
                    [F.item("key_rotate", "key_rotate", p, [p["old"], new_god_pub])], clock())
    CeremonyLog(os.path.join(folder, LOG), clock).write("request-written", round=req["round"], request=F.request_hash(req), items=["key_rotate"])
    return {"ok": True, "request": _write(folder, req), "old": p["old"], "new": new_god_pub}


async def god_apply(settings, folder: str, req: dict, docs: list[dict], clock=time.time) -> dict:
    got, err = F.collect(req, docs)
    if err:
        return {"ok": False, "error": err}
    p = req["items"][0]["payload"]
    svc = _service(settings, folder)
    r = await svc.record("key_rotate", p, got["key_rotate"])
    if not r["ok"]:
        return r
    if current_keys(svc.ledger.chain)["god"] != p["new"]:
        return {"ok": False, "error": "the ledger does not show the new god key"}
    with open(os.path.join(folder, GOD_PUB), "w", encoding="utf-8") as f:  # what arena.genesis checks the ledger against
        f.write(p["new"] + "\n")
    CeremonyLog(os.path.join(folder, LOG), clock).write("rotated", hash=r["hash"], seq=r["seq"], old=p["old"], new=p["new"])
    return {"ok": True, "entry": r["hash"], "seq": r["seq"], "old": p["old"], "new": p["new"]}
