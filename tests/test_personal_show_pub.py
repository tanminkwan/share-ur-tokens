"""`python -m arena.peers.personal show-pub`: the owner reads the peer's whole public key (64 hex characters) without starting
the peer, to ask a connectivity server's operator for leave to use it (docs/peer-manual.md 4.4). The secret key never shows."""
import dataclasses
import pathlib
import subprocess
import sys

from arena.peer.home import PeerHome
from arena.peers.personal import show_pub

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_show_pub_prints_the_whole_public_key_and_the_pen_name_of_the_home(settings, tmp_path, capsys):
    s = dataclasses.replace(settings, key_store="file", personal_peer_home=str(tmp_path / "home"), personal_peer_nick="나래")
    me = PeerHome(s.personal_peer_home, s).identity()  # the key the peer runs with
    show_pub(s)
    out = capsys.readouterr().out
    assert me.pub in out and len(me.pub) == 64
    assert f"나래-{me.pub[:s.pen_name_len]}" in out
    secret = open(PeerHome(s.personal_peer_home, s).key_name(), encoding="utf-8").read().strip()
    assert secret not in out  # the secret key is never printed


def test_show_pub_on_a_new_home_makes_the_key_the_peer_will_use(settings, tmp_path, capsys):
    """before the first start: the key is made now, and the peer keeps it when it starts"""
    s = dataclasses.replace(settings, key_store="file", personal_peer_home=str(tmp_path / "new"))
    show_pub(s)
    out = capsys.readouterr().out
    assert PeerHome(s.personal_peer_home, s).identity().pub in out


def test_show_pub_runs_as_a_command(tmp_path):
    env = {"ARENA_KEY_STORE": "file", "ARENA_PERSONAL_PEER_HOME": str(tmp_path / "h"), "PATH": "/usr/bin:/bin",
           "ARENA_PERSONAL_PEER_NICK": "가람"}
    r = subprocess.run([sys.executable, "-m", "arena.peers.personal", "show-pub"], capture_output=True, text=True, timeout=60, env=env,
                       cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-300:]
    lines = r.stdout.strip().splitlines()
    pub = next(ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("public key"))
    assert len(pub) == 64 and all(c in "0123456789abcdef" for c in pub)
