"""python -m arena.peers.foundation  (settings: ARENA_FOUNDATION_PEER_*)

An optional special-purpose peer: it publishes the built-in code table as an edition on the ledger and hands out the
document. Anyone may run one; following an edition is optional."""
import asyncio

from ..config import Settings
from ..peer.foundation_role import FoundationRole
from .common import build_autonomous_peer, run_peer


def build(s: Settings):
    return build_autonomous_peer(s, "foundation_peer", [FoundationRole(s)],
                                 "에이전트 아레나 재단 peer: 코드표의 기본 판을 원장에 기록하고 그 문서를 내준다(따르는 것은 선택)")


def main():
    s = Settings.load()
    asyncio.run(run_peer(build(s), s.foundation_peer_port))


if __name__ == "__main__":
    main()
