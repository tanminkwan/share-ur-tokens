# 테스트 결과서

> 2026-11-03 기준. 사용자: "test 철저히 하고 coverage 관리도 해. test 결과서도 작성해." 이 문서는 플랫폼 전체 테스트의 현황, 커버리지와 그 기준선, 이번에 더한 테스트, 아직 덜 덮인 곳과 그 이유를 적는다. 단계별 결과(실제 LLM 실행 포함)는 `dev/phaseN/test-results.md`에 있다.

## 1. 한 줄 요약

| 항목 | 값 |
|---|---|
| 실제 LLM 없이 도는 테스트 | **428개 모두 통과**(약 31초) |
| 커버리지(줄 + 분기, 테스트가 띄운 하위 프로세스 포함) | **93.7%**(문장 7,318 가운데 6,962, 분기 2,048 가운데 1,813) |
| 기준선(이보다 낮아지면 실패) | **92%**(`.coveragerc`의 `fail_under`) |
| 실제 LLM 테스트(`tests/live`, 따로 돌림) | 11개. 이번에는 돌리지 않았다(LLM 사용을 줄이기로 한 결정, 마지막 실행 결과는 `dev/phase6/test-results.md`) |

이번 작업으로 커버리지는 **88.0% → 93.0%**가 되었다. 하위 프로세스까지 재도록 설정한 것만으로 89.7%가 되었고, 테스트 30개를 더해 93.0%가 되었다. 그 뒤 SOLID 점검 3번 묶음에서 테스트 4개를 더해 **93.3%**가 되었다(5-1절). 가지 체인 연결 마무리(CP-1·2)에 테스트 6개를 더했고 93.3%를 지켰다(5-2절). 개인 키(6-K)에 테스트 12개를 더해 93.4%가 되었다(5-3절). 원장 밖 content와 작품 등록(CP-4·9·10)에 테스트 8개를 더해 93.5%가 되었다(5-4절). 느린 답을 A2A task로(사람의 속도) 하는 데 테스트 5개를 더해 93.7%가 되었다(5-5절).

## 2. 돌리는 법

```bash
.venv/bin/python -m pytest --ignore=tests/live        # 실제 LLM 없이 도는 테스트 전부(화면 테스트 포함)
scripts/coverage.sh                                     # 같은 테스트 + 커버리지. 92% 아래면 실패, HTML 보고서는 data/coverage-html/
.venv/bin/python -m playwright install chromium         # 화면 테스트용 브라우저(한 번만)
.venv/bin/python -m pytest tests/live                   # 실제 LLM 테스트(.env의 ARENA_LLM_*, 토큰이 든다. 먼저 묻고 돌린다)
```

커버리지 설정은 `.coveragerc`에 있다. 측정 대상은 `arena/` 전체이고 분기까지 센다. 테스트가 띄운 프로세스(제네시스, broker, recorder, 각 peer 실행 명령)의 안쪽도 함께 잰다(`patch = subprocess`, `sigterm = true`).

## 3. 테스트의 종류

| 종류 | 개수 | 무엇을 확인하나 | 어디 |
|---|---|---|---|
| 단위·규칙 | 대부분 | 원장 규칙, 서명, 봉투, 코드표, 일정, 연결 방식, 기본 비서의 각 조각 | `tests/test_*.py` |
| 메모리 안의 세계 | 대부분과 겹침 | broker, recorder, 여러 peer를 한 프로세스 안에 띄워 이벤트 흐름 전체 | `tests/test_assistant.py`의 `eco` 고정물 |
| 경연 모티브 | 6 | 공모·심사 흐름을 기본 요소로 끝까지 | `tests/motif/` |
| **실제 프로세스** | 10 | 제네시스, 두 broker, recorder 재시작, 견본 개인 peer(사람 모드)의 창구 화면, 서비스 peer의 api 묶음과 영수증, 재단 peer의 코드표 판 기록 | `tests/test_processes.py`, `tests/test_runner_processes.py` |
| **화면(Playwright headless Chromium)** | 8 | 창구 화면 5(토큰, 손으로 참가, 물음과 글, 제안 승인·거절, 일정 넣어 이벤트 열기), 대화 화면 3(말하고 답 받기, 물음 카드, 토큰) | `tests/ui/` |
| 규약 시험 벡터 | 2 | 정규 JSON, 서명, 해시, 서명 요청 머리, 원장 항목 해시(판 3의 봉투 포함)를 바이트 단위로 | `tests/test_protocol_vectors.py`, `dev/protocol-vectors.json` |
| 층 구분 | 3 | 플랫폼에 앱의 말이 없음, 아래층(원장·기록자·broker)이 위층을 import하지 않음 | `tests/test_layering.py` |
| 실제 LLM | 11 | 가위바위보 한 판·리그전, 요소를 켠 한 판, 검색 peer와 임베딩 | `tests/live/`(따로) |

## 4. 패키지별 커버리지

| 패키지 | 문장 | 덮음 | 분기 | 덮음 | 커버리지 |
|---|---|---|---|---|---|
| `arena/`(최상위: 설정, 암호, 연결, A2A, REST, LLM, 제네시스 등) | 947 | 912 | 186 | 156 | 94.3% |
| `arena/broker` | 486 | 468 | 94 | 87 | 95.7% |
| `arena/recorder` | 280 | 270 | 40 | 36 | 95.6% |
| `arena/ledger` | 1,193 | 1,146 | 586 | 536 | 94.5% |
| `arena/keys`(개인 키: 보관소, 백업, 이어받기, 명령) | 305 | 287 | 66 | 56 | 92.5% |
| `arena/content`(작품 등록: 참조, 확인, 명령) | 156 | 154 | 32 | 29 | 97.3% |
| `arena/peer`(핵심) | 1,737 | 1,638 | 450 | 394 | 92.9% |
| `arena/peer/assistant`(기본 비서) | 1,105 | 1,030 | 378 | 333 | 91.9% |
| `arena/peer/desk`(소유자 창구) | 125 | 120 | 22 | 17 | 93.2% |
| `arena/peer/elements`(기본 요소의 peer 쪽) | 170 | 155 | 62 | 47 | 87.1% |
| `arena/peers`(실행 명령) | 189 | 179 | 32 | 28 | 93.7% |
| `arena/bundled`(기본 탑재 화면 앱) | 292 | 280 | 30 | 27 | 95.3% |
| `arena/sdk` | 249 | 236 | 56 | 49 | 93.4% |
| **전체** | **7,234** | **6,875** | **2,034** | **1,795** | **93.5%** |

## 5. 이번에 더한 테스트 (30개)

| 파일 | 개수 | 내용 |
|---|---|---|
| `tests/test_assistant_parts.py` | 8 | 기본 비서를 나눈 조각들을 하나씩: 도구 실행 전 검사(없는 도구, 개최자 전용, 참가자 전용, 닫힌 이벤트, 빠진 인자, 깨진 JSON, 아무도 가리키지 않는 필명, 도구가 실패해도 비서는 안 죽음), 운전석 거절과 알림 제목, 서명된 메시지의 서명·시각·머리 확인, broker가 죽었을 때 찾기, 기록자가 죽었을 때 원장 읽기, 원장 새 기록이 누구의 일인지, 공개값이 불완전하거나 다를 때 |
| `tests/test_refusals.py` | 6 | 원장 쪽 거절 하나하나: 일정 칸, 실행 방식 블록, 봉투 본체의 확인, 뿌리 신뢰와 키 이어받기의 깨짐, 가지 기록의 엇갈림, 코드표 판의 모양·앞 판·자체 코드·옮겨 적기(통째가 아님, 낸 이의 서명 없음, 봉인 없음) |
| `tests/test_edges.py` | 6 | 배관의 가장자리: REST 묶음(JSON 아님, 객체 아님, 처리 중 오류, 실제 소켓), A2A(없는 주소, 아무 A2A 손님이 peer와 글로 말하기), 화면 앱의 로컬 웹 열고 닫기, 실행 명령의 조립(재단, 검색), LLM 만들기, Claude 어댑터(가짜 SDK로 JSON 답, 사용량, 거절 재시도, API 오류 끝에 분명한 오류) |
| `tests/test_tool_refusals.py` | 5 | 기본 비서 도구와 요소 창구의 거절: 참가와 계약, 서비스 영수증 위조, 등록과 공개, 공동 확인과 배정, 제출·평가 창구 |
| `tests/test_adapters_and_chat_tools.py` | 4 | SDK 어댑터(함수 앱, HTTP 중계의 그룹·서명 확인과 서비스가 죽었을 때, A2A 에이전트 중계), 대화 비서의 도구 갈래 |
| `tests/test_runner_processes.py` | 1 | 실제 제네시스 위에서 견본 개인 peer(사람 모드), 서비스 peer, 재단 peer를 실제 프로세스로 |

테스트를 쓰다가 고친 것: 검색 peer 실행 명령에 `build()`를 두어 다른 실행 명령처럼 조립을 따로 확인할 수 있게 했다.

## 5-1. SOLID 점검 3번 묶음에서 더한 테스트 (4개)

| 파일 | 개수 | 내용 |
|---|---|---|
| `tests/test_peer_parts.py` | 2 | peer에서 떼어 낸 두 조각: 기록자 증명(`RecorderTrust`)의 거절 하나하나(뿌리도 아니고 뿌리에 이어지지도 않음, 가지의 가지, 부모 체인 증명 실패, 부모의 신뢰 문서가 바뀜, 잇는 기록이 맞지 않음), peer에 닿기(`PeerReach`)가 쓸 수 있는 연결 방식(a2a·api)을 고르고 맞는 것이 없으면 거절 |
| `tests/test_sdk_context.py` | 2 | 앱 문맥: SDK에 적힌 것과 플랫폼 문맥이 주는 것이 정확히 같고 각 항목이 작은 인터페이스 하나에만 속함, 플랫폼 문맥이 모든 작은 인터페이스를 갖추고 기본 탑재 앱 전용 기능은 SDK에 없음 |

이 테스트를 쓰다가 찾은 것: SDK의 `Context`에 플랫폼 문맥이 주는 6개(`operator`, `call_peer`, `profile_of`, `recorder_trust`, `ledger_id`, `submissions`)가 빠져 있었다. 이제 테스트가 둘을 같게 지킨다.

## 5-2. 가지 체인 연결 마무리(CP-1·2)에서 더한 테스트 (6개, `tests/test_branch_link.py`)

| 테스트 | 확인하는 것 |
|---|---|
| 0번 기록이 원래 기록자 키와 갈라진 지점을 밝힘 | 갈라진 지점이 그때 뿌리의 마지막 기록이고, 가지 기록이 같은 지점을 되풀이하며, 뿌리 값 문서에도 적힘 |
| 갈라진 지점이 없거나 틀린 시작은 거절 | 가지 원장이 `parent`의 네 칸과 모양을 확인하고, 뿌리 원장은 자기 기록이 아닌 지점을 거절 |
| 1번 기록 전에는 아무것도 받지 않음 | 연결 전 등록 거절, 1번 기록 뒤에는 받음, 1번 기록은 한 번만, 뿌리 체인에는 1번 기록 없음 |
| 가지 원장이 담는 가지 기록을 확인 | god 서명, 바뀐 본문(해시), 위조 봉인, 다른 체인의 가지 기록, 모양 |
| peer가 양쪽이 한 지점을 말하는지 증명 | 1번 기록이 없음·다른 가지 기록을 담음·서명이 깨짐, 갈라진 지점에서 유효하지 않은 원래 기록자 키, 다른 갈라진 지점 |
| 갈라진 뒤 뿌리 기록자 키가 바뀌어도 맞음 | 0번 기록은 그때의 키, 가지 기록은 새 키로 봉인, 증명 통과 |

실제 두 제네시스 프로세스 테스트(`test_p5g9_a_community_genesis_process_links_into_the_original_chain`)도 갈라진 지점과 1번 기록까지 확인하도록 늘렸다.

## 5-3. 개인 키(6-K)에서 더한 테스트 (12개)

`tests/test_peer_keys.py` 11개와 시험 벡터 1개(`test_key_backup_and_commitment_vectors`)다. 키 보관소(대역 OS 보관소, 0600 파일, auto의 고르기), 백업(암호문만, 틀린 암호문구·바뀐 머리·지나친 scrypt 값 거절), 원장의 키 이어받기(약속한 키로만, 옛 키 거절, 미리 정한 키 peer만 복구, 실적이 신원을 따라감), 키 peer의 거절과 잠김, 소유자 작업(등록·이어받기·복구·되살리기), 명령이 비밀을 찍지 않음을 확인한다. 실제 프로세스 테스트(`tests/test_runner_processes.py`)에 키 peer 프로세스와 `python -m arena.keys register`·`rotate`를 더했다. 결과 표: `dev/phase6/test-results.md` 7절.

테스트는 기기의 실제 OS 키 보관소를 건드리지 않는다(`ARENA_KEY_STORE=file`, 대역 보관소). 이 서버에는 OS 키 보관소가 없어(keyring의 실패 백엔드) 실제 키체인 연동은 macOS·Windows·데스크톱 Linux에서 따로 확인할 일이다.

## 5-4. 원장 밖 content와 작품 등록(CP-4·9·10)에서 더한 테스트 (8개)

`tests/test_content.py` 7개와 시험 벡터 1개(`test_content_form_vector`)다.

| 테스트 | 확인하는 것 |
|---|---|
| content form | BOM, Windows·옛 Mac 줄바꿈, 한글 조합형(NFD)이 `utf8-nfc-lf`에서 같은 hash가 되고 `bytes`는 파일 그대로, UTF-8이 아니거나 모르는 form은 거절 |
| ledger reference | JSON ↔ `arena-ref:` 주소 왕복, colophon 문구, 잘못된 주소 거절 |
| `ref` block | 다른 content hash, 빈 storage, 모르는 storage kind, 너무 긴 위치, 크기·형식, 모르는 proof method, 서명 없음·위조, 모르는 form은 원장이 거절. 공개 확인에 `form`은 보이고 `ref`는 안 보임 |
| `share`의 `ref` | 언제나 봉투에, 공개 본체에 두면 거절 |
| 읽는 쪽의 확인 | 다른 기계의 줄바꿈으로 저장한 사본도 통과, 고친 본문·다른 작가·UTF-8 아닌 사본은 실패, 뿌리 값이 없으면 원장 증명을 건너뛰었다고 말함, 다른 뿌리는 실패. 본문 hash로 찾기, 같은 본문은 한 번만 등록, 조회를 닫은 기록자 |
| 숨긴 위치와 가지 체인 | 위치를 봉투에 넣으면 공개 기록 흐름에 없음, 가지 체인에 등록한 작품은 뿌리의 연결로 증명, 다른 뿌리의 가지는 실패 |
| 명령 | hash, register(DID, 위치, 참조 파일), check(참조 파일, 주소, 뿌리 값 있음·없음), find, 잘못된 위치 인자 |

실제 프로세스 테스트(`tests/test_runner_processes.py`)에 `python -m arena.content register`·`check`·`find`를 더했다. 공개 확인(`GET /entries`)에 봉인한 기록자 키 `sealed_by`를 더해, 그 결과를 고정해 두던 테스트 4개의 기대값을 맞췄다.

## 5-5. 느린 답을 A2A task로 (5개, `tests/test_a2a_tasks.py`, 실제 소켓)

| 테스트 | 확인하는 것 |
|---|---|
| 빠른 답과 느린 답 | 짧으면 message 하나, 길면 task로 알리고 부르는 쪽이 끝까지 따라감, 뒤에서 난 오류도 답으로 옴, `return_immediately` 없이 보내는 바깥 client도 같은 답을 받음 |
| 기다림 한도 | 한도가 지나면 pending과 task id, 그리고 무엇을 기다리는지("waiting for the owner") |
| 남의 A2A agent | task가 `failed`면 그 사유, `input-required`면 needs_input |
| human peer | 상대가 human이면 `ARENA_A2A_HUMAN_WAIT_SEC`로 더 오래 기다리고, 다른 peer는 기본값 |
| 사람에게 묻는 engage | human peer가 desk에서 몇 초 뒤 답하는 동안 부르는 쪽은 task를 따라가고, 답이 오면 계약 서명을 받음 |

## 6. 아직 덜 덮인 곳과 그 이유

| 모듈 | 커버리지 | 덜 덮인 곳 | 이유와 다음 |
|---|---|---|---|
| `arena/a2a.py` | 86.2% | 스트리밍, 일부 연결 오류 | 느린 답의 task와 남의 agent의 task 상태는 5-5절에서 실제 소켓으로 확인한다. 스트리밍은 쓰지 않는다(agent card가 `streaming: false`) |
| `arena/peers/app_store.py`, `search.py` | 77~80% | `main()`의 실행 루프 | 조립(`build`)은 테스트한다. 끝없이 도는 루프는 실제 프로세스 테스트로만 닿는다 |
| `arena/sdk/packaging.py` | 80.6% | 꾸러미 검사의 일부 거절(크기, 목록표 모양) | 다음 보강 대상 |
| `arena/peer/app_install.py` | 80.8% | 배포 peer가 꾸러미 대신 주소를 줄 때, 내려받기 실패 | 다음 보강 대상 |
| `arena/peer/assistant/core.py` | 83.4% | 감시 루프(시작 뒤 도는 부분), 일부 메시지 거절 | 루프는 시간에 기대므로 단위 테스트보다 실제 프로세스나 짧은 대기로 확인한다 |
| `arena/peer/elements/evaluation.py` | 84.5% | 평가 창구의 일부 거절 | 다음 보강 대상 |

## 7. 커버리지 관리 정책

- **기준선**: 전체 커버리지가 `.coveragerc`의 `fail_under`(지금 92%)보다 낮으면 `scripts/coverage.sh`가 실패한다. 테스트를 더해 올라가면 기준선도 따라 올린다(내리지 않는다).
- **새 코드에는 테스트를 함께**: 새 기능은 요구사항 번호를 이름에 단 테스트와 함께 들어온다(`test_p6x..._`). 거절과 실패 갈래도 테스트한다. "거절이 테스트에서 한 번도 돌지 않으면 그 거절이 동작하는지 아무도 모른다."
- **실제 LLM 테스트는 최소로**: 플랫폼 보장은 실제 LLM 없이 확인한다(정해진 답을 내는 대역). 실제 LLM은 꼭 필요할 때 peer 최소 구성으로 한 번, 묶음 실행은 먼저 묻는다.
- **결과서 갱신**: 단계가 끝나거나 큰 변경 뒤에 이 문서의 1·4·6절을 다시 잰 값으로 고친다.
