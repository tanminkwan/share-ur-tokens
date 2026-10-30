"""The record role (platform infrastructure): a peer hosts the recorder service, sealing with the peer's own key, and opens
the recorder API. The judgement whether to accept a record contract can be supplied; default is to accept."""
from __future__ import annotations

from typing import Callable

from ..recorder.api import build_recorder_app
from ..recorder.service import RecorderService
from .plugin import BaseApp, Decision

ROLE = "record"


class RecordRole(BaseApp):
    name, version = "record", "1.0"

    def __init__(self, service: RecorderService, url: str, decide: Callable[..., Decision] | None = None):
        self.service, self.url, self.decide = service, url, decide

    def offers(self):
        return [ROLE]

    def profile_extra(self):
        return {"recorder_url": self.url}

    async def accept_role(self, ctx, role, request):
        if role != ROLE:
            return None
        if self.decide is None:
            return Decision(True, "기록 역할을 공개하고 있음")
        d = self.decide(ctx, request)
        return await d if hasattr(d, "__await__") else d

    def api(self):
        return build_recorder_app(self.service)
