# 9단계 시험 결과: peer가 정하는 필명

> 2026-11-06, 브랜치 `pen-name-20261106`. 요구사항 [requirements.md](requirements.md), 설계 [design.md](design.md).

## 1. 요약

- 요구사항 P9-A1~A7, B1~B6, C1~C3, D1~D3 모두 ✅.
- 새 테스트 24개: 순수 규칙 8(`tests/test_p9_names.py`), peer·broker·이름 해석 15(`tests/test_p9_peer_names.py`), 브라우저 창 1(`tests/ui/test_console_ui.py`). 기존 테스트 7개의 필명 접두사를 새 규칙으로 고쳤다.
- 전체 594개 테스트: 593 통과, 1 건너뜀(opt-in, 이전과 같음). 실제 LLM은 쓰지 않았다. 커버리지 94.5%(기준 92%).
- `dev/protocol-vectors.json`의 `pen_name`(`필명-79b556`)은 기본 닉네임에서 같은 값이라 바꾸지 않았다.

## 2. 요구사항별

| 번호 | 확인한 것 | 테스트 |
|---|---|---|
| P9-A1, A3 | 필명은 닉네임 + 키 앞 6자. 닉네임은 서명된 프로필의 `nick` | `test_p9a1_the_pen_name_is_the_nickname_and_the_key_start` |
| P9-A2 | 닉네임이 없으면 기본 닉네임 | `test_p9a2_without_a_nickname_the_default_one_is_used` |
| P9-A4 | 모양 규칙, 어긴 설정은 peer가 시작하지 않고, 어긴 프로필은 broker가 거절 | `test_p9a4_*` 3개 |
| P9-A5 | 아무 때나 바꿈, 바로 게시(버전 +1), 같은 값은 다시 게시 안 함, 재시작 뒤에도 유지, LLM을 부르지 않음, 창에서 바꿈 | `test_p9a5_*` 4개, UI `test_p9a5_the_owner_renames_the_peer_in_the_window_at_any_time` |
| P9-A6 | 같은 닉네임이 둘이어도 등록됨 | `test_p9a6_nicknames_may_repeat` |
| P9-A7 | 바꾼 뒤 옛 닉네임은 아무도 가리키지 않고, 새 이름과 현재 전체 필명은 통한다 | `test_p9a7_the_old_nickname_stops_working_after_a_change` |
| P9-B1~B3 | 전체 필명, 닉네임만, 닉네임 + 키 앞부분 | `test_p9b1_*`, `test_p9b2_*`, `test_p9b3_*` (규칙 4개, peer 2개) |
| P9-B4 | 여럿이면 거절하고 후보 필명을 전체로, 없으면 못 찾음, 도구는 오류로 돌려줌 | `test_p9b4_*` 5개 |
| P9-C1~C3 | 남은 프로필에서 본 닉네임으로, 못 본 키는 기본 닉네임으로 | `test_p9c_others_are_shown_by_the_nickname_they_posted` |
| Q3(대소문자) | 찾을 때 구분하지 않고 표시는 정한 그대로 | `test_p9_q3_*` |

## 3. 실제 서버로는 아직 확인하지 않았다

- 이 시험은 모두 메모리 안 세계와 한 대의 headless 브라우저다. 시험용 docker 컨테이너(`10.10.20.11`)에는 새 코드가 반영되지 않았다. 이미지를 다시 빌드하고 컨테이너를 새로 띄워야 한다.
- 두 peer가 실제 프로세스로 닉네임을 주고받는 시험(`real-genesis-tests` 방침)은 아직 하지 않았다.
