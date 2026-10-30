"""An ecosystem that begins with god's genesis, for the acceptance check. In memory (LocalTransport) or over real
processes and HTTP; both give the same peers to the same flow."""
from __future__ import annotations

import dataclasses
import random

from arena.a2a import LocalTransport
from arena.broker.client import InMemoryBrokerClient
from arena.broker.neighbors import NoNeighbors
from arena.broker.service import BrokerService
from arena.crypto import Identity
from arena.events import EventLog
from arena.genesis import record_genesis
from arena.ledger import MemoryStore
from arena.llm import NoLLM
from arena.peer.area import LocalFolderArea
from arena.peer.god_role import GodRole
from arena.peer.node import Peer, PeerConfig
from arena.peer.owner import NoOwner
from arena.peer.record_role import RecordRole
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService
from arena.search import BM25Searcher
from tests.acceptance.rps import RpsHost, RpsPlayer
from tests.fakes import FakeOwner

SDS = "소속:삼성SDS"


class CountingTransport:
    """wraps one peer's transport and records (from, to, op) so we can prove where game messages went"""

    def __init__(self, inner, me, log):
        self.inner, self.me, self.log = inner, me, log

    async def call(self, url, msg, timeout=None):
        self.log.append((self.me, url, msg.get("op")))
        return await self.inner.call(url, msg, timeout)


class MemoryEcosystem:
    def __init__(self, tmp, settings, n_players=4, declining=1, cheaters=(), seed=7):
        self.tmp, self.s = tmp, dataclasses.replace(settings, recorder_require_group=True)
        self.log, self.t, self.msgs = EventLog(echo=False), LocalTransport(), []
        self.god_id = Identity.generate()
        # god's genesis: the genesis broker and the recorder
        self.broker = BrokerService(self.s, Identity.generate(), BM25Searcher(), NoNeighbors(), name="genesis-broker", neighbors=[])
        self.rec_id = Identity.generate()
        self.svc = RecorderService.build(self.s, self.rec_id, MemoryStore(), readers=[self.god_id.pub])
        self.rec = self.peer("recorder", self.rec_id, [RecordRole(self.svc, "mem://recorder/api")], "제네시스 기록자")
        self.god = self.peer("god", self.god_id, [GodRole(self.s, viewers=[])], "god")
        self.host_app = RpsHost()
        self.host = self.peer("host", Identity.generate(), [self.host_app], "가위바위보 대회를 여는 peer")
        rng = random.Random(seed)
        self.players = []
        for i in range(n_players + declining):
            yes = i < n_players
            app = RpsPlayer(rng=random.Random(rng.random()), cheat=(i in cheaters))
            self.players.append(self.peer(f"p{i}", Identity.generate(), [app], f"선수 {i}",
                                          owner=FakeOwner(yes=yes, why="친선 대회라 참가한다" if yes else "이번에는 쉬겠다")))

    def peer(self, name, ident, apps, line, owner=None):
        (self.tmp / name).mkdir()
        (self.tmp / name / "notes.md").write_text(f"- {line}\n", encoding="utf-8")
        url = f"mem://{name}"
        p = Peer(ident, self.s, PeerConfig(url=url, labels=[SDS]), LocalFolderArea(str(self.tmp / name), self.s), owner or NoOwner(), NoLLM(),
                 CountingTransport(self.t, url, self.msgs), self.log, brokers={"public": InMemoryBrokerClient(self.broker)}, apps=apps)
        p.recorder_factory = lambda u: InMemoryRecorderClient(self.svc)
        self.t.register(url, p.handle)
        return p

    async def genesis(self):
        r = await record_genesis(self.svc, self.god_id, self.s, self.broker.identity.pub, self.rec_id.pub)
        assert r["ok"] and r["seq"] == 0, r
        for p in [self.rec, self.god, self.host, *self.players]:
            await p.advertise()
