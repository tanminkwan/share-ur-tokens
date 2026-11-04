"""Every peer says what kind it is, so any window plugged into it shows its own background and name (arena-ui)."""
from arena.bundled.peer_kinds import PEER_KINDS, kind_view
from arena.config import Settings
from arena.peers.common import KINDS
from tests.conftest import make_env


def test_each_runner_names_a_known_kind(tmp_path):
    from arena.peers import app_store, foundation, key_peer, search
    assert set(KINDS.values()) <= set(PEER_KINDS) and kind_view("nope") == {"kind": "personal", "kind_label": "개인 peer"}
    env = make_env(tmp_path, **{f"ARENA_{p}_BROKERS": "public=http://127.0.0.1:1" for p in ("KEY_PEER", "APP_STORE_PEER", "FOUNDATION_PEER", "SEARCH_PEER")},
                   ARENA_LLM_BACKEND="none", ARENA_EMBED_URL="http://127.0.0.1:1")
    s = Settings.load(env=env, dotenv_path=None)
    built = {"key": key_peer.build(s), "app-store": app_store.build(s), "foundation": foundation.build(s), "search": search.build(s)}
    assert {k: p.config.kind for k, p in built.items()} == {k: k for k in built}
