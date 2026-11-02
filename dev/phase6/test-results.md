# 6단계 테스트 결과 (진행 중, 2026-11-02)

> 판정 기준은 5단계 2-1절과 같다. ⑴ 순수 플랫폼과 기본 요소만으로 이벤트 흐름이 끝까지 **가능한가**. ⑵ 모든 실행에서 **플랫폼 보장**(원장 감사, 서명, 원장 규칙)이 깨지지 않았는가. LLM 판정 오류는 따로 적고 실패로 세지 않는다.

## 1. 한 줄 요약

- 실제 LLM을 쓰지 않는 테스트: **314개 모두 통과**(`pytest --ignore=tests/live`, 2026-11-02).
- 기본 요소 세 가지(제출 받기 `intake`, 평가 `evaluation`, 봉인 묶음 `sealed`)와 API를 제공하는 peer 틀, 연결 방식(human, a2a, api)이 들어갔다.
- **요소를 켠 가위바위보 한 판이 실제 LLM으로 끝까지 갔다**(실행 3). 승패는 LLM이 아니라 판정 API peer가 원장의 두 공개로 계산해 기록했다.
- 요소 있을 때와 없을 때 비교: 4절(실행 중).

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

(실행 중: `python -m scripts.compare_elements --runs 5`)
