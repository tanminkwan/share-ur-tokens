"""python -m arena.peers.link_peer  (settings: ARENA_LINK_PEER_*)

An optional special-purpose, API-serving peer that keeps permanent links: the ledger names a link of this peer, which
never changes; where the content is now may change, and only its publisher changes it (arena/peer/link_role.py).
Anyone may run one; it earns standing by being used, and a work may name several."""
import asyncio

from ..config import Settings
from ..peer.link_role import LinkRole
from .common import build_autonomous_peer, open_connections, run_with_connections


def build(s: Settings):
    role = LinkRole(s)
    peer = build_autonomous_peer(s, "link_peer", [role], "link peer: 원장이 가리키는 영구 link를 맡고, 지금 위치는 게시자가 서명해 바꾼다")
    open_connections(peer, list(s.link_peer_connections), "ARENA_LINK_PEER_CONNECTIONS", f"http://{s.host}:{s.link_peer_api_port}",
                     list(role.ops()))
    return peer


def main():
    s = Settings.load()
    asyncio.run(run_with_connections(build(s), s.link_peer_port, s.link_peer_api_port, "link peer"))


if __name__ == "__main__":
    main()
