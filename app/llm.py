"""LLM adapter with two backends, chosen by environment:

  SUT_LLM_BASE_URL + SUT_LLM_API_KEY   an OpenAI-compatible chat endpoint (e.g. Samsung SDS Cloud Simple AI Inference)
  ANTHROPIC_API_KEY                    Claude API (used when no SUT_LLM_BASE_URL is set)
  neither, or SUT_OFFLINE=1            callers get their offline fallback

Models: SUT_AGENT_MODEL (peer/broker/requester agents) and SUT_PERSONA_MODEL (the simulated humans).
Defaults: openai/gpt-oss-120b on the compatible endpoint, claude-opus-5-5 on Claude.
Every call goes through ask_json(): JSON-schema output, and any failure returns the caller's fallback so the demo never stalls.
"""
import asyncio
import json
import os

import httpx

from .common import emit

BASE_URL = os.getenv("SUT_LLM_BASE_URL", "").rstrip("/")
BACKEND = "compat" if BASE_URL and os.getenv("SUT_LLM_API_KEY") else ("claude" if os.getenv("ANTHROPIC_API_KEY") else "offline")
if os.getenv("SUT_OFFLINE") == "1":
    BACKEND = "offline"
_DEFAULT = "openai/gpt-oss-120b" if BACKEND == "compat" else "claude-opus-5-5"
AGENT_MODEL = os.getenv("SUT_AGENT_MODEL", _DEFAULT)
PERSONA_MODEL = os.getenv("SUT_PERSONA_MODEL", _DEFAULT)
_sem = asyncio.Semaphore(int(os.getenv("SUT_LLM_CONCURRENCY", "6")))
_client = None


def live() -> bool:
    return BACKEND != "offline"


def describe() -> str:
    return {"compat": f"호환 엔드포인트 {AGENT_MODEL}", "claude": f"Claude {AGENT_MODEL}", "offline": "오프라인 템플릿"}[BACKEND]


def _parse(text: str) -> dict:
    """first JSON object in the text (models sometimes add trailing text or a second object)"""
    return json.JSONDecoder(strict=False).raw_decode(text[text.find("{"):])[0]  # tolerate raw newlines/tabs inside strings


async def _ask_compat(model, messages, schema, effort, max_tokens):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}}}
    if effort:
        body["reasoning_effort"] = effort
    async with httpx.AsyncClient(timeout=240) as hc:
        for attempt in (0, 1):
            r = await hc.post(f"{BASE_URL}/v1/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {os.environ['SUT_LLM_API_KEY']}"})
            if r.status_code == 400 and "reasoning_effort" in body:  # endpoint/model without that knob: retry plain
                body.pop("reasoning_effort")
                continue
            r.raise_for_status()
            break
    msg = r.json()["choices"][0]["message"]
    if not msg.get("content"):  # reasoning model ran out of tokens before answering
        raise ValueError("empty content (raise max_tokens?)")
    return _parse(msg["content"])


async def _ask_claude(model, system, messages, schema, effort):
    global _client
    import anthropic
    _client = _client or anthropic.AsyncAnthropic()
    kwargs = dict(model=model, max_tokens=8000, system=system, messages=messages)
    try:
        resp = await _client.messages.create(**kwargs, output_config={"effort": effort or "low", "format": {"type": "json_schema", "schema": schema}})
    except anthropic.BadRequestError:  # model without structured outputs: ask for plain JSON
        resp = await _client.messages.create(**kwargs | {"system": system + "\n반드시 JSON 객체 하나만 출력하세요."}, output_config={"effort": effort or "low"})
    if resp.stop_reason == "refusal":
        raise ValueError("refusal")
    return _parse("".join(b.text for b in resp.content if b.type == "text"))


async def ask_json(*, actor: str, model: str, system: str, schema: dict, fallback, user: str = None,
                   messages: list = None, effort: str = "low", max_tokens: int = 6000) -> dict:
    """Ask for a JSON object matching `schema` (single `user` prompt, or a full `messages` history)."""
    if not live():
        return fallback()
    msgs = messages or [{"role": "user", "content": user}]
    try:
        async with _sem:
            if BACKEND == "compat":
                return await _ask_compat(model, [{"role": "system", "content": system}] + msgs, schema, effort, max_tokens)
            return await _ask_claude(model, system, msgs, schema, effort)
    except Exception as e:
        emit("llm", actor, f"LLM 호출 실패({type(e).__name__}: {str(e)[:60]}) → 폴백 사용")
        return fallback()
