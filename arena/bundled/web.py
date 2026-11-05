"""LocalWebApp: a bundled app that opens its own local web window when the peer starts (and closes it when it stops).
One responsibility: hosting. What the window shows is the subclass's Starlette app."""
from __future__ import annotations

import os
import secrets

from ..peer.home import PeerHome
from ..peer.plugin import BaseApp
from ..serve import serve_background


def web_token(home: PeerHome, fixed: str = "") -> str:
    """the token of a peer's windows: the one the owner set, else one made once in the home folder (web-token, 0600)"""
    if fixed:
        return fixed
    p = home.path("web-token")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(24))
        os.chmod(p, 0o600)
    with open(p, encoding="utf-8") as f:
        return f.read().strip()


class LocalWebApp(BaseApp):
    def __init__(self, host: str, port: int, token: str):
        self.host, self.port, self.token = host, port, token
        self._server = None

    def web_app(self, ctx):  # the Starlette app this window serves
        raise NotImplementedError

    @property
    def address(self) -> str:
        return f"http://{self.host}:{self.port}/#token={self.token}"

    async def start(self, ctx) -> None:
        if self._server is None:
            self._server = await serve_background(self.web_app(ctx), self.host, self.port)
            ctx.log.emit("web", ctx.pen, f"{self.name} 화면: http://{self.host}:{self.port}/")

    async def stop(self, ctx) -> None:
        if self._server is not None:
            self._server.should_exit = True
            self._server = None
