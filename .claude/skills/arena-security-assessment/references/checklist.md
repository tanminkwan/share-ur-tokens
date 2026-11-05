# 범주와 확인할 곳

| # | 범주 | 확인할 것 | 확인할 곳 (grep 예) |
|---|---|---|---|
| 1 | 전송 암호화 | TLS를 서비스가 직접 하나, 앞단이 필요한가. 비공개 내용(봉투, 창의 token)이 평문으로 오가나 | `arena/serve.py`, `grep -rniE "ssl|tls|certfile" arena` |
| 2 | 인증과 권한 | 쓰기는 서명이 필요한가, 읽기 중 무엇이 공개인가, 관리 기능(키 교체)이 네트워크에 있나 | `arena/signing.py`, `arena/recorder/api.py`의 `guarded`, `arena/broker/service.py`의 `is_member`, `dev/protocol.md` 4.1 |
| 3 | 빈도·크기 제한 | 요청 빈도 제한, HTTP 본문 크기 제한, 원장 항목 크기 상한, 연결 수 | `grep -rniE "rate|limit|throttl|max_body" arena`, `ARENA_LEDGER_*_MAX_BYTES` |
| 4 | 신원 위조(Sybil) | 키를 공짜로 만들 수 있나, 무엇이 가짜 다수를 막나(닫힌 그룹, 공동 서명, 스핑크스) | `arena/broker/service.py`, `dev/founding`, `arena/ledger/endorse.py` |
| 5 | 밖으로 나가는 요청(SSRF) | 남이 준 주소로 이 peer가 요청을 보내나(webhook, 프로필 URL, 앱 배포 주소, URL 공개 영역, 기록자 주소). 사설 주소를 막나 | `arena/a2a_push.py`의 `push_url_ok`, `arena/peer/app_install.py`, `arena/peer/url_area.py`, `httpx.AsyncClient` 사용처 |
| 6 | 사람의 창 | 어디서 듣나(기본 주소), token 방식, token이 URL·저장소 어디에 남나, XSS 방지 | `arena/bundled/web_api.py`의 `token_guard`, `common_static/token.js`, `common_static/dom.js`, `ARENA_PERSONAL_WEB_HOST`, `ARENA_GENESIS_GOD_WEB_HOST` |
| 7 | LLM 특유 | 모르는 상대의 글(공지, 규칙, 메시지)을 LLM이 읽나, 권리가 정해지는 행동 전에 사람 확인이 있나, 비용을 남이 일으킬 수 있나 | `arena/peer/assistant/`, 운전석(drive), `ARENA_ASSISTANT_MAX_STEPS` |
| 8 | 코드 실행 | 남이 만든 코드(앱)를 실행하나, 격리·해시·서명·소유자 승인 | `arena/peer/app_install.py`, `arena/peer/plugins.py`, `dev/app-guide.md` |
| 9 | 키와 비밀 | 키 파일 권한, OS key store, 백업 암호화, 온라인에 있는 키(운영 기록자 키), 오프라인 키(god), LLM API 키 | `arena/keys/`, `arena/crypto.py`의 `save`, `dev/phase8`, `.env.example` |
| 10 | 가용성과 단일 지점 | 기록자·broker가 하나인가, 백업, 디스크 증가(원장, 접근 기록, 이벤트 기록) | `dev/chain-policy.md` 8절, `ARENA_ACCESS_LOG_SIZE`, `ARENA_EVENT_LOG_SIZE` |
| 11 | 정보 노출 | 공개 조회가 누가 언제 누구와 했는지를 드러내나, 끌 수 있나 | `ARENA_RECORDER_PUBLIC_*`, `/log`, `/track`, `/events`, `/profiles`, 비공개 봉투 |
| 12 | 시간과 재전송 | 서명 시각 허용 폭, nonce, 시계 동기화 | `ARENA_SIG_WINDOW_SEC`, `unique_nonce`, `arena/signing.py` |
| 13 | 배치 | 컨테이너 사용자, network mode, 듣는 주소 기본값, 비밀이 이미지에 들어가나 | `deploy/image/Dockerfile`, `deploy/*/docker-compose.yml`, `dev/docker.md` |
| 14 | 기록과 감시 | 보안 사건을 무엇이 남기나(접근 기록, 거절 기록), 한곳에 모이나 | `arena/recorder/service.py`의 `_allowed`, `arena/events.py` |

## 등급 기준 (인터넷 노출 전제)

| 등급 | 뜻 |
|---|---|
| **높음** | 공개 전에 막아야 한다. 아무나 원격에서 쉽게 할 수 있고, 비밀 노출·제어권 상실·서비스 중단·비용 발생으로 이어진다 |
| **중간** | 공개 직후 막는다. 조건이 필요하거나 피해가 제한되지만 운영에 실제 피해를 준다 |
| **낮음** | 알고 운영한다. 이미 있는 방어로 대부분 막히거나 피해가 작다 |
