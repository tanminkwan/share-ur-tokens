"""python -m arena.peers.app_store  (settings: ARENA_APP_STORE_DIR, ARENA_APP_STORE_PEER_*, ARENA_APP_TRUSTED_PUBLISHERS)

An optional app distribution peer: anyone may run one, there may be many, and each peer chooses whether to use one."""
import asyncio

from ..config import Settings
from ..peer.app_store import AppStoreRole
from .common import build_autonomous_peer, run_peer


def build(s: Settings):
    return build_autonomous_peer(s, "app_store_peer", [AppStoreRole(s)],
                                 "앱 배포 peer: 배포자가 서명한 앱 꾸러미를 보관하고, 앱 id로 꾸러미나 내려받기 주소를 내준다")


def main():
    s = Settings.load()
    asyncio.run(run_peer(build(s), s.app_store_peer_port))


if __name__ == "__main__":
    main()
