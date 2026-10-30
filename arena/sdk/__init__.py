"""에이전트 아레나 app SDK. Third-party app developers depend on this package only (not on arena.peer internals).

    from arena.sdk import BaseApp, Decision, MessageHead, Context
    class MyApp(BaseApp):
        name, version, sdk = "my-app", "0.1.0", "1"
        app_id = "<a fixed UUID>"
        def ops(self):
            return {"my_op": self.my_op}
        async def my_op(self, ctx: Context, msg: dict, head: MessageHead) -> dict:
            return {"ok": True}

Ship it with an entry point in your package:  [project.entry-points."arena.apps"]  my-app = "my_pkg:make_app"
The convention book is dev/app-guide.md.
"""
from ..peer.assistant.tools import Tool, default_tools  # noqa: F401  (extend the basic assistant)
from ..peer.plugin import (  # noqa: F401
    CAPABILITIES, SDK_VERSION, App, BaseApp, Decision, EventApprover, Lifecycle, MessageHead, OfferProvider, OpHandler, OpProvider,
    ProfileContributor, RequestReceiver, RoleAcceptor, capabilities_of)
from ..peer.plugin import (  # noqa: F401
    ASSISTANT_APP_ID, MODES, EventHandler, app_fingerprint, app_spec, assistant_spec, valid_app_spec, version_ok)
from ..peer.plugins import load_app, load_apps  # noqa: F401
from .adapters import A2AAgentAdapter, HttpServiceAdapter, function_app  # noqa: F401
from .context import Context, State  # noqa: F401
from .discovery import ENTRY_POINT_GROUP, discover_apps  # noqa: F401
