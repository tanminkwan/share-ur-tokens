# 시스템 개요 (기술 설계)

이 문서가 신청서와 나머지 근거 문서의 기준입니다. 용어는 [review/premises.md](../review/premises.md)를 따릅니다. 표의 **검증** 열은 2026-10-28에 실제로 실행해 확인한 것(✅), 문서·사양으로만 확인한 것(📄), 아직 확인하지 못한 것(❓)을 구분합니다.

## 1. 한 장 요약

| 질문 | 답 |
|---|---|
| peer와 broker는 무엇으로 만드는가 | 둘 다 **A2A 서버 + 클라이언트**를 가진 Python 프로세스다. broker는 "노출 접수·질의 응답"을 skill로 제공하는 A2A 에이전트다 |
| "p2p"는 정확히 무엇인가 | **거래 단계에서 broker를 거치지 않고 peer끼리 A2A로 직접 호출**하는 것이다. 호출 대상 주소는 답변지에 들어 있다 |
| 무엇이 분산이고 무엇이 아닌가 | 거래는 분산이다. 발견은 broker가 맡으며, broker는 domain별로 여러 개를 두고 서로 질의한다. **발견까지 탈중앙이라고 주장하지 않는다** |
| AI는 어디에 쓰는가 | 노출·요청의 구조화, 의미 매칭, 일치 근거 생성, 협상 중 제안 해석·생성. 규칙으로 되는 일은 규칙으로 한다 |
| LLM이 없어도 도는가 | 돈다. LLM 호출은 어댑터 뒤에 두고, 없으면 규칙 + TF-IDF 폴백으로 같은 흐름이 실행된다(품질은 낮아진다) |

## 2. 기술 스택

| 영역 | 선택 | 이유 | 검증 |
|---|---|---|---|
| 언어 | Python 3.11 | a2a-sdk가 3.10 이상 요구 | ✅ (이 PC의 기본 python3는 3.9라 3.11 가상환경 필요) |
| 에이전트 간 통신 | **A2A 1.0**, JSON-RPC 바인딩, 공식 `a2a-sdk` 1.3.0 (`a2a-sdk[http-server]`) | 표준 프로토콜이라 Agent Card 발견, 작업 상태, 다회 대화가 SDK에 있음 | ✅ spike로 확인 |
| 서버 | Starlette + uvicorn (SDK 의존) | A2A 라우트 헬퍼가 Starlette용 | ✅ |
| 저장소 | SQLite(파일) | 설치가 필요 없고 broker마다 파일 하나 | ❓ 구현 시 확인 |
| 검색 | 필드 필터(SQL) + 임베딩 코사인 유사도(NumPy). 임베딩이 없으면 TF-IDF | 외부 벡터 DB 없이 노출 수백 건 규모는 충분 | ❓ |
| LLM | OpenAI 호환 HTTP 어댑터 1개(`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). 사내 허용 LLM을 가리킨다 | 사내 LLM이 정해지지 않았으므로 교체 가능하게 | ❓ 사내 LLM 미정 |
| 대시보드 | 단일 HTML + SSE (broker와 peer가 이벤트를 `/events`로 내보냄) | 별도 프론트엔드 빌드 없이 2일 안에 | ❓ |

A2A 사양에서 확인한 사실(📄, a2a-protocol.org): 최신 릴리스 1.0.0, 바인딩은 JSON-RPC·gRPC·HTTP+JSON, 작업 상태에 `INPUT_REQUIRED`·`COMPLETED`·`REJECTED` 등이 있고, 인증 방식은 Agent Card의 `securitySchemes`로 선언한다. Agent Card 경로는 SDK 기준 `/.well-known/agent-card.json`이다(✅ 실제 응답 확인).

## 3. 구성 요소와 배치

```
         ┌──────────── 사내망 ────────────┐
 peer F (제공자)  :9101   ─advertise─▶  broker-E (이벤트)  :9201 ◀─A2A 질의─▶ broker-G (물품)  :9202
 peer H (제공자)  :9102   ─advertise─▶  broker-G                              (각자 SQLite)
 peer C (소비자)  :9103   ─query────▶  broker-E                      
        │                         ◀─answer_sheet(공급자 주소 포함)
        └────── A2A 직접 호출(broker 미경유) ──────▶ peer F, peer H
```

| 프로세스 | 하는 일 | A2A 서버 skill | A2A 클라이언트로 하는 일 |
|---|---|---|---|
| 제공자 peer | 노출 등록, 거래 단계에서 조건 판단·확정 | 거래 skill(예: `lend-projector`, `seat-reservation`) | broker에 `advertise` |
| 소비자 peer | 요청 공개, 후보 선택, 협상 | (필요 시 알림 수신) | broker에 `query`, 공급자에 거래 메시지 |
| broker | 노출 색인, 질의 처리, broker 간 질의 | `advertise`, `query`, `broker_query` | 다른 broker에 `broker_query` |

한 프로세스가 제공자와 소비자를 겸할 수 있습니다(서버와 클라이언트를 둘 다 가지므로).

## 4. A2A로의 매핑

모든 통신이 A2A 메시지입니다. 별도 프로토콜을 만들지 않고, 메시지의 `data` 파트에 JSON을 싣습니다.

| 업무 개념 | A2A 구현 | 비고 |
|---|---|---|
| 노출 | broker에 `SendMessage`, data 파트 = `advertise` JSON | 즉시 응답(`COMPLETED`) |
| 요청 | broker에 `SendMessage`, data 파트 = `query` JSON | 결과는 Artifact로 `answer_sheet` |
| broker 간 질의 | broker → broker `SendMessage`, data 파트 = `broker_query` | 응답은 Artifact |
| 연결(p2p) | 답변지의 공급자 URL에서 Agent Card를 읽고 클라이언트 생성 | broker 미경유 |
| 제안 | 소비자 → 제공자 `SendMessage` (새 Task) | `TASK_STATE_WORKING` |
| 반제안 | 제공자가 `TASK_STATE_INPUT_REQUIRED`로 응답, 메시지에 반제안 | 같은 task id로 소비자가 이어서 답한다 |
| 수락·확정 | 소비자가 같은 task id로 수락 → 제공자가 Artifact(확정서) 발행 후 `COMPLETED` | |
| 거절 | `TASK_STATE_REJECTED` | |
| 권한 범위 초과 | 소비자 에이전트가 소유자 확인이 필요하다고 멈춤(소비자 측 상태) | 소유자 승인은 대시보드의 버튼 |

데이터 구조(필수 필드만):

```json
// advertise
{"peer_url": "http://host:9101", "summary": "...", "domain_hint": "equipment",
 "fields": {"item": "projector", "quantity": 2, "available": ["2026-11-06T14:00/16:00"]},
 "ttl_hours": 72, "owner": "dept-facilities"}

// query
{"text": "다음 주 금요일 오후에 쓸 프로젝터", "constraints": {"when": "2026-11-06"}, "hops_left": 1, "visited": []}

// answer_sheet (Artifact)
{"candidates": [{"peer_url": "...", "summary": "...", "why": "item=projector, 금요일 14시 가능", "score": 0.82, "source_broker": "broker-G"}]}
```

SQLite 테이블: `ads(id, peer_url, owner, domain, summary, fields_json, embedding, created_at, expires_at)` 하나가 핵심입니다.

## 5. 처리 흐름

1. **노출**: 제공자 → broker. broker가 domain을 판정한다(자기 domain이 아니면 맞는 broker 주소를 응답에 담아 돌려보내고 제공자가 재전송). LLM이 `fields`를 추출·검증하고(없으면 제공자가 보낸 `fields`를 그대로 사용), 임베딩을 계산해 저장한다.
2. **요청**: 소비자 → broker. `fields` 필터(시기, 물품)와 임베딩 유사도로 후보를 뽑는다. 후보가 `min_candidates`보다 적고 `hops_left > 0`이면 이웃 broker에 `broker_query`를 보낸다(`hops_left - 1`, `visited`에 자기 추가). 결과를 peer_url 기준으로 합치고 정렬한다.
3. **답변지**: 후보마다 일치 근거를 만든다. 근거는 **저장된 필드 값에서 조립**하고(예: "item=projector, 14시 가능"), LLM은 문장을 다듬을 뿐 새 사실을 만들지 못하게 한다.
4. **연결과 협상**: 소비자가 후보의 `peer_url`로 직접 `SendMessage`한다. 제공자는 자기 재고·일정에서 가능한 조건을 판단해 수락하거나 반제안한다. 협의는 최대 3회다.
5. **확정**: 제공자가 자기 상태(예약표)를 갱신하고 확정서를 Artifact로 돌려준다. 양쪽이 각자 로그를 남긴다.

## 6. 협상에 실제 내용을 넣는 방법

무상·교환뿐이면 협상이 날짜 맞추기로 줄어듭니다. 그래서 MVP는 **제약이 서로 얽히는 거래**를 시나리오에 둡니다.

| 변수 | 소비자의 제약 | 제공자의 제약 | 협상 |
|---|---|---|---|
| 시간 | 금요일 오후 2~4시 | 14시는 이미 예약, 15시 이후 가능 | 반제안 |
| 수량 | 2대 | 2대 중 1대만 가능한 시간대 | 분할 또는 시간 이동 |
| 묶음 | 세미나 좌석 + 프로젝터를 같은 날 | 두 제공자가 서로 다른 peer | 한쪽 확정 후 다른 쪽 조건에 맞춰 재협상 |
| 교환 | 소비자도 노출한 정보가 있음 | 맞교환을 조건으로 제시 | 서로의 노출 가치를 비교 |

제공자 에이전트의 판단은 코드가 가능 여부를 계산하고(`available` 필드와 예약표), LLM은 사람이 읽는 제안 문장과 소비자 측 선호 해석을 맡습니다. **가능 여부의 계산을 LLM에 맡기지 않습니다.** 환각으로 이중 예약이 나지 않게 하는 장치입니다.

## 7. p2p와 사내망

- peer 주소는 서버에서 호스팅하는 에이전트의 URL이다. 개인 PC에 인바운드 연결을 열 필요가 없도록, **에이전트는 사내 서버나 컨테이너에서 도는 것을 기본 배치로 한다**. 임직원은 소유자로서 설정만 한다.
- 사내망의 서버 간 직접 호출 허용 여부는 ❓ 미확인이다. 허용되지 않을 때의 후퇴안은 broker가 메시지를 중계하는 것이다. 그때 "거래가 broker를 거치지 않는다"는 주장은 성립하지 않으므로, 신청서는 그 한계를 문항 7에 명시한다.
- 인증은 Agent Card의 `securitySchemes`로 선언하고, MVP는 API 키 방식을 쓴다(SSO 연동은 범위 밖).

## 8. AI 사용 지점과 폴백

| 지점 | LLM 사용 | 폴백(LLM 없음) |
|---|---|---|
| 노출의 필드 추출 | 자연어에서 `fields` 추출 | 제공자가 폼으로 입력한 `fields` 사용 |
| 임베딩 | 임베딩 API | TF-IDF |
| 일치 근거 | 필드 값으로 조립한 문장을 다듬음 | 템플릿 문장 |
| 소비자 요청 해석 | 자연어 → `constraints` | 키워드·날짜 규칙 |
| 협상 문장 | 제안·반제안 문장 생성 | 템플릿 |

폴백을 두는 이유는 두 가지입니다. 시연 중 LLM이 지연되거나 실패해도 흐름이 멈추지 않게 하고, "AI 없이 되는 부분"과 "AI가 더하는 부분"을 비교 시연(LLM 켜기/끄기)으로 보여 줄 수 있게 합니다.

## 9. 검증 현황

| 항목 | 상태 | 근거 |
|---|---|---|
| A2A 서버·클라이언트가 같은 PC에서 직접 통신 | ✅ | `proto/spike_a2a.py` 실행 |
| Agent Card 발견 (`/.well-known/agent-card.json`) | ✅ | 같은 spike, 이름과 skill 목록 확인 |
| 다회 협상(`INPUT_REQUIRED` → 같은 task로 수락 → `COMPLETED` + Artifact) | ✅ | 같은 spike |
| broker 2개 간 `broker_query` | ❓ | 미구현 |
| LLM·임베딩 연동 | ❓ | 사내 LLM 미정 |
| 서로 다른 PC·서버 간 직접 호출 | ❓ | 사내망 정책 미확인 |
| 스트리밍(SSE) 표시 | ❓ | spike는 비스트리밍 |

spike 실행: `python3.11 -m venv .venv && .venv/bin/pip install "a2a-sdk[http-server]" && .venv/bin/python proto/spike_a2a.py`. 이 spike는 프로토콜 계층의 실현 가능성만 확인한 것으로, 규칙 기반이며 LLM을 쓰지 않습니다. 해커톤 규정이 사전 작성 코드를 제한하는지는 확인이 필요하며, 제한한다면 spike는 제출·재사용하지 않고 폐기합니다.

## 10. 2일 구현 분해

| 모듈 | 내용 | 의존 | 포기 기준 |
|---|---|---|---|
| M1 스키마·공통 | 위 JSON 스키마, LLM 어댑터와 폴백 | 없음 | 필수 |
| M2 제공자 peer | 예약표, 가능 여부 계산, 반제안 | M1 | 필수 |
| M3 broker | `advertise`/`query`, SQLite, 필터 + 유사도 | M1 | 필수 |
| M4 소비자 peer | 요청, 후보 선택, 협상 루프, 권한 범위 | M2, M3 | 필수 |
| M5 broker 간 질의 | `broker_query`, 홉 제한, 중복 제거 | M3 | 1일차 종료 시 미완이면 broker 1개로 시연하고 설명만 |
| M6 대시보드 | 이벤트 SSE, 3패널 | M2~M4 | 터미널 로그로 대체 가능 |
| M7 LLM 켜기/끄기 비교 | 같은 요청을 두 모드로 실행 | M1 | 시간이 남을 때 |

## 11. 기존 방식과의 차이

| 기존 방식 | 한계 | 이 구조 |
|---|---|---|
| 사내 게시판·메신저 공지 | 올린 사람이 대상을 알아야 하고, 필요한 사람이 우연히 봐야 한다 | 필요한 사람의 요청이 공급을 찾아간다 |
| 사내 검색·지식 관리 | 문서를 찾지, 지금 줄 수 있는 주체와 연결하지 못한다 | 주체와 조건까지 연결한다 |
| 중앙 마켓플레이스 | 운영자가 거래를 중개한다 | 발견만 broker, 거래는 peer 직접 |

이 비교는 일반적인 도구 유형에 대한 서술이며, 이 회사의 실제 사내 도구 조사는 아직 하지 않았습니다([proposal-notes.md](proposal-notes.md) 미해결 과제).
