"""AppHarness: put one app on an in-memory peer (broker, recorder, transport, scripted owner/LLM) and drive it.

    h = AppHarness(MyApp(), tmp_path)
    r = await h.call("my_op", {"x": 1}, group="public", event="ev-1")
"""
from __future__ import annotations

import os

from ..a2a import LocalTransport
from ..broker.client import InMemoryBrokerClient
from ..broker.neighbors import NoNeighbors
from ..broker.service import BrokerService
from ..config import Settings
from ..crypto import Identity
from ..events import EventLog
from ..ledger import MemoryStore
from ..llm import NoLLM
from ..peer.area import LocalFolderArea
from ..peer.node import Peer, PeerConfig
from ..peer.owner import NoOwner
from ..peer.record_role import RecordRole
from ..recorder.client import InMemoryRecorderClient
from ..recorder.service import RecorderService
from ..search import BM25Searcher


def harness_settings(tmp_dir: str, **over) -> Settings:
    env = {"ARENA_EVENT_STORE_DIR": os.path.join(tmp_dir, "events"), "ARENA_LABEL_AUTO": "false", "ARENA_RECORDER_REQUIRE_GROUP": "false",
           "ARENA_BROKER_STATE_FILE": os.path.join(tmp_dir, "broker.json"), "ARENA_RECORDER_ACCESS_LOG_FILE": os.path.join(tmp_dir, "access.jsonl")}
    env.update({k: str(v) for k, v in over.items()})
    return Settings.load(env=env, dotenv_path=None)


class AppHarness:
    def __init__(self, app, tmp_dir, *, settings: Settings | None = None, owner=None, llm=None, labels=(), notes=("하네스 peer",),
                 group_id: str | None = None):
        tmp_dir = str(tmp_dir)
        self.settings = settings or harness_settings(tmp_dir)
        self.log, self.transport = EventLog(echo=False), LocalTransport()
        self.broker = BrokerService(self.settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="harness", neighbors=[],
                                    group_id=group_id)
        rec_id = Identity.generate()
        self.recorder = RecorderService.build(self.settings, rec_id, MemoryStore(), readers=[])
        area_dir = os.path.join(tmp_dir, "area")
        os.makedirs(area_dir, exist_ok=True)
        with open(os.path.join(area_dir, "notes.md"), "w", encoding="utf-8") as f:
            f.writelines(f"- {n}\n" for n in notes)
        self.peer = Peer(Identity.generate(), self.settings, PeerConfig(url="mem://harness", labels=list(labels)),
                         LocalFolderArea(area_dir, self.settings), owner or NoOwner(), llm or NoLLM(), self.transport, self.log,
                         brokers={"public": InMemoryBrokerClient(self.broker)}, apps=[app, RecordRole(self.recorder, "mem://harness/recorder")])
        self.peer.recorder_factory = lambda url: InMemoryRecorderClient(self.recorder)
        self.transport.register(self.peer.config.url, self.peer.handle)
        self.app = app

    @property
    def ctx(self):
        return self.peer.ctx(self.app)

    async def call(self, op: str, msg: dict | None = None, *, group: str | None = None, event: str | None = None) -> dict:
        meta = {"group_id": group, "event_id": event} if (group or event) else None
        return await self.peer.handle(dict(msg or {}, op=op), meta)

    async def start(self):
        await self.peer.advertise()
        await self.peer.start()
