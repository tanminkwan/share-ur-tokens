# 2단계 테스트 결과: 범용화와 peer 핵심

- 실행일: 2026-10-30
- 브랜치: `arena-platform-20261030`
- 환경: Python 3.11.9, pytest 9.2.0, pytest-asyncio 1.4.1, Linux
- 실제 LLM: 삼성SDS Cloud AI 서비스(OpenAI 호환), 모델 `openai/gpt-oss-120b`

## 1. 자동 테스트

```
.venv/bin/python -m pytest
117 passed in 14.79s
```

실패 0건, 건너뛴 것 0건. 실제 LLM 테스트 3건이 포함된 실행이다.

| 파일 | 건수 | 층 | 요구사항 |
|---|---|---|---|
| `tests/test_ledger.py` | 18 | 단위 | R2, P2-A2 ~ A6, A9 |
| `tests/test_layering.py` | 2 | 소스 검사 | P2-A1 (플랫폼에 앱 용어 없음, 앱·시연 import 없음) |
| `tests/test_recorder_service.py` | 9 | 단위 | R3, P2-A7 |
| `tests/test_recorder_api.py` | 7 | API (ASGI) | R3 |
| `tests/test_broker_service.py` | 16 | 단위 | R4, P2-A8, A10 |
| `tests/test_broker_api.py` | 7 | API (ASGI) | R4 |
| `tests/test_config.py` | 6 | 단위 | R1, P2-A4, B1 |
| `tests/test_crypto.py`, `tests/test_search.py` | 14 | 단위 | R1 |
| `tests/test_llm.py` | 10 | 단위 (가짜 HTTP 엔드포인트) | P2-B2, B3 |
| `tests/test_a2a.py` | 2 | 실제 A2A 서버 + 메모리 전송 | P2-B6, B7 |
| `tests/test_area.py` | 3 | 단위 | P2-B4, B15 |
| `tests/test_peer.py` | 9 | 단위 | P2-B5, B8, B9, B11, B14, B16 |
| `tests/test_record_role.py` | 1 | 단위 + ASGI | P2-B10 |
| `tests/test_events_log.py` | 1 | 단위 | P2-B13 |
| `tests/test_processes.py` | 4 | 실제 프로세스 | R2-12, R3-8, R4-11 |
| `tests/motif/test_motif_memory.py` | 5 | 경연 모티브, 메모리 세계 | P2-C1 ~ C6 |
| `tests/live/test_llm_live.py` | 2 | **실제 LLM** | P2-B2, B5, E2 |
| `tests/live/test_motif_live.py` | 1 | **실제 프로세스 + 실제 LLM** | P2-C7, E2 |
| **합계** | **117** | | |

## 2. 경연 모티브: 실제 프로세스와 실제 LLM (P2-C7)

broker 두 곳(응모 그룹, 진행자가 소유한 닫힌 심사 그룹)을 `python -m arena.broker` 별도 프로세스로 띄웠다. peer 6개(진행자, 기록자, 사장님, 심사자, 응모자 2명)는 각자 A2A 서버로 떴고, 기록자 peer는 recorder API를 따로 열어 원장을 파일에 남겼다. 소요 시간은 약 9.5초다.

| 단계 | 결과 |
|---|---|
| 프로필 요약 | 6개 모두 실제 LLM이 요약, 대체값 사용 0건 |
| 기록자 찾기와 계약 | broker 역할 검색(`record`)으로 찾고, 검색 결과에 실린 recorder 주소로 원장에 기록 |
| **사장님 결재** | 결재자 라벨(`직책:대표이사`)로 찾아 A2A로 결재 요청. LLM이 사장님 역할로 승인. 이벤트 선언에 진행자와 사장님 두 서명 |
| 심사자 계약 | 닫힌 심사 그룹 broker에서 역할(`review`)로 찾고, LLM이 심사자 역할로 수락 |
| 응모자 확인 | 공지를 라벨로 보고, recorder에서 이벤트·결재·계약을 확인하고, broker에서 결재자 라벨을 확인 |
| 응모 | LLM이 응모자 역할로 아이디어를 쓰고, 먼저 등록 → A2A 제출 → 공유 기록, 영수증 2건씩 보관 |
| 심사와 채택 | 심사자가 2건에 7점과 8점, 8점 1건 채택 |
| 원장 | 12건: 이벤트 1, 계약 2, 먼저 등록 2, 공유 4, 판정 3. 감사 정상, 사장님 결재 집계 1 |

실행 기록은 [evidence/live-motif-gpt-oss-120b.txt](evidence/live-motif-gpt-oss-120b.txt)에 있다.

**발견한 것**: LLM이 사람 역할로 낸 판단은 맞았지만 이유 문장의 질은 낮았다. 결재 이유가 "결재 여부 판단 및 조언", 수락 이유가 "아래와 같이 진행하면 됩니다."로 나왔다. 이 문장은 테스트 대역(`LLMOwner`)의 프롬프트에서 나오며 플랫폼 기능에는 영향이 없다. 이유를 화면에 보이는 단계에서 프롬프트를 다듬는다.

## 3. 경연 모티브: 메모리 세계 (P2-C1 ~ C6)

| 테스트 | 확인한 것 |
|---|---|
| 결재와 공지 | 원장 순서가 이벤트 → 기록자 계약 → 심사자 계약. 이벤트에 진행자·사장님 서명. 공지에 심사자 없음. 공지는 삼성SDS 라벨 6명에게 보이고 협력사 1명에게는 안 보임 |
| 결재 반려 | 사장님이 반려하면 이벤트도 공지도 없음 |
| 응모와 완료 | 응모자 3명 모두 결재·계약·결재자 라벨을 확인한 뒤 응모. policy가 심사자 이름을 숨김. 기여 집계: 사장님 결재 1, 심사자 역할 1·판정 3, 채택자는 받은 판정 심사 1·채택 1 |
| policy 집행 | 계약 없는 심사 거절, 발행자 아닌 채택 거절, 기록자의 응모 거절(원장과 진행자 양쪽), 한 사람 두 번 제출 거절 |
| 감사와 열람 | 허용 키만 전체 열람. 이벤트 선언에서 결재자를 몰래 지우면 `TAMPERED at seq 0` |

## 4. 범위 조정 (사용자 결정 2026-10-30)

- 처음 설계에 있던 **앱 분리(아이디어 경연 앱 다섯 개)와 시연 장치 이전, `app/` 삭제는 하지 않았다.** 플랫폼 개발 범위 밖이기 때문이다. 경연은 `tests/motif/`의 대역 앱 네 개(결재, 역할 수락, 제출 받기, 심사 판정)로만 재현했다.
- `collector`는 실제 역할에 맞게 `recorder`(기록자)로 이름을 바꿨다.
- 다음 단계는 **기본 서빙 peer**다. 고급 검색 peer(임베딩 + 벡터 거리)와 관전용 절대자 peer가 확정 대상이다([../plan.md](../plan.md) 3단계).

## 5. 남은 한계

- Claude 백엔드(`ARENA_LLM_BACKEND=claude`)는 키가 없어 실제로 돌려 보지 못했다. 설정 검사만 테스트했다.
- 서로 다른 PC 사이의 A2A 호출은 확인하지 않았다(모두 한 PC의 다른 포트).
- broker의 프로필·공지·허가는 메모리에만 있다. 원장만 파일에 남는다.
- 재전송은 서명 요청의 시각 폭과 원장의 nonce로만 막는다.
