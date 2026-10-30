"""P2-B2, P2-B3: the OpenAI-compatible adapter against a mocked HTTP endpoint."""
import json

import httpx
import pytest

from arena.config import ConfigError, Settings
from arena.events import EventLog
from arena.llm import CompatLLM, LLMError, ask_json, build_llm
from tests.conftest import make_env

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"], "additionalProperties": False}


def llm_settings(tmp_path, **over):
    base = dict(ARENA_LLM_BACKEND="compat", ARENA_LLM_BASE_URL="http://llm", ARENA_LLM_API_KEY="k",
                ARENA_LLM_MODEL_AGENT="agent-m", ARENA_LLM_MODEL_PERSONA="persona-m", ARENA_LLM_RETRIES="2")
    return Settings.load(env=make_env(tmp_path, **{**base, **over}), dotenv_path=None)


def endpoint(replies, seen):
    """replies: list of (status, content) consumed in order; content None -> empty message"""
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append({"body": body, "auth": request.headers.get("authorization"), "path": request.url.path})
        status, content = replies.pop(0)
        if status != 200:
            return httpx.Response(status, json={"error": "x"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_pb2_asks_with_json_schema_and_parses(tmp_path):
    seen = []
    llm = CompatLLM(llm_settings(tmp_path), http=endpoint([(200, 'note {"x": 3} trailing')], seen))
    out = await llm.ask_json(system="sys", user="hi", schema=SCHEMA, effort="low")
    assert out == {"x": 3}
    b = seen[0]["body"]
    assert seen[0]["path"] == "/v1/chat/completions" and seen[0]["auth"] == "Bearer k"
    assert b["model"] == "agent-m" and b["messages"][0] == {"role": "system", "content": "sys"}
    assert b["response_format"]["json_schema"]["schema"] == SCHEMA and b["reasoning_effort"] == "low"
    assert b["max_tokens"] == llm.settings.llm_max_tokens


async def test_pb2_persona_model_and_message_history(tmp_path):
    seen = []
    llm = CompatLLM(llm_settings(tmp_path), http=endpoint([(200, '{"x": 1}')], seen))
    msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    await llm.ask_json(system="s", messages=msgs, schema=SCHEMA, model=llm.settings.llm_model_persona)
    assert seen[0]["body"]["model"] == "persona-m" and seen[0]["body"]["messages"][1:] == msgs


@pytest.mark.parametrize("bad", [(200, None), (200, "no json here"), (503, None), (429, None)])
async def test_pb2_retries_empty_bad_or_failed_answers(tmp_path, bad):
    seen = []
    llm = CompatLLM(llm_settings(tmp_path), http=endpoint([bad, (200, '{"x": 2}')], seen))
    assert await llm.ask_json(system="s", user="u", schema=SCHEMA) == {"x": 2}
    assert len(seen) == 2


async def test_pb2_gives_up_after_retries(tmp_path):
    seen = []
    llm = CompatLLM(llm_settings(tmp_path, ARENA_LLM_RETRIES="1"), http=endpoint([(200, None), (200, None)], seen))
    with pytest.raises(LLMError):
        await llm.ask_json(system="s", user="u", schema=SCHEMA)
    assert len(seen) == 2


async def test_pb3_drops_reasoning_effort_on_400(tmp_path):
    seen = []
    llm = CompatLLM(llm_settings(tmp_path), http=endpoint([(400, None), (200, '{"x": 5}')], seen))
    assert await llm.ask_json(system="s", user="u", schema=SCHEMA, effort="medium") == {"x": 5}
    assert "reasoning_effort" in seen[0]["body"] and "reasoning_effort" not in seen[1]["body"]


async def test_pb2_fallback_helper_logs_and_returns_fallback(tmp_path):
    seen, log = [], EventLog(echo=False)
    llm = CompatLLM(llm_settings(tmp_path, ARENA_LLM_RETRIES="0"), http=endpoint([(200, None)], seen))
    out = await ask_json(llm, log, "me", fallback=lambda: {"x": 0}, system="s", user="u", schema=SCHEMA)
    assert out == {"x": 0} and log.tail(1)[0]["kind"] == "llm"


def test_pb2_build_llm_checks_required_settings(tmp_path):
    assert isinstance(build_llm(llm_settings(tmp_path)), CompatLLM)
    s = Settings.load(env=make_env(tmp_path, ARENA_LLM_BACKEND="compat"), dotenv_path=None)
    with pytest.raises(ConfigError) as e:
        build_llm(s)
    assert "ARENA_LLM_BASE_URL" in str(e.value)
    with pytest.raises(ConfigError):
        build_llm(Settings.load(env=make_env(tmp_path, ARENA_LLM_BACKEND="nope"), dotenv_path=None))
