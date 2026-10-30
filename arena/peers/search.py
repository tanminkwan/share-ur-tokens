"""python -m arena.peers.search  (settings: ARENA_SEARCH_PEER_*, ARENA_EMBED_*)"""
import asyncio

from ..config import Settings
from ..embedding import HttpEmbedder
from ..peer.search_role import SearchRole
from .common import build_autonomous_peer, run_peer


def main():
    s = Settings.load()
    peer = build_autonomous_peer(s, "search_peer", [SearchRole(HttpEmbedder(s), s)],
                                 "고급 검색 peer: broker의 프로필과 공지를 임베딩 벡터로 바꿔 뜻이 가까운 것을 찾아 준다")
    asyncio.run(run_peer(peer, s.search_peer_port))


if __name__ == "__main__":
    main()
