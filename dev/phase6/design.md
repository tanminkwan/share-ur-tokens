# 6단계 설계: 여러 이벤트에 공통인 요소의 기본 탑재

요구사항: [requirements.md](requirements.md). 구현 순서는 6-0 → 6-A → 6-B → 6-C → 6-D → 6-V → 6-E이고, 요소마다 테스트를 먼저 쓴다.

## 0. 층 나눔

요소 하나는 원장 쪽(무엇을 받을지)과 peer 쪽(무엇을 할지)에 걸친다. 원장 코드가 peer 코드를 알면 안 되므로(지금 구조와 같은 방향), 같은 이름으로 두 곳에 나눠 등록한다.

```mermaid
flowchart TB
    subgraph L["arena/ledger/elements.py (원장 쪽)"]
        LE["LedgerElement<br/>name, check_config(cfg), rules(chain, entry, cfg)"]
    end
    subgraph P["arena/peer/elements/ (peer 쪽)"]
        PE["PeerElement<br/>name, app(설정) → 내장 앱(op), tools(기본 비서 도구)"]
    end
    D["이벤트 선언 elements 블록<br/>{이름: 설정}"] --> LE
    D --> PE
    LE --> R["기록자: 그 이벤트를 가리키는 항목에<br/>선언된 요소의 규칙을 더해 검사"]
    PE --> A["peer: 내장 앱이 op를 받고,<br/>기본 비서는 그 이벤트가 켠 요소의 도구만 봄"]
```

- 요소를 더할 때 원장(`rules.check`), 기록자, 이벤트 배정기, 기본 비서를 고치지 않는다. 등록만 한다(`register_ledger_element`, `register_peer_element`).
- 요소의 확인은 모두 코드다. 기본 비서는 도구를 고르고 인자를 채울 뿐이다.
- 요소의 내장 앱은 **이벤트를 다루는 앱(`EventHandler`)이 있는 peer에만** 조립된다. god·기록자·검색 peer처럼 이벤트에 참여하지 않는 peer에는 들어가지 않는다(god은 쓰기·내용 op가 없어야 함).
- 요소의 op 이름에는 요소 이름을 붙인다(`intake.submit`, `evaluation.request`). 앱의 op와 겹치지 않는다.
- 평가 요소의 이름은 `evaluation`이다(원장의 `evaluator` 칸과 맞춤). 플랫폼에는 특정 앱의 말(공모, 심사, 채택 등)을 넣지 않는다는 층 규칙(`tests/test_layering.py`)을 지킨다.
- 제출 받기에서는 받는 peer의 `IntakeDesk`가 제출자 서명이 든 `share`에 자기 서명을 더해 **직접 원장에 기록**하고, 원장이 받은 뒤에만 보관한다(받았다는 기록과 원장이 어긋나지 않게).

## 1. 6-0 요소 블록

**선언과 공지**: 이벤트 선언 payload와 공지에 `elements: {이름: 설정}`을 더한다(없으면 `{}`). `announce_event(..., elements=None)`.

**원장**:
- `event` 항목의 모양 검사에 더한다: `elements`는 객체, 이름은 등록된 요소, 설정은 그 요소의 `check_config`를 통과.
- 공통 규칙 뒤에 `r_elements`를 더한다: 항목이 이벤트를 가리키면(`event_id`), 그 이벤트 선언의 요소마다 `rules(chain, entry, cfg)`를 차례로 본다.
- 이벤트 공개 정보에 `elements`를 싣는다.

**이벤트 배정기**: 지금 규칙 해시·실행 방식·앱 목록을 원장과 대조하는 자리에서 `elements`도 같아야 받는다.

**기본 비서**: 이벤트 상태에 `elements`를 둔다(저장됨). `Tool`에 `element: str | None`을 더하고, `_tools_for`는 그 이벤트가 켠 요소의 도구만 보여 준다. 요소 도구는 요소를 등록할 때 기본 비서에 더한다.

## 2. 6-A API를 제공하는 peer 틀

### 2.1 서비스 설명 파일 (JSON)

```json
{
  "name": "rps-referee", "version": "1.0", "app_id": "<고정 UUID>",
  "description": "두 공개값으로 가위바위보 승패를 계산하고 원장에 기록한다",
  "offers": ["판정"], "allow_groups": ["public"], "require_signed": false,
  "base_url": "http://localhost:9000", "headers_env": {"Authorization": "REFEREE_TOKEN"},
  "ops": {
    "judge": {"python": "my_pkg.referee:judge", "description": "...", "record": {"kind": "match"}},
    "lookup": {"http": {"method": "GET", "path": "/items/{id}"}, "description": "..."}
  }
}
```

- `python` op: `async def fn(input: dict, ctx) -> dict`. `http` op: 지금의 `HttpServiceAdapter` 중계를 그대로 쓴다. 헤더의 비밀값은 파일에 넣지 않고 환경 변수 이름만 적는다.
- `ServiceApp`(`arena/peer/service.py`)이 파일을 읽어 op를 만든다. `HttpServiceAdapter`는 이 앱의 `http` op 구현으로 옮긴다(SDK 공개 이름은 유지).
- 단독 실행: `python -m arena.peers.service --spec <파일>`(포트 등은 `ARENA_SERVICE_PEER_*`).

### 2.2 결과 서명 (P6-A2)

모든 답에 영수증을 붙인다.

```text
receipt = {service: 서비스 공개키, op, request_hash: SHA-256(정규JSON(요청에서 서명 칸을 뺀 것)),
           result_hash: SHA-256(정규JSON(result)), ts}
reply   = {ok, result, receipt, receipt_sig: 서명(receipt)}
```

`arena.sdk.verify_service_receipt(reply, request, expected_pub)`가 묻는 쪽에서 확인한다.

### 2.3 원장에 결과 남기기 (P6-A3)

op 설정에 `record: {kind}`가 있으면, 호출에 `event_id`, `subject`가 함께 오고:

1. 서비스 peer가 그 이벤트의 기록자를 뿌리 신뢰로 확인한다(`ctx.recorder_trust`).
2. 함수가 결과를 계산한다.
3. 서비스 peer가 혼자 당사자인 공동 확인 `{kind, subject, value: {input_hash, result}}`을 기록한다. 원장은 정책의 `attest_roles`로 그 종류를 맡은 역할인지, 배정된 종류면 배정된 당사자인지 확인한다(지금 규칙). 그래서 이벤트는 판정 peer와 역할 계약을 맺고 `attest_roles: {match: "referee"}`처럼 맡긴다.
4. 답에 그 항목의 해시를 싣는다.

### 2.4 찾기 (P6-A4)

- 프로필의 `offers`에 `service:<name>`과 설명 파일의 `offers`를, `service` 칸에 op 목록과 설명을 싣는다(지금 `profile_extra`를 넓힘).
- 앱 설치기: `ARENA_APP_STORE_URLS`가 비어 있고 `ARENA_APP_STORE_DISCOVER`가 켜져 있으면, broker에서 역할 `앱 배포`를 가진 peer를 찾아 차례로 묻는다.

### 2.5 기본 비서 도구 (P6-A5)

`call_service {peer, op, input_json, event_subject?}`: 코드가 필명을 주소로 바꾸고, 보내고, 영수증 서명과 요청·결과 해시를 확인해 이벤트 상태에 보관한다. 결과만 LLM에 보여 준다.

### 2.6 연결 방식 (P6-A6 ~ A8)

```mermaid
flowchart LR
    C["부르는 peer의 코드"] --> P["상대 프로필 connections"]
    P -->|"a2a가 있으면"| A["A2A 1.0 JSON-RPC<br/>(에이전트 카드)"]
    P -->|"api만 있으면"| R["POST {주소}/ops/{op}<br/>{input} → {ok, result, receipt}"]
    P -->|"human"| H["자동으로 쓰지 않음<br/>소유자에게 연락처만 알림"]
```

- **등록부**(`arena/peer/connections.py`): `ConnectionKind(name, label, fields, automatic)`. 처음 등록: `human`(칸 `contact`, 자동 아님), `a2a`(칸 `url`), `api`(칸 `url`, 선택 `ops`). broker와 peer가 같은 등록부로 검사한다.
- **프로필**: `connections: [{kind, url | contact, ...}]`. `url`(지금 칸)은 A2A 호환을 위해 남긴다. 에이전트 peer는 `PeerConfig.connections`가 비면 `[{kind: a2a, url}]`. 사람 연락처는 설정 `ARENA_PEER_HUMAN_CONTACT`가 있을 때만.
- **`api` 묶음**(`arena/rest.py`): 서버 `build_rest_app(handler)`는 `POST /ops/{op}`를 받아 `{op, **body}`를 peer의 메시지 처리기(`Peer.handle`)에 머리와 함께 넘긴다. 즉 같은 op가 두 방식으로 열린다. 클라이언트 `RestTransport.call(url, msg, meta)`.
- **고르기**: `Peer.call_peer(pub, msg, group, event)`가 broker 프로필의 연결 정보를 읽어 `a2a` → `api` 순으로 쓴다. `call_service` 도구가 이것을 쓴다.
- **API 전용 peer**: 서비스 peer 실행기 `--connections api`(또는 `ARENA_SERVICE_PEER_CONNECTIONS`)면 A2A 서버 없이 REST만 열고 프로필 연결 정보도 `api`만 싣는다. 신원 키와 서명된 프로필, 서명 영수증은 그대로다.

## 3. 6-B 제출 받기 (`intake`)

**설정**: `{"deadline": 유닉스 초, "max_per_author": 1, "receiver": "issuer" 또는 역할 이름, "audience": [라벨...]}`.

**원장**: `share` 항목에 선택 칸 `event_id`를 더한다(이벤트 참조 선택). `intake`를 켠 이벤트에서 `purpose: "submission"`인 `share`는:
- 받는 사람(`consumer`)이 설정의 받는 사람(개최자 또는 그 역할 계약자)이고,
- 기록 시각이 마감 전이고,
- 같은 작성자(`provider`)의 제출 수가 상한 안이고,
- 작성자가 겸할 수 없는 역할이 아니어야 한다(지금의 `conflict_roles` 확인을 `share`에도).

**peer**:

```mermaid
sequenceDiagram
    participant A as 참가자(기본 비서 submit 도구)
    participant R as recorder
    participant H as 받는 사람의 내장 앱 IntakeDesk
    A->>R: publish {content_hash, event_id}
    A->>H: op submit {event_id, content, publish 항목 해시, share payload, 작성자 서명}
    H->>H: 코드 확인: 내용 해시, 서명, 받는 사람, 마감, 상한, 겸직, 응모 대상
    H-->>A: 받은 쪽 서명(share)
    A->>R: share (두 사람 서명) → 영수증 보관
    H->>H: 제출 보관(재시작 뒤 이어 감)
```

- `IntakeDesk`는 내장 앱(고정 app_id, op `submit`)이다. 보관은 앱 전용 저장소.
- 개최자 쪽 목록은 `AppContext.submissions(event_id)`로 연다(필명, 내용 해시, 받은 시각). 기본 비서 도구 `submissions`는 이것을 보여 준다.

## 4. 6-C 평가 요청과 판정 기록 (`evaluation`)

**설정**: `{"evaluator_role": "evaluator", "verdict": "review", "per_item": 1}`. 판정 권한은 정책의 `verdict_roles`(지금 있음).

**원장**: `feedback`에 공개 정보(평가자, 내용 해시, 판정, 점수)를 더한다. `evaluation`을 켠 이벤트에서 판정 종류가 설정의 `verdict`인 `feedback`은 평가자가 그 내용을 넘겨받은 기록(`share`, `purpose: "evaluation"`)이 있어야 한다(지금의 "받은 적 없는 내용" 규칙을 이벤트 범위로).

**peer**:
- 개최자 도구 `request_evaluation {evaluator}`: 넘김 `share` payload를 만들어 평가자의 op `evaluation.request`로 보낸다.
- 평가자 쪽 내장 앱 `EvaluationDesk`가 받아 `EvaluationProvider` 능력(`evaluate(ctx, items, request) -> [{content_hash, score, comment}]`)을 가진 앱에 넘긴다. 없으면 기본 비서가 규칙 글을 보고 판정한다. 판정 payload와 서명, 넘김 영수증은 코드가 만든다.
- 개최자가 넘김과 판정을 원장에 기록한다. 도구 `verdicts`는 항목별 판정을 보여 준다. **무엇을 채택할지는 정하지 않는다.**

## 5. 6-D 봉인 묶음 (`sealed`)

**설정**: 빈 객체(`{}`). 켜면 배정된 모든 주제의 라벨이 봉인된다(구현하며 `kinds`를 뺐다: 주제 단위로 충분했다).

**라벨 규약**: 배정된 주제 `S`의 봉인 라벨은 `S` 또는 `S-<숫자>`. 라벨에서 주제 찾기: 라벨이 배정 주제와 같으면 그 주제, 아니면 마지막 `-<숫자>`를 뗀 것이 배정 주제면 그 주제.

**원장 규칙**(그 이벤트를 가리키는 항목에):
- `reveal`(라벨 `L`, 주제 `S`): `S`에 배정된 당사자 전원에게 라벨 `L`의 `publish`가 있어야 한다.
- `publish`(라벨 `L`, 주제 `S`): `S`에 배정된 당사자만 등록하고, 라벨 `L`의 `reveal`이 이미 있으면 받지 않는다.
- `reveal`(어느 배정 주제에도 속하지 않는 라벨): 받지 않는다. 등록은 받는다(값은 봉인된 채 남는다). 요소를 켠 실제 실행 1에서 배정 전에 한 선수가 m1을 등록하고 공개했고, 배정 뒤 m1은 이미 열려 상대가 등록하지 못해 판이 멈췄다(`dev/phase6/evidence/rps-minielem1.log`).

**기본 비서**: 지금 상태에 "봉인 m1-2: 등록 2/2, 공개 가능" 같은 줄을 코드가 진행 현황에서 만들어 넣는다.

## 6. 6-V 검증

### 6.1 LLM 사용량 (P6-V1)

- LLM 어댑터의 `ask_json`에 선택 인자 `on_usage(usage: dict)`를 더한다. OpenAI 호환 응답의 `usage`(prompt, completion 토큰), Claude 응답의 `usage`를 넘긴다. 없으면 호출 수만.
- `UsageMeter`가 peer(필명)별로 호출 수와 토큰을 센다. `ask_json(llm, log, actor, ...)` 도우미가 미터에 넘긴다. 미터는 peer에 주입하고(테스트·실행기에서 만들어 넣음), 실행 끝에 표로 낸다.

### 6.2 경연 모티브를 요소로 (P6-V2)

`tests/motif/`의 대역 앱 `Inbox`, `Judge`를 `IntakeDesk`, `ReviewDesk` + `EvaluationProvider` 대역으로 바꾼다. 흐름 함수(`tests/motif/flow.py`)는 요소를 켠 이벤트를 선언하고 요소의 op를 쓴다. 기존 테스트가 그대로 통과해야 한다.

### 6.3 있을 때와 없을 때 비교 (P6-V3)

`scripts/compare_elements.py`: 같은 이벤트를 두 가지로 N번씩 돌린다(5단계의 반복 안정성 도구와 같은 틀).

| 대상 | 요소 없이 | 요소를 켜고 |
|---|---|---|
| 아이디어 공모 모티브 | 자연어 규칙만 | `intake` + `evaluation` |
| 가위바위보 | 자연어 규칙만(5단계 mini, 리그전) | `sealed` + 판정 API peer(`attest_roles`로 결과를 맡김) |

잴 것: 플랫폼 보장(원장 감사), 끝까지 간 비율, 걸린 시간, peer별 LLM 호출 수와 토큰.

## 7. 6-E (뒤에)

게시판 구독, 추천 peer 틀, 판단 근거 틀은 6-A~D와 6-V가 끝난 뒤 따로 설계한다. 6-V의 측정에서 LLM 판단이 많이 쓰이는 자리가 보이면 그 순서를 정하는 근거로 쓴다.

## 8. 바뀌는 규약 (규약 판 2)

`dev/protocol.md`에 더한다: 이벤트 선언·공지의 `elements` 블록, `share`의 `event_id`, `feedback` 공개 정보, 요소별 원장 규칙(제출, 판정, 봉인), 서비스 결과 영수증 모양, 내장 op `intake.submit`·`evaluation.request`.

## 9. 6-P 견본 개인 peer: 소유자 창구, 운전석, 소유자 API, 화면

### 9.1 층 나눔

```mermaid
flowchart TB
    UI["화면 (브라우저, 바닐라 JS 모듈)<br/>ApiClient · Store · 조각들 · 조립"] -->|"HTTP + 토큰"| API["소유자 API (Starlette)<br/>HTTP만 맡음"]
    API --> SVC["OwnerService<br/>(무엇을 할 수 있나: 상태, 답하기, 도구 실행, 이벤트 열기)"]
    SVC --> DESK["OwnerDesk<br/>(알림 거리와 답)"]
    SVC --> ASST["EventAssistant<br/>(운전석: 자동·제안·수동)"]
    ASST -->|"Owner + Notifier"| DO["DeskOwner<br/>(물음·글·제안·알림을 창구로)"]
    DO --> DESK
    ASST --> TOOLS["같은 도구<br/>(원장 규칙·서명은 코드)"]
```

| 부분 | 맡는 일(하나씩) | 위치 |
|---|---|---|
| `DeskItem` | 알림 거리 하나: `id, kind, event_id, title, body, fields?, status(open·done), answer, created` | `arena/peer/desk/model.py` |
| `OwnerDesk` | 알림 거리를 쌓고, 답을 받고, 답을 기다리는 쪽에 돌려준다. 재시작해도 남게 저장(`OwnerDeskApp`의 앱 상태) | `arena/peer/desk/desk.py` |
| `DeskOwner` | 플랫폼의 `Owner`(묻기·글 받기)와 `Notifier`(알리기·제안 승인받기)를 창구로 잇는 어댑터. 답이 정해진 시간 안에 없으면 "아니오" | `arena/peer/desk/owner.py` |
| 운전석 | 기본 비서의 이벤트 상태 `drive`: `auto`·`suggest`·`manual`. 제안이면 실행 전에 `Notifier.suggest`, 수동이면 LLM을 부르지 않고 입력을 알림으로 넘긴다 | `arena/peer/assistant/core.py` |
| `OwnerService` | 화면이 쓰는 일의 목록(응용 층). HTTP를 모른다 | `arena/peer/desk/service.py` |
| 소유자 API | HTTP 경로와 토큰 확인만. `OwnerService`에 기댄다 | `arena/peer/desk/api.py` |
| 화면 | 정적 파일. `ApiClient`(통신만), `Store`(상태와 구독), 조각(`ItemsView`, `EventsView`, `EventView`, `ToolForm`, `HostForm`), 알림 종류별 카드 등록표, `app.js`(조립) | `arena/peer/desk/static/` |

SOLID: 조각은 `Store`와 `ApiClient`를 생성자로 받는다(의존 뒤집기). 알림 종류를 더할 때는 카드 등록표에 하나를 더한다(열고 닫기). `ToolForm`은 도구의 인자 스키마로 입력칸을 만들어, 도구가 늘어도 화면 코드를 고치지 않는다.

### 9.2 운전석

| 입력이 오면 | 자동 | 제안 | 수동 |
|---|---|---|---|
| 새 공지, 일정 시각, 내 예약 | 창구에 알림 + LLM 차례 | 같음 | 창구에 알림만 |
| 메시지, 원장 새 기록, 서명 요청 | LLM 차례 | LLM 차례 | 창구에 알림만 |
| LLM이 도구를 고르면 | 실행 | 창구에 제안 → 승인하면 실행, 거절하면 이번 차례를 멈춤(읽기만 하는 도구는 바로 실행) | (LLM 없음) |
| 사람이 화면에서 도구를 고르면 | 실행 | 실행 | 실행 |

LLM이 없는 peer(`NoLLM`)는 언제나 수동이다. 사람이 화면에서 실행한 도구도 LLM이 고른 도구와 같은 코드(`_run_tool`)를 지나므로, 필명 되돌리기, 공개값 코드 운반, 원장이 거절할 일 미리 거절이 똑같이 선다.

### 9.3 소유자 API (판 0)

모든 경로는 `Authorization: Bearer <토큰>`이 있어야 한다(없거나 틀리면 401). 토큰은 설정(`ARENA_PERSONAL_DESK_TOKEN`)이나, 비면 홈 폴더에 만든 무작위 값이다. 기본으로 127.0.0.1에만 연다.

| 경로 | 하는 일 |
|---|---|
| `GET /api/state` | 나(필명, 공개키, `operator`, LLM 유무), 이벤트 목록(제목, 역할, 운전석, 닫힘), 열린 알림 수 |
| `GET /api/items?status=open\|all` | 알림 거리 목록 |
| `POST /api/items/{id}/answer` | 답하기: 물음 `{yes, why}`, 글 `{fields}`, 제안 `{approve}`, 그 밖 `{}`(읽음) |
| `GET /api/events/{id}` | 이벤트 하나: 규칙, 지금 상태 줄(코드가 만든 것), 최근 기록, 쓸 수 있는 도구와 인자 스키마, 일정과 예약 |
| `POST /api/events/{id}/drive` | `{drive}`: 운전석 바꾸기(LLM이 없으면 `manual`만) |
| `POST /api/events/{id}/tools/{name}` | `{args}`: 사람이 도구 실행. 답은 도구의 결과 그대로 |
| `POST /api/events` | 이벤트 열기 `{title, kind, rules, policy, instruction?, schedule?, elements?}` |

### 9.4 화면 테스트

`tests/ui/`: 메모리 안의 broker·recorder·peer 세계에 견본 peer의 소유자 API를 실제 포트로 띄우고, Playwright(비동기, headless Chromium)로 화면을 연다. LLM은 정해진 답을 내는 테스트용 대역이다. 브라우저가 설치되어 있지 않으면 건너뛴다.

## 9-1. 6-K 개인 키: 스스로 만들고, 미리 약속하고, 맡긴다

**원칙**: 키는 언제나 peer가 자기 기기의 보안 영역에서 스스로 만든다. 누구도(키 peer도) 남의 비밀키를 만들거나 보지 않는다. 플랫폼이 정하는 것은 키를 두는 곳의 인터페이스, 백업의 모양, 원장의 키 이어받기 규칙이다. 백업을 맡고 복구에 서명하는 일은 특수 목적 peer인 키 peer가 맡는다(선택).

```mermaid
flowchart LR
    subgraph D["소유자의 기기"]
        P["peer 프로그램"] --> S["KeyStore<br/>OS 키 보관소 또는 0600 파일"]
        P --> B["암호화한 백업<br/>(지금 키 + 다음 키)"]
    end
    P -- "key_commit: 다음 키의 해시, 복구 담당" --> L["원장"]
    B -- "암호문만" --> K["키 peer"]
    K -. "복구 서명(미리 정해진 경우만)" .-> L
```

**왜 다음 키를 미리 약속하나**: 옛 키와 새 키의 서명만으로 이어받게 하면, 지금 키를 훔친 사람이 먼저 자기 키로 옮겨 신원을 가져간다. 다음 키를 해시로 미리 원장에 적어 두고 그 키는 기기에 두지 않으면(암호화한 백업에만 둔다), 지금 키만 가진 도둑은 이어받기를 할 수 없다. 소유자가 백업으로 먼저 옮기면 원장은 그 뒤 도둑이 가진 옛 키의 서명을 받지 않는다.

```mermaid
sequenceDiagram
    participant O as 소유자의 peer
    participant K as 키 peer
    participant R as 기록자(원장)
    O->>O: 다음 키를 스스로 만든다
    O->>R: key_commit {pub, next: 다음 키의 해시, recovery: [키 peer]}
    O->>K: key.backup.put {백업(암호문), 복구 비밀} (그 키로 서명)
    Note over O: 키를 도난당함
    O->>K: key.backup.get {pub, 복구 비밀}
    K-->>O: 백업(암호문)
    O->>O: 암호문구로 열기: 다음 키, 그다음 키를 새로 만든다
    O->>R: peer_rotate {old, new, next, by: next} (새 키가 서명)
    Note over R: 옛 키의 서명은 이제 받지 않는다
```

**복구(기기와 암호문구를 모두 잃음)**: 새 기기에서 새 키와 그다음 키를 만들고, 키 peer에 `key.recover {payload, 복구 비밀}`을 보낸다. 키 peer는 자기 방식으로 본인을 확인하고(견본: 복구 비밀) payload에 서명한다. 소유자가 새 키로도 서명해 `peer_rotate {by: recovery, recoverer}`를 기록한다. 원장은 그 키 peer가 그 신원의 `recovery` 목록에 있는지 본다. 미리 정해 두지 않은 신원은 복구할 수 없다(키 분실은 개인 책임).

| 조각 | 한 가지 일 | 원본 |
|---|---|---|
| `KeyStore`(`FileKeyStore`, `OsKeyStore`, `AutoKeyStore`) | 키를 두고 꺼낸다 | `arena/keys/store.py` |
| `seal_backup` / `open_backup` | 백업을 잠그고 연다 | `arena/keys/backup.py` |
| `commit_entry`, `rotate_entry`, `recovery_entry` | 원장에 쓸 키 기록을 만든다 | `arena/keys/lineage.py` |
| 원장 규칙 `key_commit`, `peer_rotate`, 물러난 키 거절 | 이어받기가 맞는지 본다 | `arena/ledger/peer_keys.py`, `arena/ledger/rules.py` |
| `KeyFlows` | 소유자의 작업(등록, 이어받기, 복구, 되살리기). 기록자와 키 peer를 주입받는다 | `arena/keys/flows.py` |
| `KeyRole` | 키 peer의 일(백업 보관, 복구 서명) | `arena/peer/key_role.py` |
| 명령 | `python -m arena.keys` | `arena/keys/cli.py` |

견본 개인 peer의 홈은 `PeerHome.key_store()`로 키를 둔다. god, broker, 기록자 같은 플랫폼 시설의 키는 지금처럼 파일이다(서버에서 돈다).

## 9-2. 6-N 원장 없는 broker 그룹

```mermaid
flowchart TB
    F["founder (그룹 주인 또는 열린 그룹의 founder)"] -->|"python -m arena.groups declare"| BA["broker A: 선언 보관<br/>(founder 서명, ver, ledger: null)"]
    BA -->|"이웃에 나눔"| BB["broker B"]
    P["peer: ctx.group_mode(그룹)"] -->|"GET /group, 서명 확인"| BB
    P --> M{"ledger?"}
    M -->|"없음"| NL["공지만: event_hash 없음<br/>요소·코드표 거절<br/>원장 도구 빼기, close_notice로 끝"]
    M -->|"있음"| L["원장 선언과 대조(지금과 같음)"]
    F -->|"python -m arena.groups attach"| R["recorder: group 항목 기록"]
    R --> BA2["broker: ver + 1, ledger = {ledger_id, recorder_url, recorder, entry}"]
```

| 부분 | 파일 | 하는 일 |
|---|---|---|
| 선언의 모양 | `arena/groups/decl.py` | 모양 검사, 다음 판 규칙(같은 founder, 더 큰 ver, 붙은 원장은 그대로), 원장으로 옮길 `group` 항목. broker와 peer 아래층이라 둘 다 쓴다 |
| broker | `arena/broker/service.py` `declare`·`group`, `POST /group`·`GET /group` | founder(닫힌 그룹: 주인, 열린 그룹: `ARENA_BROKER_FOUNDER_PUB`) 서명, `closed`, 자기 키 확인, 보관과 이웃에 나눔. 만민 그룹은 받지 않음 |
| peer가 보는 그룹 | `arena/peer/groups.py` `GroupModes` | 선언을 읽고 서명 확인, 붙은 원장 증명(기록자 뿌리 신뢰, `ledger_id`, founder의 `group` 항목). 선언이 없거나 틀리면 원장 그룹(더 엄한 쪽). `ARENA_GROUP_MODE_TTL_SEC` 동안 기억 |
| 개최 | `arena/peer/events.py` `announce_event` | 원장 없으면 공지만. 붙은 원장이 증명되면 그 원장에 선언 |
| 배정 | `EventRouter._checked` | 원장 선언 없는 공지는 원장 없는 그룹에서만, 요소·코드표 없이. 증명된 그룹 원장이 있으면 그 원장의 선언만 |
| 기본 비서 | `Tool.ledger`, `Toolbox`, `EventState.on_ledger`, `close_notice` | 원장 도구(계약, 등록·공개, 확인, 진행 현황, 공동 확인, 배정, 닫기, 공동 서명)는 원장 없는 이벤트에서 목록에서 빠지고 손으로 불러도 거절. `call_service`의 `subject` 거절. 프롬프트에 "원장 없음" |
| founder 절차 | `arena/groups/flows.py`, `cli.py` | `show`, `declare`, `attach`(group 항목 기록 → 다음 판 선언) |

원장을 붙인 뒤에도 이미 받은 원장 없는 이벤트는 그대로 진행한다(배정기는 아는 이벤트의 수정·마감을 계속 넘긴다). 새 공지는 원장 선언이 있어야 한다.

## 10. 설정 (모두 `.env`)

| 키 | 뜻 |
|---|---|
| `ARENA_SERVICE_PEER_PORT` 등 | 서비스 peer 실행 |
| `ARENA_APP_STORE_DISCOVER` | 앱 배포 peer를 broker에서 찾을지 |
| `ARENA_INTAKE_MAX_CONTENT_BYTES` | 제출 내용 크기 상한 |
| `ARENA_EVALUATION_MAX_ITEMS` | 한 번에 넘기는 평가 항목 수 상한 |
| `ARENA_KEY_STORE`, `ARENA_KEY_STORE_SERVICE` | 키를 두는 곳(auto, os, file), OS 키 보관소의 서비스 이름 |
| `ARENA_KEY_BACKUP_SCRYPT_N`·`_R`·`_P`, `ARENA_KEY_BACKUP_SCRYPT_N_MAX`, `ARENA_KEY_BACKUP_MIN_PASSPHRASE` | 백업 암호화의 세기, 열 때 받는 상한, 암호문구 최소 길이 |
| `ARENA_KEY_RECOVERY_MAX` | 복구 담당으로 정할 수 있는 키 peer 수 |
| `ARENA_KEY_PEER_*` | 키 peer 실행, 틀린 복구 비밀 허용 횟수, 복구 비밀 최소 길이 |
