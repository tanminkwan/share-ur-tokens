# 테스트 결과서

> 2026-11-05 기준(8단계 뿌리 키 세리머니, 가지 그룹 창설 경로 2차까지, 요약 표와 3절만 갱신. 패키지별 표는 2026-11-04 값). 사용자: "test 철저히 하고 coverage 관리도 해. test 결과서도 작성해." 이 문서는 플랫폼 전체 테스트의 현황, 커버리지와 그 기준선, 이번에 더한 테스트, 아직 덜 덮인 곳과 그 이유를 적는다. 단계별 결과(실제 LLM 실행 포함)는 `dev/phaseN/test-results.md`에 있다.

## 1. 한 줄 요약

| 항목 | 값 |
|---|---|
| 실제 LLM 없이 도는 테스트 | **570개**: 569개 통과, 1개(실제 docker 실행, `ARENA_TEST_DOCKER=1`일 때만)는 건너뜀(약 70초) |
| 커버리지(줄 + 분기, 테스트가 띄운 하위 프로세스 포함) | **94.4%**(문장 9,465 가운데 9,070, 분기 2,742 가운데 2,477) |
| 기준선(이보다 낮아지면 실패) | **92%**(`.coveragerc`의 `fail_under`) |
| 실제 LLM 테스트(`tests/live`, 따로 돌림) | 11개. 이번에는 돌리지 않았다(LLM 사용을 줄이기로 한 결정, 마지막 실행 결과는 `dev/phase6/test-results.md`) |

이번 작업으로 커버리지는 **88.0% → 93.0%**가 되었다. 하위 프로세스까지 재도록 설정한 것만으로 89.7%가 되었고, 테스트 30개를 더해 93.0%가 되었다. 그 뒤 SOLID 점검 3번 묶음에서 테스트 4개를 더해 **93.3%**가 되었다(5-1절). 가지 체인 연결 마무리(CP-1·2)에 테스트 6개를 더했고 93.3%를 지켰다(5-2절). 개인 키(6-K)에 테스트 12개를 더해 93.4%가 되었다(5-3절). 원장 밖 content와 작품 등록(CP-4·9·10)에 테스트 8개를 더해 93.5%가 되었다(5-4절). 느린 답을 A2A task로(사람의 속도) 하는 데 테스트 5개를 더해 93.7%가 되었다(5-5절). task 보관과 pending 다시 보기에 테스트 6개를 더해 94.2%가 되었다(5-6절). 원장 크기 상한과 link peer에 테스트 8개를 더했고 94.2%를 지켰다(5-7절). 여러 link peer, broker 재연결, docker 배치에 테스트 7개를 더해 94.4%가 되었다(5-8절). 무전기 방식 a2a(webhook, SSE)와 통합 창(console)에 테스트 15개를 더했고 94.4%를 지켰다(5-9절). 결재를 공동 서명(endorse)으로 바꾸는 데 테스트 7개를 더하고 결재 전용 테스트를 고쳐 쓰며 94.4%를 지켰다(5-10절). 원장 없는 broker 그룹(6-N)에 테스트 11개를 더해 94.5%가 되었다(5-11절). 그룹 생성권 모의 실험(`sim/`, 커버리지 대상 밖)에 14개, 스핑크스 peer에 10개를 더해 94.6%가 되었다(5-12절). 모든 창의 한 가지 모양(arena-ui)과 peer 종류별 바탕에 7개를 더했고 94.6%를 지켰다(5-13절).

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
| **뿌리 키 세리머니** | 25 | 형식과 서명 확인, 첫 기록자 키가 어떤 파일에도 없음, 틀린 서명·시간 초과·증인 부족, 폐기 선언의 확인, 키 교체, 관찰자 키, 실제 프로세스 리허설(뿌리, 가지) | `tests/test_ceremony_*.py`, `dev/phase8/test-results.md` |
| **가지 그룹 창설 경로** | 19 | 위임·철회, `chain_link`의 증명서와 god 승인, 대리인의 키 이어받기, foundation 기준과 스핑크스의 집행, 세리머니의 위임과 가지 허락, 실제 프로세스로 처음부터 끝까지 | `tests/test_delegation.py`, `test_founding_policy.py`, `test_ceremony_delegation.py`, `test_founding_process.py`, `dev/founding/test-results.md` |
| 규약 시험 벡터 | 3 | 정규 JSON, 서명, 해시, 서명 요청 머리, 원장 항목 해시(판 3의 봉투 포함)를 바이트 단위로 | `tests/test_protocol_vectors.py`, `dev/protocol-vectors.json` |
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

## 5-6. task 보관과 pending 다시 보기 (6개)

| 테스트 | 확인하는 것 |
|---|---|
| 다시 보기와 재시작(실제 소켓) | pending 답에 다시 볼 `url`, 다시 봐도 아직이면 무엇을 기다리는지, 답이 오면 결과. 받는 peer가 재시작하면 끝난 task는 결과 그대로, 일하던 task는 "restarted, ask again"으로 닫힘, 없는 task는 그렇다고 함 |
| task 보관 | 최근 것만 남김, context별 목록, 지운 것은 파일에서도 사라짐 |
| task 없는 transport | 그렇다고 말함 |
| 사람이 정하는 중인 계약 | 기본 비서의 contract가 pending이면 거절도 기록도 아닌 기다림으로 남고, 예약이 걸리고, 상태 줄에 보이고, 다시 봤을 때 아직이면 그대로, 답이 오면 코드가 원장에 계약을 기록하고 알림 |
| 지금 보기와 거절 | `check_pending`, 상대 소유자가 거절하면 기다림이 끝나고 사유를 받음 |
| finisher | 도구별 마무리는 한 번만 등록 |

이 작업에서 `arena/peer/assistant/core.py`에 똑같이 두 번 들어가 있던 메서드 세 개(`host_event`, `on_event`, `on_timer`, 앞선 refactor의 실수, 동작은 같았음)를 하나로 정리했다.

## 5-7. 원장 크기 상한과 link peer (8개)

| 테스트 | 확인하는 것 |
|---|---|
| free-form field 상한 (`tests/test_ledger_sizes.py`) | 기본값 256·4096 bytes, 작은 free-form은 통과, 넘으면 거절하고 field 이름과 "원장 밖에"를 알림, 종류가 아는 field는 free-form이 아님 |
| entry 상한 | 큰 `ref`는 entry 상한으로 거절, field를 선언하지 않은 앱의 종류는 entry 상한만 받음 |
| 모든 기본 종류가 field를 선언 | 등록된 event column도 아는 field로 셈 |
| link peer의 버전 (`tests/test_link_peer.py`) | ver는 마지막 + 1, 남이 서명한 것·바뀐 서명·owner/name/content hash 변경·link 안의 link·빈 목록·모르는 kind·틀린 id 거절, 이력, `link.info`, 프로필 |
| key rotation 뒤 | 물러난 처음 key는 link를 못 바꾸고 지금 key는 바꿈, 읽는 쪽도 기록자를 물어 확인(묻지 않으면 처음 key만 인정) |
| 작품과 link | 원장 `ref`에는 link만(URL 없음), colophon과 주소에 link, resolve·relink 뒤 새 위치, **원장은 그대로**, 다른 작가 거절, link peer가 위치를 바꿔치기하면 서명으로 잡힘 |
| 원장의 link 위치 확인 | link는 전용 field(`peer` hex 64, `link_id` hex 32), 한 문자열로 묶은 `location`은 거절, kind마다 자기 field만, `via` 모양 |
| free-form은 글만 | 코드가 쓸 값(객체)을 free-form에 넣으면 거절하고 "전용 field로"를 알림 |
| 명령 | register `--link-peer`, relink(참조 파일), resolve(참조 파일, id와 owner), link peer 주소가 없을 때 |

실제 프로세스 테스트(`tests/test_runner_processes.py`)에 link peer 프로세스(api만)와 `python -m arena.content register --link-peer`·`relink`·`resolve`를 더했다. service peer와 link peer가 연결 방식(a2a, api)을 여는 부분은 `arena/peers/common.py`의 `open_connections`·`run_with_connections`로 합쳤다.

## 5-8. 여러 link peer, broker 재연결, docker 배치

| 테스트 | 확인하는 것 |
|---|---|
| 여러 link peer (`tests/test_link_peer.py`) | link id는 어디서나 같음, 원장 `ref`에 link peer마다 link 하나, 위치를 옮기면 모든 link peer에 새 버전, 한 link peer가 위조해도 다른 쪽이 답함, 닿지 않는 link peer는 건너뜀, 아무 데도 없으면 그렇다고 함 |
| link 보관소 | SQLite와 메모리 보관소가 같은 약속을 지킴(최근 버전만, 개수, 디스크에 남음) |
| broker 재연결 (`tests/test_presence.py`) | broker가 아직 없으면 1·2·4초…(상한)로 다시 시도하고, 닿으면 profile을 게시하고 만료 전에 다시 게시. 앱 하나가 시작하지 못해도 peer는 멈추지 않음 |
| docker 배치 (`tests/test_deploy.py`) | peer마다 디렉토리·compose·`.env.example`, compose에 build 없음, 실행 모듈이 있음, `.env.example`의 설정이 실제 설정, 예시 service spec이 실림, compose 문법(docker가 있을 때) |
| 실제 container (선택, `ARENA_TEST_DOCKER=1`) | 이미지 build, broker보다 먼저 뜬 link peer가 다시 시도하다가 broker가 뜨면 연결하고 `link.info`에 답함 |

이 서버에서 실제로 6개 container(test broker, link, foundation, service, key, app store peer)를 띄워 확인했다(`dev/docker.md` 5절).

## 5-9. 무전기 방식 a2a와 통합 창 (10개)

| 테스트 | 확인하는 것 |
|---|---|
| webhook으로 오는 사람의 답 (`tests/test_a2a_push.py`, 실제 소켓, 실제 peer 둘) | 다시 묻기 간격을 30초로 두어도 사람이 0.5초 뒤 답하면 몇 초 안에 받음(알림으로 깨어나 직접 다시 물음), 끝난 호출의 token은 잊음 |
| pending 호출 | 기다림 한도가 지난 뒤 사람이 답하면 알림이 다시 볼 예약을 지금으로 당김 |
| 가짜·엉뚱한 알림 | 모르는 token, 다른 task, JSON 아님은 401. 맞는 token이어도 알림 본문(가짜 완료)은 결과로 쓰지 않고 깨우기만 함 |
| 알림 주소 규칙 | webhook 경로가 아닌 주소(내부 주소 등)는 받는 쪽이 요청 단계에서 거절 |
| SSE | 바깥 client가 streaming으로 빠른 답과 느린 답(진행을 흘려받음)을 받음 |
| scheduler | 그 event의 그 kind 예약만 지금으로 당김 |
| timeline과 말하기 (`tests/test_console.py`) | 받은 말(참가 신청, 메시지)은 in, 상대 agent가 한 말은 그쪽에서 out, 사람이 창에서 보낸 말은 out(by owner)으로 남고 상대에게 닿음, 빈 말 거절, LLM이 없으면 지시와 agent 대화는 거절, 토큰 없이는 401 |
| agent와 함께 | 내 지시, agent의 행동과 결과, 공지가 timeline에 남음, 내 agent와 말 주고받기 |
| 화면 (`tests/ui/test_console_ui.py`, Playwright, 7개) | 받은 말이 말풍선으로 보이고, 칸에 써서 보내면 내 말풍선이 생기고 상대에게 닿음, LLM이 없으면 지시·agent 칸 없음. agent 모드에서 지시와 내 agent 대화. 토큰 없이 열면 안내. 물음에 답하고 글 쓰기. 도구를 직접 실행하면 상대에게 닿고 대화에 내 행동으로 남음. 운전석을 suggest로 바꾸고 제안을 거절했다가 승인. 일정 넣어 이벤트 열기 |

desk 창의 공통 모듈(ApiClient, Poller, Store, Actions, 카드·이벤트 목록·이벤트 열기·알림·도구 form·토스트, 공통 CSS)을 `/common/owner/`로 옮겨 desk와 console이 함께 쓴다. 내 agent와의 대화는 `AgentTalk`로 뽑아 chat과 console이 함께 쓴다. 화면 테스트는 모두 15개(desk 5, chat 3, console 7)다.

## 5-10. 결재를 공동 서명으로 (7개)

사용자(2026-11-04): "결재는 특별한 것이 아니야. event 게시자의 의도로 하는 거야. event의 효력이나 명성을 위한 장치인 거야", "2가지 선택 옵션이 있다고 하자". 이벤트 선언의 결재자(`approvers`)를 빼고, 선언 뒤에 받는 공동 서명을 두 방식(`ledger`, `signature`)으로 더했다(dev/protocol.md 4.9절).

| 테스트 | 확인하는 것 |
|---|---|
| 선언 뒤의 공동 서명 (`tests/test_ledger.py`) | 이벤트는 개최자 혼자 서명해 선언됨, 결재자 field는 free-form 규칙으로 거절. `endorse` 항목은 선언된 그 이벤트의 해시만 가리키고, 개최자만 청하며, 같은 서명자는 한 번만, 개최자 자신은 안 됨, 닫힌 뒤에도 덧붙음. 앞의 항목은 하나도 바뀌지 않음(해시 체인 그대로) |
| 감사 | 감사가 `endorse` 항목의 두 서명을 다시 확인해 바뀐 서명을 찾음 |
| 청받는 쪽 (`tests/test_peer.py`) | 내가 아닌 서명자 이름, 빠진 field, 모르는 방식은 거절, 앱이 거절하면 그 이유로 거절, 정하는 앱이 없으면 거절, 앱이 받아들이면 본문에 서명 |
| 원장 방식 (`tests/test_endorse.py`) | 청하고 받은 서명으로 `endorse` 항목을 기록, 영수증 보관, 실적에 준 수(`endorsements`)와 받은 수(`endorsed`) |
| 원장 밖 방식 | 원장은 자라지 않고, 토큰을 공지에 실어 다시 냄(`ver` + 1), 참가자의 비서가 토큰을 확인해 받아 둠, 다른 이벤트의 토큰과 서명이 틀린 토큰은 버림 |
| 거절과 가짜 이벤트 | 소유자가 거절하면 아무것도 남지 않고 이벤트는 그대로 진행, 원장에 없는 해시는 청받는 쪽이 서명 전에 원장에서 확인해 거절 |
| 비서 도구와 느린 답 | 기본 비서의 `ask_endorsement` 도구, 사람이 늦게 답하면 pending으로 보관했다가 끝나면 마무리(finisher) |

경연 모티브(`tests/motif/`)는 조직이 사장님의 공동 서명을 받아야만 공모를 여는 흐름으로 바꿨다. 그것은 조직의 선택이고 원장의 관문이 아니다. 실제 LLM 모티브(`tests/live/test_motif_live.py`)도 같이 고쳤지만 돌리지 않았다.

## 5-11. 원장 없는 broker 그룹 (11개)

사용자(2026-11-02): "non-recorder 모드로 broker group 단위로 사용도 가능할 수 있겠다". 2026-11-04 "P6-N1~N3부터 진행해", "genesis test 도 했어?"

| 테스트 | 확인하는 것 |
|---|---|
| broker가 선언을 보관하고 나눔 (`tests/test_groups.py`) | founder가 아닌 서명, 그룹의 실제와 다른 `closed`, 자기 키가 없는 `brokers`, 다른 그룹, `ver` 0, 같거나 옛 판은 거절. 받으면 이웃 broker에 나눔, 재시작해도 남음. 만민 그룹과 founder가 정해지지 않은 broker는 받지 않음, 닫힌 그룹은 주인이 founder |
| 선언의 모양과 다음 판 | 빠진 field와 틀린 값, 원장 칸 모양(hex64, http(s)), 같은 founder, 한 번 붙은 원장은 떼거나 바꿀 수 없고 기록자 주소만 바뀜 |
| HTTP | `POST /group`·`GET /group`을 실제 HTTP 앱으로 |
| peer가 보는 그룹 | 만민 그룹과 선언 없는 그룹은 원장 그룹, broker가 founder 서명 없이 바꾼 선언은 원장 그룹(더 엄한 쪽), `ledger: null`이면 원장 없는 그룹. 기억 시간 안에는 다시 읽지 않고, `fresh`면 다시 읽음. broker가 답하지 않으면 원장 그룹 |
| 원장 없는 그룹의 이벤트 | 공지에 원장 선언이 없고 원장에 아무것도 기록되지 않음, 참가자의 배정기가 앱에 넘김. 요소를 켜면 개최가 거절됨, 요소를 켠 공지를 직접 올려도 참가자가 버림. 만민 그룹에서는 원장 선언 없는 공지를 버림 |
| 기본 비서 | 원장 없는 이벤트에서 원장 도구 14개가 빠지고 `close_notice`가 들어감, 손으로 불러도 거절, `call_service`의 `subject` 거절, 프롬프트에 "원장 없음", 참가자에게 "원장이 없다"고 알림, 공지 마감으로 끝남. 원장 이벤트에서는 `close_notice`가 없고 손으로 불러도 거절 |
| 나중에 원장 붙이기 | 선언 전에는 붙일 수 없음, 붙이면 founder의 `group` 항목이 원장에 남고 선언이 2판, 그 전의 이벤트는 원장에 없음. 두 번 붙이거나 떼는 것은 거절. 그 뒤 새 이벤트는 말하지 않아도 그 원장에 선언됨, 원장 선언 없는 새 공지는 버리고 이미 하던 이벤트의 수정은 계속 넘김. 증명되지 않는 원장을 가리키는 선언은 원장 그룹으로 보되 증명 안 됨 |
| 다른 원장의 이벤트 | 그룹에 붙은 원장이 아닌 곳에 선언된 공지는 버림 |
| 원장이 거절하면 | 제네시스 없이 시작한 기록자, 같은 그룹을 먼저 선언한 다른 사람이 있으면 붙이기가 멈추고 broker의 선언은 그대로 |
| 명령 | `python -m arena.groups show`·`declare`·`attach`, `--recorder` 없는 attach 거절, 새 판은 붙은 원장을 지킴, 만민 그룹 broker에는 선언하지 못함 |
| **진짜 제네시스 위에서, 실제 프로세스** (`tests/test_groups_processes.py`) | `python -m arena.genesis`(broker, recorder, god)와 서로 이웃인 team broker 둘을 프로세스로 띄우고, founder가 `python -m arena.groups`를 실행. 만민 그룹은 선언을 받지 않음, 한 broker에 선언하면 다른 broker에도 있음, 원장 없는 그룹으로 보임. 붙이면 제네시스 원장에 founder의 `group` 항목이 있고 두 broker가 그 항목을 가리킴, 증명된 원장으로 보임, 두 번 붙이기 거절, broker를 다시 띄워도 남음 |

알게 된 한계: 원장은 한 그룹의 `group` 항목을 먼저 낸 사람의 것으로 받는다. 다른 사람이 먼저 같은 `group_id`를 원장에 선언하면 진짜 founder는 그 원장에 붙일 수 없다(테스트가 이를 확인한다). 원장이 founder를 broker 선언과 맞춰 보는 장치는 아직 없다.

## 5-12. 그룹 생성권 모의 실험과 스핑크스 peer (24개)

| 테스트 | 확인하는 것 |
|---|---|
| 모의 실험 (`tests/test_sim_rights.py`, 14개) | 조절 logic이 맞는 방향으로 움직임(재고 보정, 하루 변화 폭, window), 설계별 발견을 고정(D1 재고 보정이 마구 쓰기에 뚫림, D2 흐름만으로는 몫을 못 지킴, D3 하루 상한이 반짝 공격을 막음, D5 양도 불가 보증 길이 정직한 사람을 지킴, D7 줄어드는 일정이 성장을 굶김, D8 전체 발행 추이가 복리로 부풀고 공격자가 키움, D9 보증 쓰임 추이가 성장을 따르고 공격을 무시), 같은 씨앗이면 같은 결과, 명령이 표를 씀. 결과: `dev/sim-rights.md` |
| 통과 증명서 (`tests/test_sphinx.py`) | 스핑크스 서명, founder 키에만(양도 불가), 기한, 믿는 스핑크스 목록, 틀린 모양 |
| 신청 | founder 키가 지금 서명한 신청만 받음(모양, 공개키, 글 길이, 시각, 서명). 틀리면 사람에게 가지 않음 |
| 승인 | 사람의 창에 founder 키, 목적, 연락처, 확인할 것이 보임. 같은 founder는 한 번에 하나, 유효한 증명서가 있으면 다시 주지 않음. 승인하면 증명서, 상태와 정보 op |
| 거절과 시간 초과 | 사람이 거절하면 `rejected`와 이유, 정하지 않으면 `expired`(전용 field `Answer.answered`로 구별), 다시 신청 가능 |
| 상한 | 기간당 상한: 둘 다 승인해도 하나는 한도로 거절, 다음 기간에는 다시 받음 |
| 재시작 | 기다리던 신청을 다시 물음 |
| 신청자 명령 | `python -m arena.groups apply`(peer home 또는 키 파일)와 `pass --out`, 빠진 인자 거절 |
| 실행 | 사람 모드가 아니면 띄우지 않음, 사람 모드면 사람의 peer에 스핑크스 역할 |
| **진짜 제네시스 위에서, 실제 프로세스** (`tests/test_sphinx_processes.py`) | `python -m arena.genesis`와 `python -m arena.peers.sphinx`(사람 모드, console 창)를 띄움. 스핑크스가 broker에 "그룹 생성 허락"으로 보임, 신청자가 `python -m arena.groups apply`로 a2a 신청, 사람이 창의 API에서 신청을 보고 승인, 신청자가 `pass`로 증명서를 받아 확인 |
| 실행 디렉토리 (`tests/test_deploy.py`) | `deploy/sphinx-peer`의 compose와 `.env.example` |

## 5-13. 모든 창의 한 가지 모양과 peer 종류별 바탕 (7개)

사용자(2026-11-04): "동일한 identity를 가진 html ui(css) 디자인으로 모든 web ui 디자인 통일하자", "각 peer(주로 api 서빙)는 바탕색상을 달리해서 구분하자. 예를 들어 관전 peer는 녹색 바탕". 규칙은 `.claude/skills/arena-ui/SKILL.md`, 모양은 `arena/bundled/common_static/arena.css` 한 파일이다.

| 테스트 | 확인하는 것 |
|---|---|
| 세 창의 같은 모양 (`tests/ui/test_ui_identity.py`, desk·console·chat 3개) | 밝은 화면과 어두운 화면에서 강조색, 창 바탕, 글꼴이 세 창 모두 같은 값. 머리줄에 종류 태그 "개인 peer" |
| 종류가 바탕을 물들임 (스핑크스, 관전 2개) | 스핑크스는 모래색, 관전 peer는 녹색 바탕(밝은·어두운), 머리줄에 이름 |
| 모든 종류 | `peer_kinds.py`의 아홉 종류가 밝은 화면과 어두운 화면에서 저마다 다른 바탕이고 이름이 나옴 |
| 실행 명령의 종류 (`tests/test_peer_kinds.py`) | 키, 앱 배포, 재단, 검색 peer가 자기 종류를 갖고, 스핑크스 실행은 `sphinx`, god은 `observer` |

`ARENA_UI_SHOTS=<폴더>`를 주면 창마다 밝은·어두운 스크린샷을 남긴다. 기존 화면 테스트 15개는 class 대신 `data-testid`로 찾으므로 그대로 통과한다. 알려진 불안정: `test_in_the_console_the_person_runs_a_tool_by_hand_and_sees_it_in_the_conversation`이 전체를 돌릴 때 가끔 시간 초과로 실패한다(이번 변경 전에도 3번 중 1번). 혼자 돌리면 통과한다. 원인은 아직 찾지 못했다.

## 6. 아직 덜 덮인 곳과 그 이유

| 모듈 | 커버리지 | 덜 덮인 곳 | 이유와 다음 |
|---|---|---|---|
| `arena/a2a.py` | 87.5% | 스트리밍, 일부 연결 오류 | 느린 답의 task와 남의 agent의 task 상태는 5-5절에서 실제 소켓으로 확인한다. 스트리밍은 쓰지 않는다(agent card가 `streaming: false`) |
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
