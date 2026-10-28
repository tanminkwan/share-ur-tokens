# (가칭) 사내 정보 장터: p2p + a2a 정보 거래 네트워크

> 사내 AI 해커톤(2일) 기획 문서. 이름은 임시입니다.
> 이전 아이디어(SUT, LLM 토큰 공유)는 `checkpoint-20261023-v2` 브랜치에 보존되어 있습니다.

## 한 줄 요약

정보를 가진 사람(의 에이전트)과 정보가 필요한 사람(의 에이전트)을 **broker가 맥락으로 이어 주고, 연결된 뒤의 거래는 두 에이전트가 직접(p2p + a2a) 끝내는** 네트워크.

## 해결하려는 문제

필요한 정보를 누가 가지고 있는지 모른다. 사내 공지, 메신저, 게시판에 흩어져 있고, 검색으로는 "누구에게 물어야 하는가"와 "그 사람이 지금 줄 수 있는가"를 알 수 없다. 정보를 가진 쪽도 질문을 받기 전에는 자신이 줄 수 있는 것을 알릴 방법이 없다.

## 구조

```
제공자 peer ──노출──▶ broker(domain별 DB) ◀──broker 간 질의──▶ 다른 broker
                           ▲   │
              요청 공개(검색)│   │답변지(공급자 peer 정보 포함)
                           │   ▼
                      소비자 peer ══ p2p 연결 + a2a 거래 ══ 제공자 peer
```

## 문서 구성

| 문서 | 내용 |
|---|---|
| [docs/system-overview.md](docs/system-overview.md) | 구성 요소, 전체 흐름, 메시지 |
| [docs/broker-and-discovery.md](docs/broker-and-discovery.md) | broker의 맥락 기반 DB화, 검색, broker 간 질의 |
| [docs/a2a-transaction.md](docs/a2a-transaction.md) | p2p 연결과 a2a 거래·교환 |
| [docs/trust-and-security.md](docs/trust-and-security.md) | 신원, 신뢰, 사내 보안과 규정 |
| [docs/hackathon-proposal.md](docs/hackathon-proposal.md) | **제출용 신청서** (주최 측 7개 문항) |
| [docs/proposal-notes.md](docs/proposal-notes.md) | 내부 메모: 가정, 예상 질문, 미해결 과제, 일정 |
| [review/premises.md](review/premises.md) | 합의된 전제와 용어. `[가정]`은 확인 필요 |
| [review/review-checklist.md](review/review-checklist.md) | 리뷰 지적과 반영 상태 |

## 작업 방법

- 쓰기: `proposal-writer` 스킬(아이디어 기획자 페르소나). "신청서 다듬어줘", "리뷰 반영해서 고쳐줘".
- 심사: `proposal-reviewer` 스킬(사업·기술·보안 3개 시선의 심사위원 페르소나). "리뷰해줘", "다시 점검해줘".
- 흐름: 쓰기 → 심사 → 체크리스트 반영 → 재검토를 반복합니다.
