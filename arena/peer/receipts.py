"""Recorder-signed receipts a peer keeps for what it recorded, so it can later prove an entry existed."""
from __future__ import annotations

from ..crypto import verify


class Receipts:
    def __init__(self):
        self.items: list[dict] = []

    @staticmethod
    def sealed_by(response: dict, recorder_pub: str) -> bool:
        seal = response.get("seal") or {}
        return bool(response.get("ok") and seal.get("pub") == recorder_pub and verify(recorder_pub, response.get("hash", ""), seal.get("sig", "")))

    def keep(self, response: dict, kind: str, payload: dict, expected_recorder: str) -> bool:
        """keep the receipt only if the expected recorder sealed it; False means do not trust this recorder"""
        if not self.sealed_by(response, expected_recorder):
            return False
        self.items.append({"kind": kind, "payload": payload, "seq": response["seq"], "hash": response["hash"], "seal": response["seal"]})
        return True
