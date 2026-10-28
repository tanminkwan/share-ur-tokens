# (가칭) 사내 지식 장터: 가명으로 나누고 증명으로 남기는 p2p + a2a 지식 네트워크

> 사내 AI 해커톤(2일) 기획 문서. 이름은 임시입니다.
> 이전 아이디어(SUT, LLM 토큰 공유)는 `checkpoint-20261023-v2` 브랜치에 보존되어 있습니다.

## 한 줄 요약

임직원의 에이전트가 **가명**으로 지식을 주고받고(p2p + a2a), 그 거래·공유가 **서명된 변조 탐지 원장**에 증명으로 남아 선등록자는 보호되고 지식은 사내 자산으로 쌓이는 네트워크.

## 해결하려는 문제

1. 지식을 나눌 이유도 안전도 없다. 기여가 남지 않고, 묻는 쪽도 부담스럽다.
2. 누가 무엇을 아는지 모른다.
3. 공유된 지식이 회사 자산으로 남지 않고, 누가 누구 지식을 참고했는지 추적되지 않는다.

## 구조

```
 제공자 peer ─발행: 원문→지식 저장소 / 해시+서명→수집가 / 요약→broker
 소비자 peer ─요청──▶ broker(발견만) ─답변지(공급자 주소)─▶ 소비자
 소비자 ══ p2p + a2a 조건 협상·전달(broker 미경유) ══ 제공자
 양쪽이 서명한 영수증 ──▶ 수집가 ×2 (독립 검증·기록, 해시 체인 원장)
 파생 지식(부모 해시) ──▶ 출처 그래프 · 기여 집계
```

- **broker**: 발견만 한다. 거래 내용을 보지 않는다.
- **수집가**: 발행·거래·파생을 검증해 원장에 기록한다. 내용이 아니라 해시·가명·서명만 담는다.
- **검증 상태**: A2A 직접 통신과 원장 논리(이중 서명, 변조 탐지, 기여 집계)는 `proto/`의 spike로 실행 확인했다.

## 문서 구성

| 문서 | 내용 |
|---|---|
| [docs/system-overview.md](docs/system-overview.md) | **기술 설계**: 구성, 원장, 흐름, 스택, 검증 현황 |
| [docs/broker-and-discovery.md](docs/broker-and-discovery.md) | broker의 맥락 기반 DB화, 검색, broker 간 질의 |
| [docs/a2a-transaction.md](docs/a2a-transaction.md) | p2p 연결과 a2a 이용 조건 협상 |
| [docs/trust-and-security.md](docs/trust-and-security.md) | 가명·재식별, 원장의 보장 한계, 사내 보안 |
| [proto/](proto/) | 실행 확인용 spike (`spike_a2a.py`, `spike_ledger.py`) |
| [docs/hackathon-proposal.md](docs/hackathon-proposal.md) | **제출용 신청서** (주최 측 7개 문항) |
| [docs/proposal-notes.md](docs/proposal-notes.md) | 내부 메모: 가정, 예상 질문, 미해결 과제, 일정 |
| [review/premises.md](review/premises.md) | 합의된 전제와 용어. `[가정]`은 확인 필요 |
| [review/review-checklist.md](review/review-checklist.md) | 리뷰 지적과 반영 상태 |

## 작업 방법

- 쓰기: `proposal-writer` 스킬(아이디어 기획자 페르소나). "신청서 다듬어줘", "리뷰 반영해서 고쳐줘".
- 심사: `proposal-reviewer` 스킬(사업·기술·보안 3개 시선의 심사위원 페르소나). "리뷰해줘", "다시 점검해줘".
- 흐름: 쓰기 → 심사 → 체크리스트 반영 → 재검토를 반복합니다.
