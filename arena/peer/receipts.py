"""Recorder-signed receipts a peer keeps for what it recorded, so it can later prove an entry existed."""
from __future__ import annotations

from ..crypto import verify


class Receipts:
    def __init__(self, items: list[dict] | None = None, on_keep=None):
        self.items: list[dict] = list(items or [])
        self.on_keep = on_keep  # e.g. append to the peer's home so receipts survive a restart

    @staticmethod
    def sealed_by(response: dict, recorder_pub: str) -> bool:
        seal = response.get("seal") or {}
        return bool(response.get("ok") and seal.get("pub") == recorder_pub and verify(recorder_pub, response.get("hash", ""), seal.get("sig", "")))

    def keep(self, response: dict, kind: str, payload: dict, expected_recorder: str, private: dict | None = None) -> bool:
        """keep the receipt only if the expected recorder sealed it; False means do not trust this recorder"""
        if not self.sealed_by(response, expected_recorder):
            return False
        item = {"kind": kind, "payload": payload, "seq": response["seq"], "hash": response["hash"], "seal": response["seal"],
                **({"private": private} if private else {})}  # a party keeps its envelope fields too
        self.items.append(item)
        if self.on_keep:
            self.on_keep(item)
        return True

    def missing_from(self, chain: list[dict]) -> list[dict]:
        """receipts whose entry is not in this copy of the chain (deleted, cut off the end, or rewritten)"""
        have = {(e["seq"], e["hash"]) for e in chain}
        return [r for r in self.items if (r["seq"], r["hash"]) not in have]
