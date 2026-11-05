---
name: arena-ui
description: 에이전트 아레나(Agent Arena)의 모든 웹 화면(사람의 창: 소유자 창구 desk, 대화 chat, 통합 창 console, 스핑크스 창, 앞으로 만들 관전·특수 목적 peer 창)이 하나의 디자인 정체성을 갖게 하는 규칙. 화면을 새로 만들거나 고칠 때, CSS·색·글꼴·버튼·카드·말풍선·알림·표를 다룰 때, "화면 만들어줘", "UI 고쳐줘", "디자인 통일", "어두운 화면", "다크 모드", "peer마다 색 다르게", "창 추가", "스타일 깨졌어", "버튼 모양", "plugin app 화면"이라고 할 때, arena/bundled/ 아래 static 파일을 건드릴 때는 skill 이름을 말하지 않아도 이 skill을 사용한다.
---

# arena-ui: 모든 창의 한 가지 모양

에이전트 아레나의 사람 화면은 모두 **plugin app**이다(peer core에는 화면이 없다). 창이 여럿이어도, 누가 만들어도 같은 제품으로 보여야 한다. 그래서 모양은 한 파일에 모으고, 창마다 다른 것은 배치뿐이다.

- 공통 모양: `arena/bundled/common_static/arena.css`(창에서는 `/common/arena.css`)
- 창의 CSS는 그것을 import하고 **자기 배치만** 더한다. 예: `arena/bundled/console/static/app.css`, `arena/bundled/chat/static/chat.css`
- 공통 JS 부품: `/common/dom.js`(`h`: 글은 글로만 넣는 DOM 만들기), `/common/owner/views/*.js`(머리줄, 카드, 이벤트 목록, 도구 form, 토스트)

## 왜 이렇게 하나

- **색은 디자인 값(token)으로만 쓴다.** 창의 CSS나 JS에 `#1f6fcc` 같은 색을 직접 쓰면, 어두운 화면과 peer 종류별 바탕색이 그 자리에서 깨진다. 값이 바뀌어야 할 때 한 곳만 고치면 되게 한다.
- **색만으로 뜻을 전하지 않는다.** 색각 이상, 흑백 인쇄, 고대비 모드에서도 읽혀야 한다. peer 종류는 바탕색과 함께 머리줄의 종류 태그로, 상태(성공·실패)는 색과 함께 글로 말한다.
- **빌드 단계가 없다.** 화면은 HTML, CSS, JS 모듈 파일 그대로다. npm, 번들러, CSS 프레임워크를 들이지 않는다. 누구나 같은 파일로 새 창을 만들 수 있게 하기 위해서다(플랫폼의 원칙: 구현은 누구나 만든다).
- **글은 글로만 넣는다.** peer나 LLM이 쓴 글이 화면에서 실행되지 않도록 `innerHTML`을 쓰지 않고 `h()`로만 만든다.

## 디자인 값 (arena.css `:root`)

| 무리 | 값 | 쓰는 곳 |
|---|---|---|
| 바탕 | `--page`(창 바탕, peer 종류가 물들임), `--surface`(카드, 입력칸), `--surface-2`(머리줄, 떠 있는 판), `--surface-3`(대화, 코드처럼 들어간 곳) | |
| 글과 선 | `--fg`, `--muted`, `--line` | 본문, 보조 글, 테두리 |
| 강조 | `--accent`, `--accent-fg`(강조 위 글자), `--accent-soft`(내 말풍선, 고른 항목) | 주된 행동 버튼, 내가 한 말, focus |
| 내 비서 | `--agent-soft` | 내 비서(agent)가 한 말 |
| 상태 | `--ok`, `--warn`, `--bad` | 상태에만. 꾸밈에 쓰지 않는다 |
| 글꼴 | `--font`(system-ui, Pretendard, Apple SD Gothic Neo, Malgun Gothic, Noto Sans KR ...), `--mono` | |
| 크기 | `--fs-sm` 12px, `--fs` 14px, `--fs-lg` 16px | |
| 간격 | `--sp-1` 4px, `--sp-2` 8px, `--sp-3` 12px, `--sp-4` 16px | |
| 모서리, 그림자 | `--r-sm` 4px, `--r` 6px, `--r-lg` 12px(말풍선), `--shadow` | |

밝은 화면과 어두운 화면은 시스템 설정을 따른다(`prefers-color-scheme`). `<html data-theme="light|dark">`로 하나를 강제할 수 있다. 어두운 화면은 같은 이름의 값을 바꿔 끼운 것이지 색을 뒤집은 것이 아니다. 글자 대비는 계산해서 정했다(본문, 보조 글, 강조 모두 4.5:1 이상). 값을 바꾸면 다시 계산한다(아래 "점검").

## peer 종류별 바탕 (`<html data-peer="...">`)

창은 `/api/state`의 `me.kind`로 `document.documentElement.dataset.peer`를 정하고(`showKind`, `/common/owner/views/header.js`), 머리줄에 `me.kind_label`을 태그로 보인다. 종류와 이름은 `arena/bundled/peer_kinds.py`, peer는 `PeerConfig.kind`로 정한다(예: 스핑크스 `personal.build(..., kind="sphinx")`).

| kind | 이름 | 바탕(밝은) | 머리줄(밝은) |
|---|---|---|---|
| `personal` | 개인 peer | 흰색 | 연회색 |
| `sphinx` | 스핑크스 | 연한 모래색 `#fbf6e9` | `#f1e3bd` |
| `observer` | 관전 peer | 연한 녹색 `#eef7f0` | `#d5ecdb` |
| `key` | 키 peer | 연보라 | |
| `link` | link peer | 연한 청록 | |
| `foundation` | 재단 peer | 연한 회청색 | |
| `app-store` | 앱 배포 peer | 연한 주황 | |
| `search` | 검색 peer | 연한 남색 | |
| `service` | 서비스 peer | 연회색 | |

바탕만 물들이고 카드는 `--surface` 그대로 둔다. 그래야 카드가 바탕 위에 떠 보이고 글 대비도 유지된다. 새 종류를 더할 때는 `peer_kinds.py`, `arena.css`(밝은·어두운 둘 다), 이 표를 함께 고친다.

## 부품 (arena.css의 class)

| 부품 | class | 메모 |
|---|---|---|
| 머리줄 | `header`, `.pen`(필명), `.tag`, `.tag.kind`(peer 종류) | 첫 칸은 필명, 바로 뒤에 종류 태그 |
| 칸 나누기 | `main`(기본 3칸), `.col`, `.col.wide` | 창의 CSS에서 `grid-template-columns`만 바꾼다 |
| 카드 | `.card`(`.kind`, `.title`, `.body`), `.ask`(사람의 답을 기다리는 카드: 강조 테두리), `.row`(버튼 줄) | |
| 버튼 | `button`, `.primary`(주된 행동 하나), `.bad`(되돌리기 어려운 행동, 거절) | 한 카드에 `.primary`는 하나 |
| 입력 | `input`, `textarea`, `select`, `label` | |
| 목록 | `.event-item`, `.event-item.selected` | |
| 코드가 만든 글 | `.state`(지금 상태), `.transcript`, `.code`(키, 해시) | 고정폭 글꼴 |
| 대화 | `.timeline`, `.line.in`(받은 말), `.line.out`(내가 한 말), `.by-agent`(내 비서가 한 말), `.line.note`(행동, 알림), `.who` | chat과 console이 같은 말풍선을 쓴다 |
| 쓰는 칸 | `.composer`, `.tell`, `.agent-say` | 글칸과 버튼이 한 줄 |
| 토스트 | `#toast .msg`, `.msg.bad` | |
| 표 | `table`, `th`, `td`, `.num`(숫자는 오른쪽, 자릿수 맞춤) | |
| 빈 상태 | `.empty` | "아직 없다"는 문장으로 |

## 창을 새로 만들 때

1. `arena/bundled/<창>/static/index.html`: `<html lang="ko">`, `<link rel="stylesheet" href="/static/<창>.css">`, `<header id="header" data-testid="header">`, `<div id="toast" data-testid="toast" role="status" aria-live="polite">`, `<main class="<창>">`.
2. `<창>.css`: 첫 줄 `@import url('/common/arena.css');`, 그 아래에는 배치(grid, 높이, 너비)만. 색, 글꼴, 모서리는 쓰지 않는다. 필요하면 값을 `var(--...)`로 쓴다.
3. 머리줄은 공통 `HeaderView`를 쓰거나, 따로 만들면 `showKind(me)`를 부르고 `me-kind` 태그를 넣는다.
4. 화면의 요소에는 `data-testid`를 단다(`h(..., { testid: '...' })`). 화면 테스트가 class가 아니라 이것으로 찾는다.
5. 글: 기술 용어는 영어 그대로(event, ledger, peer, token), 만든 한국어 말(칸, 판, 봉투 등)은 쓰지 않는다. 사람에게 하는 말은 짧은 평서문.
6. 창의 상수(주기, 코드 목록)는 화면 코드에 박지 않고 `/api/config`에서 받는다.

## 점검

- **화면 테스트**: `.venv/bin/python -m pytest tests/ui`. `tests/ui/test_ui_identity.py`가 세 창이 같은 값(강조색, 바탕, 글꼴)을 쓰는지, peer 종류가 바탕과 태그로 나오는지, 어두운 화면을 확인한다. 새 창을 만들면 이 테스트에 그 창을 더한다. 관전 창(`arena/bundled/observer`, god peer의 화면)은 `tests/ui/test_observer_ui.py`가 같은 값과 녹색 바탕, 스스로 갱신하는 것을 확인한다.
- **눈으로 보기**: `ARENA_UI_SHOTS=<폴더> .venv/bin/python -m pytest tests/ui/test_ui_identity.py`가 창마다 밝은·어두운 스크린샷을 남긴다. 겹친 글, 넘친 칸, 버튼 높이를 본다.
- **대비 계산**: 색 값을 바꾸면 글자 대비를 다시 계산한다(WCAG 상대 휘도). 본문·보조 글·강조 글은 4.5:1 이상이어야 한다. 그래프 색이 필요하면 dataviz skill의 `scripts/validate_palette.js`를 쓴다.
- 금지 확인: 창 CSS나 JS에서 `#` 색 값 검색(`grep -n "#[0-9a-fA-F]\{3,6\}" arena/bundled/*/static -r`). arena.css 밖에서 나오면 디자인 값으로 옮긴다.
