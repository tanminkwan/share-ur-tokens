"""Settings from the environment (CONNECTIVITY_*). Every constant of the service is here (none in code)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields


def _list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def _bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def F(key: str, default, parse, doc: str):
    meta = {"key": key, "parse": parse, "doc": doc}
    if isinstance(default, list):
        return field(default_factory=lambda: list(default), metadata=meta)
    return field(default=default, metadata=meta)


@dataclass
class ConnectivitySettings:
    host: str = F("CONNECTIVITY_HOST", "127.0.0.1", str, "듣는 주소(container 안에서는 0.0.0.0)")
    port: int = F("CONNECTIVITY_PORT", 9200, int, "HTTP 포트")
    public_url: str = F("CONNECTIVITY_PUBLIC_URL", "", str, "붙은 쪽이 남에게 알릴 주소의 앞부분(예: https://connect.example.com). 비면 http://HOST:PORT")
    max_attached: int = F("CONNECTIVITY_MAX_ATTACHED", 1000, int, "동시에 붙을 수 있는 키 수")
    max_inflight: int = F("CONNECTIVITY_MAX_INFLIGHT", 16, int, "한 키에게 동시에 전달 중인 요청 수 상한")
    rate_per_sec: float = F("CONNECTIVITY_RATE_PER_SEC", 20.0, float, "출발 IP 하나가 한 키에게 보낼 수 있는 초당 요청 수")
    max_body_bytes: int = F("CONNECTIVITY_MAX_BODY_BYTES", 1048576, int, "요청·응답 body 크기 상한(바이트)")
    request_timeout_sec: float = F("CONNECTIVITY_REQUEST_TIMEOUT_SEC", 30.0, float, "전달한 요청의 응답을 기다리는 시간(초)")
    attach_grace_sec: float = F("CONNECTIVITY_ATTACH_GRACE_SEC", 60.0, float, "poll이 없을 때 session을 닫기까지의 시간(초)")
    poll_hold_sec: float = F("CONNECTIVITY_POLL_HOLD_SEC", 25.0, float, "poll 하나를 붙들고 기다리는 시간의 상한(초)")
    paths: list = F("CONNECTIVITY_PATHS", [], _list, "전달하는 경로(쉼표 구분, 정확히 같아야 함). 비면 모든 경로")
    drop_headers: list = F("CONNECTIVITY_DROP_HEADERS", ["cookie", "set-cookie"], _list, "양쪽으로 전달하지 않는 헤더(hop-by-hop 헤더는 늘 버림)")
    allow_keys_file: str = F("CONNECTIVITY_ALLOW_KEYS_FILE", "", str, "붙을 수 있는 공개키 목록 파일(줄마다 하나, #은 주석). 비면 서명이 맞는 누구나")
    probe_allow: list = F("CONNECTIVITY_PROBE_ALLOW", [], _list, "inbound 점검에서 되돌아가 볼 수 있는 사설 대역(CIDR). 비면 공인 주소만")
    check_per_hour: int = F("CONNECTIVITY_CHECK_PER_HOUR", 30, int, "한 키가 inbound 점검을 요청할 수 있는 시간당 횟수")
    reach_timeout_sec: float = F("CONNECTIVITY_REACH_TIMEOUT_SEC", 5.0, float, "inbound 점검에서 되돌아가 보는 제한 시간(초)")
    stun_port: int = F("CONNECTIVITY_STUN_PORT", 0, int, "STUN(UDP) 포트. 0이면 열지 않음, 표준은 3478")
    sig_window_sec: float = F("CONNECTIVITY_SIG_WINDOW_SEC", 60.0, float, "서명 시각 허용 폭(초)")
    trust_forwarded: bool = F("CONNECTIVITY_TRUST_FORWARDED", False, _bool, "앞에 둔 reverse proxy의 X-Forwarded-For를 출발 IP로 믿을지")

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ConnectivitySettings":
        env = os.environ if env is None else env
        values = {}
        for f in fields(cls):
            raw = env.get(f.metadata["key"])
            if raw not in (None, ""):
                try:
                    values[f.name] = f.metadata["parse"](raw)
                except (TypeError, ValueError) as e:
                    raise ValueError(f"{f.metadata['key']} 값이 잘못되었습니다: {raw!r} ({e})") from e
        return cls(**values)

    @property
    def base_url(self) -> str:
        return (self.public_url or f"http://{self.host}:{self.port}").rstrip("/")
