"""LLM adapter. Two backends behind one interface (LLM.ask_json), chosen by ARENA_LLM_BACKEND:

  compat   OpenAI-compatible /v1/chat/completions (Samsung SDS Cloud AI service) with json_schema output
  claude   Claude API with structured output

Failures (empty content, not JSON, HTTP errors) are retried ARENA_LLM_RETRIES times, then LLMError.
`ask_json(llm, log, actor, fallback, ...)` is the convenience wrapper that logs and returns a fallback instead.
"""
from __future__ import annotations

import asyncio
import json
from typing import Callable, Protocol

import httpx

from .config import ConfigError, Settings


class LLMError(Exception):
    pass


class LLM(Protocol):
    async def ask_json(self, *, system: str, schema: dict, user: str | None = None, messages: list | None = None,
                       effort: str | None = None, model: str | None = None) -> dict: ...


def parse_first_json(text: str) -> dict:
    """first JSON object in the text (models sometimes add text around it)"""
    i = text.find("{")
    if i < 0:
        raise ValueError("no JSON object in the answer")
    obj = json.JSONDecoder(strict=False).raw_decode(text[i:])[0]
    if not isinstance(obj, dict):
        raise ValueError("answer is not a JSON object")
    return obj


def _messages(user, messages):
    return list(messages) if messages else [{"role": "user", "content": user}]


class CompatLLM:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        settings.require("llm_base_url", "llm_api_key", "llm_model_agent")
        self.settings, self._http = settings, http
        self._sem = asyncio.Semaphore(settings.llm_concurrency)

    async def _post(self, body):
        s = self.settings
        url, headers = f"{s.llm_base_url.rstrip('/')}/v1/chat/completions", {"Authorization": f"Bearer {s.llm_api_key}"}
        if self._http is not None:
            return await self._http.post(url, json=body, headers=headers)
        async with httpx.AsyncClient(timeout=s.llm_timeout_sec) as hc:
            return await hc.post(url, json=body, headers=headers)

    async def ask_json(self, *, system, schema, user=None, messages=None, effort=None, model=None):
        s = self.settings
        body = {"model": model or s.llm_model_agent, "max_tokens": s.llm_max_tokens,
                "messages": [{"role": "system", "content": system}] + _messages(user, messages),
                "response_format": {"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}},
                "reasoning_effort": effort or s.llm_effort}
        last, attempts = None, s.llm_retries + 1
        async with self._sem:
            while attempts > 0:
                attempts -= 1
                try:
                    r = await self._post(body)
                    if r.status_code == 400 and "reasoning_effort" in body:  # endpoint without that knob: retry plain
                        body.pop("reasoning_effort")
                        attempts += 1
                        continue
                    r.raise_for_status()
                    content = r.json()["choices"][0]["message"].get("content")
                    if not content:
                        raise ValueError("empty content")
                    return parse_first_json(content)
                except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
                    last = e
        raise LLMError(f"{type(last).__name__}: {str(last)[:120]}")


class ClaudeLLM:
    def __init__(self, settings: Settings):
        settings.require("llm_claude_api_key", "llm_model_agent")
        import anthropic
        self.settings, self._anthropic = settings, anthropic
        self._client = anthropic.AsyncAnthropic(api_key=settings.llm_claude_api_key, timeout=settings.llm_timeout_sec)
        self._sem = asyncio.Semaphore(settings.llm_concurrency)

    async def ask_json(self, *, system, schema, user=None, messages=None, effort=None, model=None):
        s, last = self.settings, None
        kwargs = dict(model=model or s.llm_model_agent, max_tokens=s.llm_max_tokens, system=system, messages=_messages(user, messages))
        async with self._sem:
            for _ in range(s.llm_retries + 1):
                try:
                    resp = await self._client.messages.create(
                        **kwargs, output_config={"effort": effort or s.llm_effort, "format": {"type": "json_schema", "schema": schema}})
                    if resp.stop_reason == "refusal":
                        raise ValueError("refusal")
                    return parse_first_json("".join(b.text for b in resp.content if b.type == "text"))
                except (self._anthropic.APIError, ValueError) as e:
                    last = e
        raise LLMError(f"{type(last).__name__}: {str(last)[:120]}")


class NoLLM:
    """for peers without a model: every call fails, so callers use their fallback (e.g. profile = first line)"""

    async def ask_json(self, **kw):
        raise LLMError("no LLM configured for this peer")


def build_llm(settings: Settings) -> LLM:
    if settings.llm_backend == "compat":
        return CompatLLM(settings)
    if settings.llm_backend == "claude":
        return ClaudeLLM(settings)
    raise ConfigError(f"{settings.key_of('llm_backend')} 값은 compat 또는 claude여야 합니다: {settings.llm_backend!r}")


async def ask_json(llm: LLM, log, actor: str, fallback: Callable[[], dict], **kw) -> dict:
    """ask, and on LLMError log it and return fallback() so a flow never stalls"""
    try:
        return await llm.ask_json(**kw)
    except LLMError as e:
        log.emit("llm", actor, f"LLM 호출 실패({e}) → 대체값 사용")
        return fallback()
