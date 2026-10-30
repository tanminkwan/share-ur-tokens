"""P2-E2: tests against the real LLM (Samsung SDS Cloud AI service, keys in .env). Skipped with a reason if keys are absent."""
import pytest

from arena.config import Settings


def live_settings(**over):
    s = Settings.load()
    for k, v in over.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def live():
    s = live_settings()
    if not (s.llm_base_url and s.llm_api_key and s.llm_model_agent):
        pytest.skip("ARENA_LLM_BASE_URL / ARENA_LLM_API_KEY / ARENA_LLM_MODEL_AGENT not set in .env")
    return s
