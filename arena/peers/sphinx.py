"""python -m arena.peers.sphinx  (settings: ARENA_PERSONAL_* for the person's peer and window, ARENA_SPHINX_* for the role)

An optional special-purpose peer: the sphinx, a person who lets others found branch groups (dev/founding/requirements.md).
It is the sample personal peer in human mode with the sphinx's role on it: applications come in by a2a, the person meets
each applicant outside the platform (video call or face to face, through the contact they gave) and answers yes or no
in the owner window; yes gives a founding pass bound to the applicant's founder key. See arena/peer/sphinx_role.py."""
import asyncio

from ..config import ConfigError, Settings
from ..peer.sphinx_role import SphinxRole
from . import personal


def build(s: Settings):
    if s.personal_mode != "human":
        raise ConfigError(f"스핑크스는 사람이 정한다: {s.key_of('personal_mode')}=human 으로 띄운다")
    if s.sphinx_foundation_url and not s.sphinx_foundation_pub:
        raise ConfigError(f"{s.key_of('sphinx_foundation_url')}를 주면 {s.key_of('sphinx_foundation_pub')}(그 foundation의 공개키)도 준다")
    return personal.build(s, extra_apps=[SphinxRole(s)], kind="sphinx")


def main():
    s = Settings.load()
    asyncio.run(personal.run(s, build(s)))


if __name__ == "__main__":
    main()
