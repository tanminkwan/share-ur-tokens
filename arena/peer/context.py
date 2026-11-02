"""AppContext: what the platform injects into an app. An app sees only this, never the peer object."""
from __future__ import annotations


class AppState:
    """an app's own persistent state (survives restarts through the peer's home); one dict per app"""

    def __init__(self, peer, app_name: str):
        self._peer, self._name = peer, app_name

    def load(self) -> dict:
        return dict(self._peer.app_states.get(self._name, {}))

    def save(self, state: dict) -> None:
        self._peer.app_states[self._name] = state
        self._peer.persist()


class AppContext:
    def __init__(self, peer, app_name: str):
        self._peer, self.app_name = peer, app_name
        self.state = AppState(peer, app_name)

    # who I am (read-only)
    @property
    def identity(self):
        return self._peer.identity

    @property
    def pub(self) -> str:
        return self._peer.identity.pub

    @property
    def pen(self) -> str:
        return self._peer.pen

    @property
    def url(self) -> str:
        return self._peer.config.url

    @property
    def labels(self) -> list[str]:
        return self._peer.current_labels()

    def sign(self, payload) -> str:
        return self._peer.sign(payload)

    # platform services
    @property
    def settings(self):
        return self._peer.settings

    def clock(self) -> float:
        return self._peer.clock()

    @property
    def log(self):
        return self._peer.log

    @property
    def llm(self):
        return self._peer.llm

    @property
    def owner(self):
        return self._peer.owner

    @property
    def area(self):
        return self._peer.area

    @property
    def brokers(self):
        return self._peer.brokers

    @property
    def receipts(self):
        return self._peer.receipts

    @property
    def data_dir(self) -> str:
        """a folder only this app writes to (inside the peer's home if it has one)"""
        import os
        home = self._peer.home
        root = home.path("apps", self.app_name) if home else os.path.join(self._peer.settings.event_store_dir, self._peer.identity.pub[:16], self.app_name)
        os.makedirs(root, exist_ok=True)
        return root

    @property
    def known_recorders(self) -> list[str]:
        return list(self._peer.known_recorders)

    def recorder(self, url: str):
        return self._peer.recorder(url)

    async def call(self, url: str, msg: dict, timeout: float | None = None, group: str | None = None, event: str | None = None) -> dict:
        return await self._peer.call(url, msg, timeout, group=group, event=event)

    async def call_peer(self, pub: str, msg: dict, timeout: float | None = None, group: str | None = None, event: str | None = None) -> dict:
        """reach a peer by a connection method its profile lists (a2a, else api)"""
        return await self._peer.call_peer(pub, msg, timeout, group=group, event=event)

    async def submissions(self, event_id: str) -> list:
        """what this peer's submission desk received for an event (the intake element)"""
        from .elements.intake import IntakeDesk
        desk = self._peer.app_by_id(IntakeDesk.app_id)
        return desk.list(event_id) if desk else []

    async def profile_of(self, pub: str) -> dict | None:
        return await self._peer.profile_of(pub)

    async def solicit(self, targets: list[str], request: dict) -> dict:
        return await self._peer.solicit(targets, request)

    async def group_id(self, group: str) -> str:
        return await self._peer.group_id(group)

    async def recorder_trust(self, url: str) -> dict:
        """is the recorder at url proven by this peer's root of trust? {ok, anchored, recorder, ledger_id, why}"""
        return await self._peer.recorder_trust(url)

    async def ledger_id(self, url: str) -> str | None:
        """the id of the ledger at url (its genesis hash): every payload signed for that ledger carries it as ledger_id"""
        return await self._peer.ledger_id(url)

    def offers(self) -> list[str]:
        return self._peer.offers()

    async def advertise(self) -> dict:
        return await self._peer.advertise()

    async def add_experience(self, note: str) -> None:
        await self._peer.add_experience(note)


class PlatformContext(AppContext):
    """for the built-in platform apps only: they also see the other apps' capabilities (to route engage, approve, solicit)"""

    def apps_with(self, capability) -> list[tuple[object, AppContext]]:
        return [(a, self._peer.ctx(a)) for a in self._peer.apps if isinstance(a, capability)]

    def app_by_id(self, app_id: str):
        return self._peer.app_by_id(app_id)

    def ctx_of(self, app) -> AppContext:
        return self._peer.ctx(app)

    async def install_app(self, app) -> None:
        """plug an app fetched by the app installer into this running peer (same checks as at assembly)"""
        await self._peer.install(app)

    @property
    def inbox(self):
        return self._peer.inbox
