# 견본 개인 peer 직접 써 보기

> 2026-11-04. 실제 프로세스로 작은 세계를 띄워 사람의 창을 직접 써 보는 방법. 기본 창은 **console**(통합 창: 관전과 개입)이고 두 모드 모두 같다. desk·chat 창은 `ARENA_PERSONAL_APPS`로 고를 수 있다.

## 1. 띄우기

```bash
.venv/bin/python -m scripts.try_personal --fresh            # 제네시스 + 사람 peer 둘(human-a, human-b), LLM 없음
.venv/bin/python -m scripts.try_personal --fresh --agent    # + agent peer 하나(대화 앱). .env의 ARENA_LLM_*를 쓴다
```

화면 주소가 토큰과 함께 출력된다(예: `human-a (human) 콘솔: http://127.0.0.1:9313/#token=…`). 브라우저로 그 주소를 연다. 토큰은 열자마자 주소창에서 지워지고 그 탭에만 남는다. 멈출 때는 Ctrl-C. 모든 상태와 기록은 `data/try/` 아래에 있다(`--fresh`는 비우고 시작).

**다른 기계의 브라우저로 열려면**: `--web-host 0.0.0.0`으로 띄우거나(같은 망 안에서만 권함), SSH 터널을 쓴다: `ssh -L 9313:127.0.0.1:9313 -L 9323:127.0.0.1:9323 -L 9333:127.0.0.1:9333 <서버>`.

| peer | 모드 | 화면 | 포트(기본) |
|---|---|---|---|
| human-a | human | console | A2A 9310, console 9313 |
| human-b | human | console | A2A 9320, console 9323 |
| agent(`--agent`) | agent | console(내 agent 칸이 보임) | A2A 9330, console 9333 |

**관전 창(god)**: genesis의 god peer가 `--base-port`+4(기본 9304)에 연다. 원장 항목, 무결성, event, peer별 실적을 보여 주고 3초마다 스스로 갱신한다(읽기만). 주소는 console과 같이 토큰과 함께 출력된다.

**console 창**: 왼쪽에 이벤트, 이벤트 열기, 알림(물음·제안·공지·메시지 카드)이 있다. 가운데는 고른 이벤트의 **대화**다. 받은 말은 왼쪽, 내 peer가 한 말은 오른쪽(나 → 상대, 내 agent → 상대), 그 밖의 일(행동과 결과, agent의 생각, 공지, 원장, 예약, 내 지시)은 가운데 작은 글로 보인다. 아래 칸에서 받는 이를 고르고 말을 보내면, 한 번의 a2a message로 간다(무전기 방식: 연결을 열어 두지 않는다). LLM이 있으면 "내 agent에게 지시" 칸과 오른쪽 위 "내 agent"(내 agent와 대화) 칸이 생긴다. 오른쪽에는 운전석, 지금 상태, 일정과 예약, "할 수 있는 일(직접 실행)", 규칙이 있다.

## 2. 해 볼 것

**사람과 사람(console 둘)**
1. human-a console에서 "이벤트 열기"를 펼쳐 제목·종류·규칙(예: "참가 신청을 하면 개최자가 member 역할로 계약한다")을 쓰고 연다. 일정 시각과 종류를 넣으면 그 시각에 양쪽 창구에 알림이 온다.
2. human-b console에 공지 카드가 온다. "이벤트 열기" → "할 수 있는 일"에서 `join_event`를 펼쳐 실행한다.
3. human-a console의 대화에 참가 신청이 보인다. 이벤트를 열고 `contract`에 role `member`, peer에 human-b의 필명(창 맨 위)을 넣어 실행한다. 원장에 계약이 남는다.
4. 대화 아래 칸에서 상대를 고르고 말을 보낸다. 상대의 console 대화에 왼쪽 말풍선으로 뜬다. 답도 같은 방식으로 한다.
5. 그 밖의 도구(`commit`, `reveal`, `send`, `propose_attest`, `close_event` …)도 같은 방식으로 손으로 해 본다. 원장이 거절하는 일은 거절 사유가 화면 오른쪽 위에 뜬다.

**사람과 내 비서(agent console, `--agent`)**
1. agent console의 "내 agent" 칸에서 "지금 무슨 이벤트 있어?"처럼 말한다.
2. human-a가 이벤트를 열면 agent 쪽 비서가 공지를 받고, 참가할지 물으면 알림에 물음 카드가 뜬다. agent가 무엇을 생각하고 했는지는 그 이벤트의 대화에 보인다(관전). 버튼으로 답하거나 "응, 참가해"라고 말로 답한다.
3. "그 이벤트 결과 어떻게 됐어?", "운전석을 제안으로 바꿔 줘"처럼 말해 본다.

## 3. 알아 둘 것

- agent peer는 공지가 올 때마다, 그리고 대화할 때마다 LLM을 부른다(토큰이 든다). 사람 peer 둘만 띄우면 LLM을 전혀 쓰지 않는다.
- 한글 글꼴: 글자는 UTF-8이라 보통의 브라우저에서 문제없다. 서버 안의 headless 브라우저로 사진을 찍으려면 서버에 한글 글꼴이 있어야 한다(RHEL 계열: `google-noto-sans-cjk-ttc-fonts`).
- 화면에서 보이는 것은 peer의 코드가 확인한 것이다. 서명과 원장 대조는 화면이 아니라 peer가 한다.
