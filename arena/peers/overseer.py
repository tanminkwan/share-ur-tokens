"""python -m arena.peers.overseer  (settings: ARENA_OVERSEER_PEER_*, ARENA_OVERSEER_VIEWERS)"""
import asyncio

from ..config import Settings
from ..peer.overseer_role import OverseerRole
from .common import build_autonomous_peer, run_peer


def main():
    s = Settings.load()
    peer = build_autonomous_peer(s, "overseer_peer", [OverseerRole(s)],
                                 "관전용 절대자 peer: 허용된 키로 원장을 읽어 스스로 감사하고 통계와 peer별 실적을 낸다")
    asyncio.run(run_peer(peer, s.overseer_peer_port))


if __name__ == "__main__":
    main()
