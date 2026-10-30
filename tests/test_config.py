import pytest

from arena.config import ConfigError, Settings
from tests.conftest import make_env


def test_r1_1_every_setting_comes_from_env(tmp_path):
    env = make_env(tmp_path, ARENA_BROKER_PORT="9333", ARENA_SIG_WINDOW_SEC="7", ARENA_BROKER_NEIGHBORS="http://a:1, http://b:2")
    s = Settings.load(env=env, dotenv_path=None)
    assert s.broker_port == 9333
    assert s.sig_window_sec == 7
    assert s.broker_neighbors == ["http://a:1", "http://b:2"]
    assert s.collector_ledger_file == str(tmp_path / "ledger.jsonl")


def test_r1_1_defaults_apply_when_key_absent():
    s = Settings.load(env={}, dotenv_path=None)
    assert s.host == "127.0.0.1"
    assert s.contract_roles == ["record", "review"]
    assert s.pen_name_prefix and s.pen_name_len > 0
    assert s.broker_owner_pub is None
    assert s.collector_readers == []


def test_r1_2_missing_required_key_names_the_key():
    s = Settings.load(env={}, dotenv_path=None)
    with pytest.raises(ConfigError) as e:
        s.require("llm_base_url", "llm_api_key")
    assert "ARENA_LLM_BASE_URL" in str(e.value) and "ARENA_LLM_API_KEY" in str(e.value)


def test_r1_2_bad_type_names_the_key():
    with pytest.raises(ConfigError) as e:
        Settings.load(env={"ARENA_BROKER_PORT": "abc"}, dotenv_path=None)
    assert "ARENA_BROKER_PORT" in str(e.value)


def test_r1_1_dotenv_file_is_read_but_env_wins(tmp_path):
    f = tmp_path / ".env"
    f.write_text("ARENA_BROKER_PORT=9001\nARENA_BROKER_NAME=from-file\n")
    s = Settings.load(env={"ARENA_BROKER_PORT": "9002"}, dotenv_path=str(f))
    assert s.broker_port == 9002
    assert s.broker_name == "from-file"


def test_r1_1_example_file_lists_every_key():
    """`.env.example` must document every ARENA_ key the Settings class knows"""
    import pathlib
    text = pathlib.Path(".env.example").read_text(encoding="utf-8")
    for key in Settings.env_keys():
        assert key in text, f"{key} missing from .env.example"
