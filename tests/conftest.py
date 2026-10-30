"""Shared fixtures. Every test gets an isolated Settings built from a dict (never from the real .env)."""
import pytest

from arena.config import Settings
from arena.crypto import Identity


def make_env(tmp_path, **over):
    env = {
        "ARENA_HOST": "127.0.0.1",
        "ARENA_BROKER_PORT": "0",
        "ARENA_RECORDER_PORT": "0",
        "ARENA_BROKER_KEY_FILE": str(tmp_path / "broker.key"),
        "ARENA_RECORDER_KEY_FILE": str(tmp_path / "recorder.key"),
        "ARENA_RECORDER_LEDGER_FILE": str(tmp_path / "ledger.jsonl"),
        "ARENA_SIG_WINDOW_SEC": "60",
        "ARENA_ACCESS_LOG_SIZE": "5",
        "ARENA_SEARCH_K": "3",
        "ARENA_SEARCH_MAX_K": "50",
        "ARENA_NEIGHBOR_TIMEOUT_SEC": "2",
        "ARENA_HTTP_TIMEOUT_SEC": "5",
        "ARENA_LABEL_AUTO": "false",  # unit tests opt in to capability labels explicitly
    }
    env.update({k: str(v) for k, v in over.items()})
    return env


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


@pytest.fixture
def settings(env):
    return Settings.load(env=env, dotenv_path=None)


@pytest.fixture
def identity():
    return Identity.generate()


class FakeClock:
    """a clock the tests can move"""

    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, sec):
        self.t += sec
        return self.t


@pytest.fixture
def clock():
    return FakeClock()
