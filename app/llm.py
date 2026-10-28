"""Claude adapter. Live when ANTHROPIC_API_KEY is set, otherwise callers get their offline fallback.

Models: SUT_AGENT_MODEL (peer/broker/requester agents) and SUT_PERSONA_MODEL (the simulated humans).
Both default to claude-opus-5-5. For a faster/cheaper demo set them to claude-haiku-5-5 or claude-sonnet-5-5.
"""
import asyncio
import json
import os

from .common import emit

AGENT_MODEL = os.getenv("SUT_AGENT_MODEL", "claude-opus-5-5")
PERSONA_MODEL = os.getenv("SUT_PERSONA_MODEL", "claude-opus-5-5")
FORCE_OFFLINE = os.getenv("SUT_OFFLINE") == "1"
_sem = asyncio.Semaphore(8)
_client = None


def live() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY")) and not FORCE_OFFLINE


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.AsyncAnthropic()
    return _client


async def ask_json(*, actor: str, model: str, system: str, user: str, schema: dict, fallback, effort: str = "low") -> dict:
    """Ask Claude for a JSON object matching `schema`; on any failure return fallback() so the demo never stalls."""
    if not live():
        return fallback()
    import anthropic
    client = _get_client()
    kwargs = dict(model=model, max_tokens=8000, system=system, messages=[{"role": "user", "content": user}])
    try:
        async with _sem:
            try:
                resp = await client.messages.create(
                    **kwargs, output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
            except anthropic.BadRequestError:  # older/other model without structured outputs: plain JSON request
                resp = await client.messages.create(
                    **kwargs | {"system": system + "\n반드시 JSON 객체 하나만 출력하세요."}, output_config={"effort": effort})
        if resp.stop_reason == "refusal":
            emit("llm", actor, "Claude가 응답을 거절 → 폴백 사용")
            return fallback()
        text = "".join(b.text for b in resp.content if b.type == "text")
        text = text[text.find("{"): text.rfind("}") + 1]
        return json.loads(text)
    except Exception as e:
        emit("llm", actor, f"LLM 호출 실패({type(e).__name__}) → 폴백 사용")
        return fallback()
