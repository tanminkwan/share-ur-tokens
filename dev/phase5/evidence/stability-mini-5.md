# 반복 안정성: tests/live/test_rps_mini.py, 5번 (2026-11-02 10:43)

- 플랫폼 보장 지켜짐: 5/5
- LLM이 끝까지 해냄(참고): 5/5
- LLM 판정 오류(참고): 0/5

| 실행 | 플랫폼 보장 | 원장 감사 | 원장 항목 | 종료 | LLM 완주 | 걸린 시간(초) | pytest 종료 코드 |
|---|---|---|---|---|---|---|---|
| 1 | 예 | ok | 12 | 예 | 예 | 24.3 | 0 |
| 2 | 예 | ok | 11 | 예 | 예 | 51.5 | 0 |
| 3 | 예 | ok | 11 | 예 | 예 | 51.6 | 0 |
| 4 | 예 | ok | 11 | 예 | 예 | 51.5 | 0 |
| 5 | 예 | ok | 11 | 예 | 예 | 51.5 | 0 |
run 1: moves: a=가위 b=바위; winner recorded 382f90, by the rules 382f90; LLM judgement error: no; messages: 6
run 2: moves: a=가위 b=가위; winner recorded (draw), by the rules (draw); LLM judgement error: no; messages: 7
run 3: moves: a=바위 b=가위; winner recorded 061c21, by the rules 061c21; LLM judgement error: no; messages: 7
run 4: moves: a=가위 b=가위; winner recorded (draw), by the rules (draw); LLM judgement error: no; messages: 6
run 5: moves: a=가위 b=바위; winner recorded 429574, by the rules 429574; LLM judgement error: no; messages: 6
