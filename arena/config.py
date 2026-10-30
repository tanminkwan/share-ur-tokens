"""Settings: every tunable value comes from the environment (and optionally a .env file). Nothing is hardcoded elsewhere.

    s = Settings.load()                       # os.environ + ./.env
    s = Settings.load(env={...}, dotenv_path=None)  # tests: fully isolated

EnvSettings is the mechanism; Settings holds the platform's keys. Apps and the demo declare their own
EnvSettings subclasses the same way. Add a setting by adding one F(...) field; `.env.example` must list it (a test checks).
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


def _bool(v: str) -> bool:
    t = v.strip().lower()
    if t in ("1", "true", "yes", "on"):
        return True
    if t in ("0", "false", "no", "off"):
        return False
    raise ValueError("true 또는 false여야 합니다")


def F(key: str, default: Any, parse: Callable[[str], Any], doc: str):
    meta = {"key": key, "parse": parse, "doc": doc, "default": default}
    if isinstance(default, list):
        return field(default_factory=lambda d=default: list(d), metadata=meta)
    return field(default=default, metadata=meta)


class EnvSettings:
    """mechanism shared by every settings class (platform, apps, demo)"""

    @classmethod
    def env_keys(cls) -> list[str]:
        return [f.metadata["key"] for f in fields(cls)]

    @classmethod
    def describe(cls) -> list[tuple[str, Any, str]]:
        return [(f.metadata["key"], f.metadata["default"], f.metadata["doc"]) for f in fields(cls)]

    @classmethod
    def load(cls, env: dict | None = None, dotenv_path: str | None = ".env"):
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


@dataclass
class Settings(EnvSettings):
    # network
    host: str = F("ARENA_HOST", "127.0.0.1", str, "서비스가 듣는 주소")
    http_timeout_sec: float = F("ARENA_HTTP_TIMEOUT_SEC", 60.0, float, "클라이언트 기본 제한 시간(초)")
    neighbor_timeout_sec: float = F("ARENA_NEIGHBOR_TIMEOUT_SEC", 10.0, float, "이웃 broker 호출 제한 시간(초)")
    sig_window_sec: float = F("ARENA_SIG_WINDOW_SEC", 60.0, float, "서명 요청의 시각 허용 폭(초)")
    # broker
    broker_port: int = F("ARENA_BROKER_PORT", 9110, int, "broker 포트")
    broker_name: str = F("ARENA_BROKER_NAME", "broker", str, "broker 이름")
    genesis_group_id: str = F("ARENA_GENESIS_GROUP_ID", "public", str, "태초부터 있는 만민 그룹의 식별자(열린 그룹, 선언 없이 쓰임)")
    broker_group_id: str | None = F("ARENA_BROKER_GROUP_ID", None, _opt, "이 broker가 속한 broker 그룹 식별자(같은 그룹의 broker는 같은 값, 비면 만민 그룹)")
    broker_neighbors: list[str] = F("ARENA_BROKER_NEIGHBORS", [], _list, "이웃 broker 주소(쉼표 구분)")
    broker_owner_pub: str | None = F("ARENA_BROKER_OWNER_PUB", None, _opt, "닫힌 그룹 소유자 공개키(비면 열린 그룹)")
    broker_key_file: str = F("ARENA_BROKER_KEY_FILE", "data/broker.key", str, "broker 키 파일")
    # recorder
    recorder_port: int = F("ARENA_RECORDER_PORT", 9120, int, "recorder 포트")
    recorder_name: str = F("ARENA_RECORDER_NAME", "recorder", str, "recorder 이름")
    recorder_key_file: str = F("ARENA_RECORDER_KEY_FILE", "data/recorder.key", str, "기록자 키 파일")
    recorder_ledger_file: str = F("ARENA_RECORDER_LEDGER_FILE", "data/ledger.jsonl", str, "원장 파일(JSONL)")
    recorder_require_group: bool = F("ARENA_RECORDER_REQUIRE_GROUP", True, _bool, "모든 항목이 선언된 broker 그룹의 group_id를 쓰도록 요구할지")
    recorder_readers: list[str] = F("ARENA_RECORDER_READERS", [], _list, "전체 열람 허용 공개키(쉼표 구분)")
    # ledger rules
    access_log_size: int = F("ARENA_ACCESS_LOG_SIZE", 50, int, "접근 기록 보관 건수")
    # search
    search_k: int = F("ARENA_SEARCH_K", 3, int, "검색 기본 상위 건수")
    search_max_k: int = F("ARENA_SEARCH_MAX_K", 50, int, "검색 최대 건수")
    bm25_k1: float = F("ARENA_BM25_K1", 1.5, float, "BM25 k1")
    bm25_b: float = F("ARENA_BM25_B", 0.75, float, "BM25 b")
    # display
    pen_name_prefix: str = F("ARENA_PEN_NAME_PREFIX", "필명-", str, "표시용 이름 접두사")
    pen_name_len: int = F("ARENA_PEN_NAME_LEN", 6, int, "표시용 이름에 쓰는 공개키 글자 수")
    # llm
    llm_backend: str = F("ARENA_LLM_BACKEND", "compat", str, "LLM 백엔드: compat(OpenAI 호환, 삼성SDS Cloud AI 서비스) 또는 claude")
    llm_base_url: str | None = F("ARENA_LLM_BASE_URL", None, _opt, "OpenAI 호환 엔드포인트 주소")
    llm_api_key: str | None = F("ARENA_LLM_API_KEY", None, _opt, "그 엔드포인트의 API 키")
    llm_claude_api_key: str | None = F("ARENA_LLM_CLAUDE_API_KEY", None, _opt, "Claude API 키(백엔드가 claude일 때)")
    llm_model_agent: str | None = F("ARENA_LLM_MODEL_AGENT", None, _opt, "비서 에이전트용 모델")
    llm_model_persona: str | None = F("ARENA_LLM_MODEL_PERSONA", None, _opt, "페르소나(사람 역할)용 모델")
    llm_concurrency: int = F("ARENA_LLM_CONCURRENCY", 6, int, "LLM 동시 호출 상한")
    llm_retries: int = F("ARENA_LLM_RETRIES", 2, int, "빈 응답·JSON 아님·HTTP 오류일 때 다시 묻는 횟수")
    llm_max_tokens: int = F("ARENA_LLM_MAX_TOKENS", 6000, int, "응답 최대 토큰")
    llm_timeout_sec: float = F("ARENA_LLM_TIMEOUT_SEC", 240.0, float, "LLM 호출 제한 시간(초)")
    llm_effort: str = F("ARENA_LLM_EFFORT", "low", str, "기본 추론 강도(reasoning_effort)")
    # peer
    a2a_timeout_sec: float = F("ARENA_A2A_TIMEOUT_SEC", 120.0, float, "peer 사이 A2A 호출 제한 시간(초)")
    profile_ttl_sec: float = F("ARENA_PROFILE_TTL_SEC", 604800.0, float, "프로필 만기(초)")
    profile_lines_max: int = F("ARENA_PROFILE_LINES_MAX", 12, int, "프로필 요약에 넣는 공개 영역 최근 줄 수")
    area_notes_file: str = F("ARENA_AREA_NOTES_FILE", "notes.md", str, "공개 영역에서 경험 노트를 덧붙이는 파일")
    area_owner_prefix: str = F("ARENA_AREA_OWNER_PREFIX", "_", str, "이 글자로 시작하는 문서는 소유자 전용")
    event_log_size: int = F("ARENA_EVENT_LOG_SIZE", 2000, int, "관측 로그 보관 건수")
    # embedding (bge-m3 service) and the advanced search peer
    embed_url: str | None = F("ARENA_EMBED_URL", None, _opt, "임베딩 서비스 주소(bge-m3, POST /embed)")
    embed_batch: int = F("ARENA_EMBED_BATCH", 32, int, "임베딩 한 번에 보내는 글 수")
    embed_timeout_sec: float = F("ARENA_EMBED_TIMEOUT_SEC", 60.0, float, "임베딩 호출 제한 시간(초)")
    embed_retries: int = F("ARENA_EMBED_RETRIES", 2, int, "임베딩 실패 시 다시 묻는 횟수")
    search_sync_sec: float = F("ARENA_SEARCH_SYNC_SEC", 5.0, float, "검색 peer 색인 갱신 주기(초)")
    search_min_score: float = F("ARENA_SEARCH_MIN_SCORE", 0.0, float, "검색 peer가 버리는 최소 유사도")
    search_peer_port: int = F("ARENA_SEARCH_PEER_PORT", 9130, int, "검색 peer A2A 포트")
    search_peer_key_file: str = F("ARENA_SEARCH_PEER_KEY_FILE", "data/search-peer.key", str, "검색 peer 키 파일")
    search_peer_area: str = F("ARENA_SEARCH_PEER_AREA", "data/areas/search-peer", str, "검색 peer 공개 영역 폴더")
    search_peer_labels: list[str] = F("ARENA_SEARCH_PEER_LABELS", [], _list, "검색 peer 라벨(넓을수록 많은 공지를 색인)")
    search_peer_brokers: list[str] = F("ARENA_SEARCH_PEER_BROKERS", [], _list, "검색 peer가 색인할 broker 그룹: 그룹=주소, 쉼표 구분")
    # the god peer (spectator: reads whole ledgers, audits, statistics)
    god_peer_port: int = F("ARENA_GOD_PEER_PORT", 9140, int, "god peer A2A 포트")
    god_peer_key_file: str = F("ARENA_GOD_PEER_KEY_FILE", "data/god-peer.key", str, "god peer 키 파일")
    god_peer_area: str = F("ARENA_GOD_PEER_AREA", "data/areas/god-peer", str, "god peer 공개 영역 폴더")
    god_peer_labels: list[str] = F("ARENA_GOD_PEER_LABELS", [], _list, "god peer 라벨")
    god_peer_brokers: list[str] = F("ARENA_GOD_PEER_BROKERS", [], _list, "god peer가 보는 broker 그룹: 그룹=주소, 쉼표 구분")
    god_viewers: list[str] = F("ARENA_GOD_VIEWERS", [], _list, "관전 결과를 볼 수 있는 공개키(쉼표 구분)")
    god_cache_sec: float = F("ARENA_GOD_CACHE_SEC", 1.0, float, "관전 결과 캐시(초)")
    god_top_flows: int = F("ARENA_GOD_TOP_FLOWS", 5, int, "공유 흐름 상위 개수")
    # phase 4: public area by address, direct requests, track records, capability labels
    area_cache_sec: float = F("ARENA_AREA_CACHE_SEC", 60.0, float, "URL 공개 영역을 다시 가져오기 전 캐시(초)")
    area_http_token: str | None = F("ARENA_AREA_HTTP_TOKEN", None, _opt, "URL 공개 영역 인증 토큰(Bearer, 비면 인증 없음)")
    area_http_timeout_sec: float = F("ARENA_AREA_HTTP_TIMEOUT_SEC", 10.0, float, "URL 공개 영역 가져오기 제한 시간(초)")
    area_local_notes_dir: str = F("ARENA_AREA_LOCAL_NOTES_DIR", "data/area-notes", str, "URL 공개 영역의 경험 노트·소유자 메모를 쓰는 로컬 폴더")
    solicit_inbox_size: int = F("ARENA_SOLICIT_INBOX_SIZE", 200, int, "직접 요청 받은 편지함 크기")
    recorder_public_track: bool = F("ARENA_RECORDER_PUBLIC_TRACK", True, _bool, "recorder가 공개키별 실적 집계를 공개할지(GET /track/{pub})")
    peer_track_recorders: list[str] = F("ARENA_PEER_TRACK_RECORDERS", [], _list, "내 실적을 확인할 recorder 주소(쉼표 구분, 쓴 recorder는 자동으로 더해짐)")
    label_auto: bool = F("ARENA_LABEL_AUTO", True, _bool, "역량 라벨 자율 갱신을 켤지")
    label_role_prefix: str = F("ARENA_LABEL_ROLE_PREFIX", "역할:", str, "원장 근거 역량 라벨 접두사")
    label_field_prefix: str = F("ARENA_LABEL_FIELD_PREFIX", "분야:", str, "지식 근거 역량 라벨 접두사")
    label_role_min: int = F("ARENA_LABEL_ROLE_MIN", 1, int, "역할 라벨을 붙이는 최소 계약 수")
    label_field_max: int = F("ARENA_LABEL_FIELD_MAX", 5, int, "분야 라벨 최대 개수")
    label_evidence_min_len: int = F("ARENA_LABEL_EVIDENCE_MIN_LEN", 8, int, "분야 라벨 근거 문장의 최소 길이")
    label_field_vocab: list[str] = F("ARENA_LABEL_FIELD_VOCAB", [], _list, "분야 표준 목록(쉼표 구분). 비면 자유 이름, 있으면 목록 안의 이름만")
    # the genesis: god creates the genesis broker and the recorder (python -m arena.genesis)
    genesis_dir: str = F("ARENA_GENESIS_DIR", "data/genesis", str, "제네시스 키·원장·공개 영역 폴더")
    genesis_broker_name: str = F("ARENA_GENESIS_BROKER_NAME", "genesis-broker", str, "만민 broker 이름")
    genesis_broker_port: int = F("ARENA_GENESIS_BROKER_PORT", 9100, int, "만민 broker 포트")
    genesis_recorder_port: int = F("ARENA_GENESIS_RECORDER_PORT", 9101, int, "제네시스 기록자 peer A2A 포트")
    genesis_recorder_api_port: int = F("ARENA_GENESIS_RECORDER_API_PORT", 9102, int, "제네시스 기록자 recorder API 포트")
    genesis_god_port: int = F("ARENA_GENESIS_GOD_PORT", 9103, int, "god peer A2A 포트")
    # the basic assistant: the primordial way to hold or join an event (natural-language rules + generic tools)
    assistant_max_steps: int = F("ARENA_ASSISTANT_MAX_STEPS", 8, int, "기본 비서가 입력 하나에 쓰는 최대 단계 수")
    assistant_transcript_max: int = F("ARENA_ASSISTANT_TRANSCRIPT_MAX", 60, int, "기본 비서가 LLM에 보여 주는 최근 기록 줄 수")
    assistant_watch_sec: float = F("ARENA_ASSISTANT_WATCH_SEC", 1.0, float, "기본 비서가 게시판의 새 공지를 확인하는 주기(초)")
    assistant_effort: str = F("ARENA_ASSISTANT_EFFORT", "low", str, "기본 비서의 추론 강도")
    event_request_ttl_sec: float = F("ARENA_EVENT_REQUEST_TTL_SEC", 600.0, float, "기본 비서가 보내는 직접 요청의 만기(초)")
    event_notice_ttl_sec: float = F("ARENA_EVENT_NOTICE_TTL_SEC", 3600.0, float, "기본 비서가 올리는 이벤트 공지의 만기(초)")
    event_store_dir: str = F("ARENA_EVENT_STORE_DIR", "data/events", str, "기본 비서가 참여 중인 이벤트를 저장하는 로컬 폴더(peer별 하위 폴더)")
    broker_state_file: str = F("ARENA_BROKER_STATE_FILE", "data/broker-state.json", str, "broker가 프로필·공지·가입 허가를 저장하는 파일(단독 실행)")
    recorder_access_log_file: str = F("ARENA_RECORDER_ACCESS_LOG_FILE", "data/recorder-access.jsonl", str, "recorder 열람 접근 기록 파일(단독 실행)")
    broker_failback_sec: float = F("ARENA_BROKER_FAILBACK_SEC", 30.0, float, "secondary broker로 넘어간 뒤 primary를 다시 시도하기까지(초)")
    assistant_idle_sec: float = F("ARENA_ASSISTANT_IDLE_SEC", 60.0, float, "열린 이벤트에 입력이 없을 때 기본 비서가 스스로 점검하기까지(초, 점검마다 두 배)")
    assistant_idle_max_checks: int = F("ARENA_ASSISTANT_IDLE_MAX_CHECKS", 5, int, "입력 없이 연달아 하는 점검의 최대 횟수")
