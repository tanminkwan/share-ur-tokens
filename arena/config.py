"""Settings: every tunable value comes from the environment (and optionally a .env file). Nothing is hardcoded elsewhere.

    s = Settings.load()                       # os.environ + ./.env
    s = Settings.load(env={...}, dotenv_path=None)  # tests: fully isolated

Add a setting by adding one Field below; `.env.example` must list it (a test checks).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Any, Callable

from dotenv import dotenv_values


class ConfigError(Exception):
    pass


def _list(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def _opt(v: str) -> str | None:
    return v or None


def F(key: str, default: Any, parse: Callable[[str], Any], doc: str):
    meta = {"key": key, "parse": parse, "doc": doc, "default": default}
    if isinstance(default, list):
        return field(default_factory=lambda d=default: list(d), metadata=meta)
    return field(default=default, metadata=meta)


@dataclass
class Settings:
    # network
    host: str = F("ARENA_HOST", "127.0.0.1", str, "서비스가 듣는 주소")
    http_timeout_sec: float = F("ARENA_HTTP_TIMEOUT_SEC", 60.0, float, "클라이언트 기본 제한 시간(초)")
    neighbor_timeout_sec: float = F("ARENA_NEIGHBOR_TIMEOUT_SEC", 10.0, float, "이웃 broker 호출 제한 시간(초)")
    sig_window_sec: float = F("ARENA_SIG_WINDOW_SEC", 60.0, float, "서명 요청의 시각 허용 폭(초)")
    # broker
    broker_port: int = F("ARENA_BROKER_PORT", 9110, int, "broker 포트")
    broker_name: str = F("ARENA_BROKER_NAME", "broker", str, "broker 이름")
    broker_neighbors: list[str] = F("ARENA_BROKER_NEIGHBORS", [], _list, "이웃 broker 주소(쉼표 구분)")
    broker_owner_pub: str | None = F("ARENA_BROKER_OWNER_PUB", None, _opt, "닫힌 그룹 소유자 공개키(비면 열린 그룹)")
    broker_key_file: str = F("ARENA_BROKER_KEY_FILE", "data/broker.key", str, "broker 키 파일")
    # collector
    collector_port: int = F("ARENA_COLLECTOR_PORT", 9120, int, "collector 포트")
    collector_name: str = F("ARENA_COLLECTOR_NAME", "collector", str, "collector 이름")
    collector_key_file: str = F("ARENA_COLLECTOR_KEY_FILE", "data/collector.key", str, "기록자 키 파일")
    collector_ledger_file: str = F("ARENA_COLLECTOR_LEDGER_FILE", "data/ledger.jsonl", str, "원장 파일(JSONL)")
    collector_readers: list[str] = F("ARENA_COLLECTOR_READERS", [], _list, "전체 열람 허용 공개키(쉼표 구분)")
    # ledger rules
    contract_roles: list[str] = F("ARENA_CONTRACT_ROLES", ["record", "review"], _list, "역할 계약에 허용되는 역할")
    access_log_size: int = F("ARENA_ACCESS_LOG_SIZE", 50, int, "접근 기록 보관 건수")
    # search
    search_k: int = F("ARENA_SEARCH_K", 3, int, "검색 기본 상위 건수")
    search_max_k: int = F("ARENA_SEARCH_MAX_K", 50, int, "검색 최대 건수")
    bm25_k1: float = F("ARENA_BM25_K1", 1.5, float, "BM25 k1")
    bm25_b: float = F("ARENA_BM25_B", 0.75, float, "BM25 b")
    # display
    pen_name_prefix: str = F("ARENA_PEN_NAME_PREFIX", "필명-", str, "표시용 이름 접두사")
    pen_name_len: int = F("ARENA_PEN_NAME_LEN", 6, int, "표시용 이름에 쓰는 공개키 글자 수")
    # llm (used from phase 2)
    llm_base_url: str | None = F("ARENA_LLM_BASE_URL", None, _opt, "OpenAI 호환 엔드포인트(삼성SDS Cloud AI 서비스)")
    llm_api_key: str | None = F("ARENA_LLM_API_KEY", None, _opt, "그 엔드포인트의 API 키")
    llm_model_agent: str | None = F("ARENA_LLM_MODEL_AGENT", None, _opt, "비서 에이전트용 모델")
    llm_model_persona: str | None = F("ARENA_LLM_MODEL_PERSONA", None, _opt, "페르소나용 모델")
    llm_concurrency: int = F("ARENA_LLM_CONCURRENCY", 6, int, "LLM 동시 호출 상한")

    @classmethod
    def env_keys(cls) -> list[str]:
        return [f.metadata["key"] for f in fields(cls)]

    @classmethod
    def describe(cls) -> list[tuple[str, Any, str]]:
        return [(f.metadata["key"], f.metadata["default"], f.metadata["doc"]) for f in fields(cls)]

    @classmethod
    def load(cls, env: dict | None = None, dotenv_path: str | None = ".env") -> "Settings":
        merged: dict[str, str] = {}
        if dotenv_path and os.path.exists(dotenv_path):
            merged.update({k: v for k, v in dotenv_values(dotenv_path).items() if v is not None})
        merged.update(os.environ if env is None else env)
        values = {}
        for f in fields(cls):
            key = f.metadata["key"]
            raw = merged.get(key)
            if raw is None or raw == "":
                d = f.metadata["default"]
                values[f.name] = list(d) if isinstance(d, list) else d
                continue
            try:
                values[f.name] = f.metadata["parse"](raw)
            except (TypeError, ValueError) as e:
                raise ConfigError(f"{key} 값이 잘못되었습니다: {raw!r} ({e})") from e
        return cls(**values)

    def require(self, *names: str) -> None:
        by_name = {f.name: f.metadata["key"] for f in fields(self)}
        missing = [by_name[n] for n in names if getattr(self, n) in (None, "", [])]
        if missing:
            raise ConfigError("필수 설정이 없습니다: " + ", ".join(missing))

    def key_of(self, name: str) -> str:
        return next(f.metadata["key"] for f in fields(self) if f.name == name)
