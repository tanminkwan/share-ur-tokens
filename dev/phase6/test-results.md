# 6단계 테스트 결과 (6-0~6-D, 6-V 완료 · 2026-11-02)

> 판정 기준은 5단계 2-1절과 같다. ⑴ 순수 플랫폼과 기본 요소만으로 이벤트 흐름이 끝까지 **가능한가**. ⑵ 모든 실행에서 **플랫폼 보장**(원장 감사, 서명, 원장 규칙)이 깨지지 않았는가. LLM 판정 오류는 따로 적고 실패로 세지 않는다.

## 1. 한 줄 요약

- 실제 LLM을 쓰지 않는 테스트: **347개 모두 통과**(`pytest --ignore=tests/live`, 화면 테스트 5개 포함, 2026-11-02 마지막 확인).
- 기본 요소 세 가지(제출 받기 `intake`, 평가 `evaluation`, 봉인 묶음 `sealed`)와 API를 제공하는 peer 틀, 연결 방식(human, a2a, api)이 들어갔다.
- **요소를 켠 가위바위보 한 판이 실제 LLM으로 끝까지 갔다**(실행 3). 승패는 LLM이 아니라 판정 API peer가 원장의 두 공개로 계산해 기록했다.
- **요소 있을 때와 없을 때(각 5번)**: 고친 뒤에는 둘 다 5번 모두 끝까지 갔고 플랫폼 보장도 모두 지켜졌다. 걸린 시간은 비슷했고(평균 46초 대 49초), 요소를 켠 쪽이 LLM 호출과 토큰을 약 4분의 1 더 썼다. 이 한 판짜리 놀이에서 요소가 준 것은 **비용 절감이 아니라 보장**이다(4절).

## 2. 요소를 켠 실제 실행 (`tests/live/test_rps_mini_elements.py`)

규칙: `dev/acceptance-rps-mini-elements-rules.md`. 봉인 묶음을 켜고, 판정은 API peer(`tests/service_samples/rps_referee.py`)가 한다.

| 실행 | 결과 | 원장 항목 | LLM 사용 | 드러난 문제 | 그 뒤 넣은 범용 기능 | 증거 |
|---|---|---|---|---|---|---|
| 1 | 실패(600초) | event, publish, reveal, contract, contract, assign | 113번, 약 27만 5천 토큰 | 배정 전에 한 선수가 m1을 등록하고 공개. 배정 뒤 m1은 이미 열려 상대가 등록하지 못해 판이 멈춤. 선수가 op `judge`가 없는 peer에 판정을 요청 | 봉인 이벤트에서는 배정된 라벨만 공개(원장 규칙). op가 없는 peer에 요청하면 그 op를 프로필에 내건 peer를 알려 줌 | `evidence/rps-minielem1.log` |
| 2 | 실패(600초) | event, publish, contract, contract, assign, publish, reveal, reveal | 139번, 약 37만 5천 토큰 | 봉인은 맞게 동작(배정 전 공개 거절, 둘 다 등록한 뒤 공개). 개최자가 지시에 적힌 판정 peer를 잊고 소유자에게 거듭 물어 referee 계약을 맺지 못함 | 소유자의 지시를 프롬프트에 늘 고정. 개최자 상태 줄에 "아직 계약 없는 역할(프로필에 내건 peer)" | `evidence/rps-minielem2.log` |
| **3** | **통과(18초)** | event, publish, contract ×3, assign, reveal ×2, attest, close | 97번, 약 21만 토큰 | 없음(판정 호출을 개최자 대신 선수가 했으나 결과는 같음). 수: 가위 대 가위, 판정 peer가 무승부 기록 | - | `evidence/rps-minielem3.log` |

플랫폼 보장: 세 실행 모두 원장이 규칙에 어긋난 기록을 받지 않았다(실행 1의 멈춤은 규칙이 허용한 순서의 빈틈이었고, 범용 원장 규칙으로 막았다).

## 3. 요구사항별 자동 테스트

| 묶음 | 테스트 파일 | 결과 |
|---|---|---|
| 6-0 요소 선언 | `tests/test_elements.py` | 통과 |
| 6-A API peer, 영수증, 연결 방식 | `tests/test_service_peer.py`, `tests/test_connections.py` | 통과 |
| 6-B 제출 받기 | `tests/test_intake.py` | 통과 |
| 6-C 평가 | `tests/test_evaluation.py` | 통과 |
| 6-D 봉인 묶음 | `tests/test_sealed.py` | 통과 |
| 6-V1 사용량 재기 | `tests/test_usage.py` | 통과 |
| 6-V2 경연 모티브를 요소로 | `tests/motif/` | 통과 |

## 4. 요소 있을 때와 없을 때 (P6-V3)

같은 가위바위보 한 판을 두 방식으로 각 5번 실제 LLM(`gpt-oss-120b`)으로 돌렸다(`python -m scripts.compare_elements --runs 5`, 2026-11-02).

- **요소 없이**: 자연어 규칙만(`tests/live/test_rps_mini.py`). 승패는 선수들의 LLM이 정해 공동 확인한다.
- **요소를 켜고**: 봉인 묶음 + 판정 API peer(`tests/live/test_rps_mini_elements.py`). 공개 순서는 원장이, 승패는 판정 peer의 코드가 정한다.

| 방식 | 플랫폼 보장 | 끝까지 감 | LLM 판정 오류 | 평균 시간(초) | 평균 LLM 호출 | 평균 토큰 |
|---|---|---|---|---|---|---|
| 요소 없이 | 5/5 | 5/5 | 0/5 | 46.1 | 89.8 | 208,297 |
| 요소를 켜고 (1차) | 5/5 | 4/5 | 0/5 | 160.1 | 109.0 | 262,746 |
| 요소를 켜고 (고친 뒤) | 5/5 | **5/5** | 0/5 | 48.6 | 111.6 | 261,744 |

**1차의 실패 1번**(`evidence/compare-rps-mini/with-run2.log`): 한 선수가 배정 전에 공개하려다 원장에 거절당했고(봉인 규칙대로), 배정이 난 뒤 같은 공개를 다시 하려 했으나 "같은 행동을 연달아 하지 않기" 장치가 그 재시도까지 막았다. 앞의 시도가 실패였는데도 막은 것이라 플랫폼 결함이다. 판정 호출에서도 알아볼 수 없는 오류("None", `KeyError: 'recorder_url'`)가 나왔다. 고친 것(범용): 실패한 호출은 그대로 다시 할 수 있다. 원장에 기록하는 서비스 op는 이벤트와 주제 없이 부르면 무엇이 필요한지 알린다. 서비스 함수가 낸 오류는 부른 쪽에 그대로 전한다(`tests/test_assistant.py::test_p5c26_a_failed_call_may_be_retried_as_it_is`, `tests/test_service_peer.py::test_p6a3_a_recording_op_called_without_an_event_says_so_and_errors_reach_the_caller`).

**읽는 법**

1. **보장은 요소를 켠 쪽만 코드로 선다.** 요소 없는 5번에서 공개 순서와 승패가 맞은 것은 LLM이 이번에 잘해서다. 5단계에서는 같은 일이 틀렸다(먼저 공개 mini 1, 승패를 거꾸로 적은 실행 11·13). 요소를 켜면 순서는 원장이 막고(2절 실행 2·3과 1차 실패에서 원장이 배정 전 공개를 실제로 거절했다), 승패는 판정 peer의 코드가 계산해 서명한다.
2. **이 크기에서는 토큰이 줄지 않았다. 오히려 약 4분의 1 늘었다.** 요소를 켠 쪽은 판정 peer와 계약하고, 판정을 부르고, 판정 peer가 기록하는 단계가 더 있다. 그리고 요소는 진행 규칙을 코드로 지킬 뿐, 진행은 여전히 각 peer의 LLM이 한 걸음씩 이끈다. 토큰 대부분은 그 걸음(무엇을 할지 고르기, 기다리기)에서 나온다.
3. **그래서 토큰을 줄이는 것은 요소가 아니라 앱이다.** 진행 자체를 코드가 맡아 LLM이 걸음마다 판단하지 않게 해야 토큰이 준다. 요소는 앱과 기본 비서가 함께 쓰는 "틀리면 안 되는 부분"이다. 이 결과는 "명확한 절차는 코드로"라는 방향과 맞지만, 그 효과를 비용으로 보이려면 진행을 코드가 맡는 앱과 비교해야 한다(다음 과제 후보).

증거: `evidence/compare-rps-mini/`(실행별 기록 15개, 1차 요약 `summary-first.md`, 고친 뒤 결과 `with-after-fix.json`).

## 5. peer 표준과 견본 개인 peer (6-P)

| 무엇 | 테스트 | 결과 |
|---|---|---|
| 프로필의 `operator`(service·agent·human), broker 확인 | `tests/test_desk.py::test_p6p2_...` | 통과 |
| 소유자 창구: 답 기다리기, 시간 넘으면 아니오, 재시작하면 기다리던 것 닫기 | `tests/test_desk.py::test_p6p3_...` | 통과 |
| 운전석 수동: LLM 없이 공지가 창구에, 사람이 같은 도구로 참가 신청 | `tests/test_desk.py::test_p6p4_manual_...` | 통과 |
| 운전석 제안: LLM이 고른 행동을 거절하면 멈추고, 승인하면 실행 | `tests/test_desk.py::test_p6p4_suggest_...` | 통과 |
| 소유자 API: 토큰, 상태·알림·답하기·이벤트·도구 실행·이벤트 열기 | `tests/test_owner_api.py` | 통과 |
| 견본 개인 peer 조립: LLM 없으면 human, 있으면 agent, 설정이 잘못된 LLM은 오류, 재시작해도 같은 키와 토큰 | `tests/test_owner_api.py::test_p6p6_...` | 통과 |
| **화면(Playwright headless Chromium)**: 토큰 없으면 막힘·주소창에서 토큰 지움, 사람이 손으로 참가 신청, 물음에 답하고 글 쓰기, 제안 거절·승인, 일정을 넣어 이벤트 열기 | `tests/ui/test_desk_ui.py`(5개) | 통과 |

화면은 실제 포트로 띄운 소유자 API에 headless Chromium이 붙어 돈다. 실제 LLM은 쓰지 않았다(사람 peer는 LLM이 없고, 제안 시험의 agent peer는 정해진 답을 내는 대역). 이 서버에는 한글 글꼴이 없어 화면 사진에서 한글이 네모로 보였지만, 테스트는 화면의 글자 내용(DOM)으로 확인하므로 결과와 상관없다. 화면의 CSS는 흔한 한글 글꼴을 차례로 쓴다.
