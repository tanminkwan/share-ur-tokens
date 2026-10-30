# 1단계 테스트 결과: 인프라 서비스 (broker · collector)

- 실행일: 2026-10-30
- 브랜치: `arena-platform-20261030`
- 환경: Python 3.11.9, pytest 9.2.0, pytest-asyncio 1.4.1, Linux

## 1. 자동 테스트

```
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
74 passed in 3.34s
```

실패 0건, 건너뛴 것 0건.

| 파일 | 건수 | 층 | 요구사항 |
|---|---|---|---|
| `tests/test_config.py` | 6 | 단위 | R1-1, R1-2 |
| `tests/test_crypto.py` | 11 | 단위 | R1-3, R1-4, R1-5 |
| `tests/test_search.py` | 3 | 단위 | R1-6 |
| `tests/test_ledger.py` | 13 | 단위 | R2-1 ~ R2-12 |
| `tests/test_collector_service.py` | 9 | 단위 | R3-1 ~ R3-8 |
| `tests/test_collector_api.py` | 7 | API (ASGI) | R3-1 ~ R3-5, R3-9 (HTTP·메모리 클라이언트 양쪽) |
| `tests/test_broker_service.py` | 14 | 단위 (메모리 이웃 3곳) | R4-1 ~ R4-10 |
| `tests/test_broker_api.py` | 7 | API (ASGI) | R4-1, R4-7, R4-9, R4-12 (HTTP·메모리 클라이언트 양쪽) |
| `tests/test_processes.py` | 4 | 실제 프로세스 + HTTP | R2-12, R3-8, R4-11 |
| **합계** | **74** | | |

가장 오래 걸린 테스트는 broker 프로세스 2개를 띄우는 통합 테스트(약 1초)다.

### 실제 프로세스 테스트에서 확인한 것

- broker A·B를 별도 프로세스로 띄우면 A에 올린 공지가 HTTP로 B에 전달되고, B에 프로필이 있는 peer가 B에서 그 공지를 본다.
- B에서 역할 검색을 하면 A에 있는 기록자 프로필이 A 출처로 함께 나온다.
- A에서 마감하면 B에서도 사라진다. B를 멈춰도 A는 계속 답한다.
- 소유자 공개키를 설정한 broker는 허가 없는 게시와 서명 없는 검색을 거부하고, 소유자 허가 뒤에는 받아들인다.
- collector를 재시작해도 같은 기록자 키와 같은 체인으로 이어 쓴다. 원장 파일의 과거 항목을 고치면 collector가 `TAMPERED at seq 0`을 알리고 시작을 거부한다.

## 2. 기존 데모 회귀 확인 (R6-3)

이번 단계는 `app/`을 건드리지 않았다. 기존 데모를 삼성SDS Cloud AI 서비스(OpenAI 호환, `openai/gpt-oss-120b`)로 한 번 끝까지 돌렸다.

```
set -a && . ./.env && set +a
.venv/bin/python -m app.run_demo --call "신입 사원이 입사 첫 달에 회사에 빨리 적응하도록 돕는 아이디어를 모집합니다." --quiet 40 --port 8766
```

| 항목 | 결과 |
|---|---|
| 종료 코드 | 0 |
| 원장 | 28건 (계약 3, 먼저 등록 4, 공유 12, 피드백 9), 감사 정상 |
| 아이디어 / 채택 | 4건 / 2건 |
| 권한 없는 열람 | 거부됨 |
| 과거 항목 변조 | 절대자가 `TAMPERED at seq 1 (hash chain)`으로 탐지 |
| LLM 호출 실패 | 1건 (아래) |

실행 기록은 [evidence/regression-app-demo-gpt-oss-120b.txt](evidence/regression-app-demo-gpt-oss-120b.txt)에 있다(파이썬 종료 시 나오는 uvicorn 취소 traceback은 뺐다).

**발견한 것 (기존 동작, 2단계 과제)**

- 마감 뒤 이벤트 peer 비서의 첫 LLM 응답이 비어 있어(`empty content`) 에이전트 루프가 바로 끝났고, 고정 순서(계약된 심사자에게 심사 요청 → 점수순 채택)로 대체되었다. 이 대체는 기존 설계대로이며 문서(`docs/a2a-transaction.md` 5절)에도 적혀 있다. 2단계 LLM 어댑터에서 빈 응답 재시도를 넣는다.
- 채택된 아이디어 하나는 심사자 2명 중 1명의 점수만으로 평균이 계산되었다. 심사자 한 명이 그 아이디어를 빠뜨린 것으로 보이며, 2단계 심사자 앱에서 "모든 아이디어에 점수가 있는지" 검사를 넣는다.

## 3. 이름 변경과 설정 (R5)

- README, `docs/*.md`, `review/premises.md`에서 "에이전트 광장(Agent Agora)" 134곳을 "에이전트 아레나(Agent Arena)"로 바꿨다. 받침 차이로 조사도 바꿨다(은→는, 이→가, 을→를, 이다→다, 이라→라). 바꾼 뒤 남은 옛 이름은 0곳이다.
- 양식 원문(`docs/form-original.txt`)과 날짜 붙은 리뷰 기록은 손대지 않았다. `python3 review/check_form.py`는 7개 문항 모두 원문 그대로다.
- `.env`에 `ARENA_LLM_BASE_URL`, `ARENA_LLM_API_KEY`를 더했다(값은 기존 `SUT_LLM_*`와 같음). `Settings.require("llm_base_url", "llm_api_key")`로 읽히는 것을 확인했다. `SUT_` 키는 2단계에서 `app/`이 사라질 때 지운다.
- `.env.example`은 `Settings`의 모든 키를 담는다(테스트가 검사).

## 4. 요구사항과 다르게 한 것

| 항목 | 요구사항·설계 | 구현 | 이유 |
|---|---|---|---|
| 원장 시각 편차 규칙, 다른 기록자 항목 검증 경로 | 설계 초안에 있었음 | 뺌 | 사용자 지시: collector 분산은 마지막 단계, 지금은 보관소 하나 (7단계로 옮김) |
| 프로필 주소 | 주소를 본문에 따로 | 프로필 안에 넣어 서명 대상에 포함 | 남이 주소만 바꿔치기하는 것을 막기 위해 |

## 5. 남은 한계

- 서명 요청의 재전송은 시각 폭(기본 60초)으로만 막는다.
- broker의 프로필·공지·허가는 메모리에만 있다(재시작하면 peer가 다시 게시해야 한다). 원장만 파일에 남는다.
- 공지 공유는 이웃에 한 번만 전달한다(다단계 전파는 범위 밖).
- 이 단계 테스트에는 LLM 호출이 없다. broker와 collector는 설계상 AI가 없기 때문이다.
