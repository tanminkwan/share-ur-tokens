# 근거는 어디에 있나

저장소에는 두 시기의 문서가 있습니다.

- **`dev/`**: 플랫폼 개발이 시작된 뒤(2026-10-30 이후)의 문서. 지금의 코드와 맞으며 **우선**한다.
- **`docs/`**: 기획 단계 문서. 이름이 "에이전트 광장"이거나 지금 구조와 다른 곳이 있다. 쓰기 전에 `dev/`와 코드로 확인한다.

| 쓰려는 것 | 먼저 볼 곳 | 확인할 곳 |
|---|---|---|
| 방향, 원칙, 범위, 단계 | `dev/plan.md` | 단계별 `dev/phaseN/requirements.md` |
| 생태계가 자라는 방향, 굳히는 세 모양 | `dev/plan.md` "생태계가 자라는 방향" | - |
| 단계별 요구사항과 상태 | `dev/phaseN/requirements.md` | `dev/phaseN/test-results.md` |
| 설계와 그림 | `dev/phaseN/design.md` | 코드 |
| 실제 LLM 실행 기록(횟수, 통과, 무엇이 드러났나) | `dev/phase5/test-results.md` | `dev/phase5/evidence/*.txt` |
| 인수 절차(가위바위보) | `dev/acceptance-rps.md` | `dev/acceptance-rps-rules.md`, `dev/acceptance-rps-mini-rules.md` |
| 앱 SDK와 규약 | `dev/app-guide.md` | `arena/sdk/`, `arena/peer/plugin.py` |
| 원장 항목 종류와 규칙 | `arena/ledger/types.py` | `arena/ledger/rules.py` |
| 기본 비서의 도구 | `arena/peer/assistant/tools.py` | `arena/peer/assistant/core.py` |
| 설정 값(시간, 상한) | `.env.example` | `arena/config.py` |
| 테스트 수 | `pytest --ignore=tests/live` 실행 결과 | - |
| 신뢰·보안, broker, A2A 거래(기획 단계) | `docs/trust-and-security.md`, `docs/broker-and-discovery.md`, `docs/a2a-transaction.md` | 지금 코드와 다르면 코드를 따른다 |
| 다른 방식과 비교(기획 단계) | `docs/competitive-comparison.md` | 확인해서 쓴다 |

## 상태 표시

기능이나 주장마다 아래 중 하나가 분명해야 합니다. 문장으로 풀어 써도 되고, 표에 칸으로 둬도 됩니다.

| 상태 | 뜻 | 근거 |
|---|---|---|
| 구현·테스트됨 | 코드가 있고 실제 LLM 없는 테스트가 통과 | 요구사항 번호, 테스트 파일 |
| 실제 실행 확인 | 실제 LLM으로 돌려 확인 | `dev/phase5/evidence/` 파일 |
| 계획 | 단계 계획에 있으나 아직 없음 | `dev/plan.md`의 단계 |
| 미정 | 사용자가 아직 정하지 않음 | 사용자 확인 필요로 표시 |

숫자는 바뀝니다(테스트 수, 실행 횟수). 숫자를 쓸 때는 "언제 기준"인지 날짜를 함께 적습니다.
