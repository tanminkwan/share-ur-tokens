"""python -m arena.peers.key_peer  (settings: ARENA_KEY_PEER_*)

An optional special-purpose peer: it keeps encrypted key backups and signs recoveries for identities that named it in
advance. It never makes or sees a private key (peers make their own). Anyone may run one. See arena/peer/key_role.py."""
import asyncio

from ..config import Settings
from ..peer.key_role import KeyRole
from .common import build_autonomous_peer, run_peer


def build(s: Settings):
    return build_autonomous_peer(s, "key_peer", [KeyRole(s)],
                                 "키 peer: 암호화된 키 백업을 맡아 두고, 미리 복구 담당으로 정해 둔 peer의 키 복구에 서명한다(비밀키는 보지 않는다)")


def main():
    s = Settings.load()
    asyncio.run(run_peer(build(s), s.key_peer_port))


if __name__ == "__main__":
    main()
