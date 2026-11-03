"""The owner desk screen (bundled app): a local web window onto the owner desk, for a person who drives their peer (a
human peer) or watches and decides (dev/peer-spec.md 2.8). Not required: any other screen may use the same owner API."""
from __future__ import annotations

from ..owner_service import OwnerService
from ..web import LocalWebApp
from .api import build_owner_api


class DeskWebApp(LocalWebApp):
    name, version, app_id = "bundled.desk_web", "1.0", "6d1f3a8c-2e4b-4a97-b5c0-8e3d7f1a9b26"

    def __init__(self, service: OwnerService, host: str, port: int, token: str):
        super().__init__(host, port, token)
        self.service = service

    def web_app(self, ctx):
        return build_owner_api(self.service, self.token)
