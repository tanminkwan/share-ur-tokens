"""P6-V1: the LLM usage meter. An LLM adapter reports what the service says it used; the ask_json helper adds it to the
meter of that LLM under the asking peer, so runs with and without built-in elements can be compared (calls, tokens)."""
import json

import httpx

from arena.events import EventLog
from arena.llm import CompatLLM, UsageMeter, ask_json
from tests.test_llm import SCHEMA, llm_settings


def endpoint_with_usage(seen):
    def handler(request: httpx.Request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 1}'}}],
                                         "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_p6v1_calls_and_tokens_are_counted_per_peer(tmp_path):
    llm = CompatLLM(llm_settings(tmp_path), http=endpoint_with_usage([]))
    llm.meter = UsageMeter()
    log = EventLog(echo=False)
    for actor in ("필명-a", "필명-a", "필명-b"):
        assert await ask_json(llm, log, actor, fallback=lambda: {}, system="s", user="u", schema=SCHEMA) == {"x": 1}
    t = llm.meter.totals()
    assert t["필명-a"] == {"calls": 2, "prompt_tokens": 240, "completion_tokens": 60} and t["필명-b"]["calls"] == 1
    assert llm.meter.total() == {"calls": 3, "prompt_tokens": 360, "completion_tokens": 90}


async def test_p6v1_without_a_meter_nothing_changes(tmp_path):
    llm = CompatLLM(llm_settings(tmp_path), http=endpoint_with_usage([]))
    assert await ask_json(llm, EventLog(echo=False), "필명-a", fallback=lambda: {}, system="s", user="u", schema=SCHEMA) == {"x": 1}
