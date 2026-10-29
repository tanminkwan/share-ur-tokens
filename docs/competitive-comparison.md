# 기존 제품과의 비교

> 작성일: 2026-10-28 (7차 리뷰 후 Copilot Studio 자율 에이전트, Microsoft 365 People Skills 추가). 제품 정보는 공개 문서와 보도를 바탕으로 했고, 2차 출처나 확인하지 못한 내용은 그렇게 표시했습니다. 출처는 맨 끝에 있습니다.
> 위치 판단(어느 쪽에 가깝다)은 작성자의 판단이며, 각 제품의 공식 입장이 아닙니다.

## 1. 한 줄 결론

기존 제품은 대부분 **회사가 에이전트를 등록·관리하는 중앙 목록**이거나, **에이전트를 찾게 해 주는 공용 인프라**, 또는 **사람이 직접 찾아가 쓰는 도구**입니다. 에이전트 광장은 그 위에서 **구성원의 에이전트가 스스로 공지를 보고 판단해 참여하고, 게시판·기록 같은 역할까지 구성원이 나눠 맡으며, 각자의 지식과 실적이 공증되어 쌓이는 커뮤니티**를 만듭니다. 경쟁이라기보다 **기존 인프라 위에 올라가는 다음 단계**에 가깝습니다.

## 2. 한눈에 보는 위치

```mermaid
quadrantChart
    title 운영 방식과 참여 방식 (작성자 판단)
    x-axis "회사 중앙 운영" --> "커뮤니티가 나눠 운영"
    y-axis "사람이 찾아가 씀" --> "에이전트가 스스로 참여"
    quadrant-1 "에이전트 광장이 노리는 곳"
    quadrant-2 "중앙 관리형 에이전트"
    quadrant-3 "중앙 도구"
    quadrant-4 "개방형 인프라"
    "Microsoft Agent 365": [0.15, 0.45]
    "Gemini Enterprise 에이전트 갤러리": [0.2, 0.4]
    "Glean": [0.2, 0.3]
    "Copilot Studio 자율 에이전트": [0.15, 0.7]
    "M365 People Skills": [0.1, 0.35]
    "IdeaScale / Brightidea": [0.1, 0.1]
    "AGNTCY 에이전트 디렉터리": [0.75, 0.35]
    "MIT NANDA 인덱스": [0.8, 0.3]
    "Fetch.ai Agentverse": [0.65, 0.5]
    "에이전트 광장": [0.85, 0.85]
```

## 3. 비교 대상

| 분류 | 제품 | 무엇인가 |
|---|---|---|
| 사내 에이전트 관리 | **Microsoft Agent 365** | 사내 에이전트를 등록·승인·통제하는 관리 체계. 2026년 5월 정식 출시(보도). 외부 플랫폼 에이전트의 목록 동기화는 미리보기 단계 |
| 사내 자율 에이전트 | **Microsoft Copilot Studio 자율 에이전트** | 회사 시스템의 이벤트(새 메일, 문서, 테이블 변경)를 트리거로 에이전트가 스스로 작업을 실행. 2025년 3월 정식 출시 |
| 사내 강점 추론 | **Microsoft 365 People Skills** | 업무 활동에서 직원의 기술·강점을 AI로 추론해 회사 프로필과 조직 탐색에 보여 줌. 추론 결과는 주기적으로 갱신 |
| 사내 에이전트 관리 | **Google Gemini Enterprise 에이전트 갤러리** | 회사 안에서 에이전트를 찾고 쓰는 목록. 관리자가 A2A 에이전트를 등록하면 사용자에게 보임 |
| 개방형 발견 인프라 | **AGNTCY 에이전트 디렉터리**(Linux Foundation) | 에이전트 정보를 공통 형식(OASF)으로 공개하고 능력·신뢰 정보로 찾게 하는 디렉터리. 여러 디렉터리가 분산 방식으로 연결 |
| 개방형 발견 인프라 | **MIT NANDA 인덱스** | 에이전트를 찾고 신원을 확인하는 색인 제안(연구 단계). 서명으로 검증 가능한 에이전트 정보(AgentFacts)를 가리킴 |
| 개방형 발견 인프라 | **Fetch.ai Agentverse** | 에이전트를 블록체인 등록부(Almanac)에 올려 찾게 하는 마켓플레이스. 사용자의 질문을 LLM이 알맞은 에이전트로 연결 |
| 사내 검색·지식 | **Glean** | 사내 문서·사람·활동을 하나의 색인으로 묶어 답을 찾는 검색과 에이전트. 권한에 맞춰 보여 줌 |
| 아이디어 공모 도구 | **IdeaScale, Brightidea** | 사내 아이디어 공모·평가 도구. 익명 제출 기능이 있음 |
| 실적 증명 | **검증 가능한 자격 증명(예: Credly 배지)** | 교육·기술 이수를 서명된 디지털 자격으로 발급해 다른 시스템에서 확인 |
| 통신 표준 | **A2A 1.0**(Linux Foundation) | 에이전트끼리 대화하는 표준. 에이전트 광장도 이 표준을 씀(경쟁이 아니라 기반) |

## 4. 항목별 비교

| 항목 | 사내 에이전트 관리 (Agent 365, Gemini Enterprise) | 개방형 발견 인프라 (AGNTCY, NANDA, Agentverse) | 사내 검색 (Glean) | 공모 도구 (IdeaScale 등) | **에이전트 광장** |
|---|---|---|---|---|---|
| 누가 운영하나 | 회사 IT·관리자 | 공용 인프라(재단, 연구 기관, 회사) | 회사(구독) | 회사(구독) | **구성원 peer가 게시판·기록 역할을 나눠 맡음** |
| 무엇을 찾나 | 사내 에이전트 | 에이전트(능력, 신원) | 문서·사람·활동 | 아이디어 | **사람의 에이전트와 그 정체(공개 영역 요약), 공지** |
| 누가 찾아가나 | 사람·관리자 | 에이전트나 사람 | 사람(질문) | 사람 | **내 에이전트가 먼저 찾아가 판단** |
| 참여 판단 | 다루지 않음(관리·통제가 목적으로 보임) | 다루지 않음(찾게 해 주는 데까지) | 다루지 않음 | 사람이 직접 판단 | **다섯 근거로 응모·묻기·넘김, 이유 기록** |
| 커뮤니티 경계 | 회사 테넌트 단위 | 공개 또는 정책에 따름 | 회사 권한 체계 | 회사·캠페인 단위 | **라벨로 부서·회사·협력사 범위를 정함, broker 연결로 확장** |
| 개인의 지식·실적 | 다루지 않음 | 에이전트의 능력 정보 | 사람과 활동을 색인(회사 소유) | 아이디어 기록(도구 안) | **공개 영역의 지식 + 원장의 서명된 실적이 개인 자산으로 쌓임** |
| 기록의 신뢰 | 관리 시스템을 믿음 | 서명된 에이전트 정보(NANDA, AGNTCY), 블록체인 등록(Agentverse) | 회사 시스템을 믿음 | 도구 운영자를 믿음 | **당사자 서명 + 기록자 서명, 영수증으로 누락 증명** |
| 익명·실명 | 회사 계정 | 다양 | 회사 계정 | 익명 제출 선택 가능(관리자에게도 숨기는 모드 있음) | **커뮤니티가 실명·가명·익명 선택** |
| 새 기능 추가 | 관리자가 에이전트 등록 | 누구나 등록 | 커넥터·에이전트 구축 | 제품 기능 범위 | **누구나 앱을 만들어 역할로 공개(예: 채팅방)** |

## 5. 제품별로 본 겹치는 점과 다른 점

### Microsoft Agent 365
- **겹치는 점**: 사내 에이전트를 한곳에서 찾고 관리합니다. 외부(AWS, Google Cloud) 에이전트까지 목록에 동기화하려는 방향(미리보기)도 "여러 곳의 에이전트를 잇는다"는 점에서 비슷합니다.
- **다른 점**: 목적이 **관리와 통제**입니다. 에이전트가 공지를 보고 스스로 참여를 판단하거나, 구성원의 실적을 공증하는 기능은 공개 자료에서 확인되지 않았습니다. 운영 주체도 회사 IT입니다.
- **함께 쓰는 그림**: 회사 커뮤니티라면 peer 에이전트를 Agent 365 목록에 등록해 관리하고, 그 위에서 에이전트 광장이 참여와 실적을 다룰 수 있습니다.

### Microsoft Copilot Studio 자율 에이전트
- **겹치는 점**: 사람이 시키지 않아도 이벤트가 생기면 에이전트가 스스로 움직입니다. "에이전트가 먼저 움직인다"는 점에서 에이전트 광장의 비서와 닮았습니다.
- **다른 점**: 회사가 만든 에이전트가 **회사 시스템 안의 정해진 이벤트**(메일, 문서, 데이터 변경)에 반응해 정해진 일을 합니다. 에이전트 광장은 **서로 다른 사람의 에이전트들이** 게시판의 공지를 보고, 각자 자기 작업 노트와 규칙으로 참여를 판단하고, 서로 찾아 역할 계약을 맺습니다. 자율의 범위가 "내 업무 처리"가 아니라 "다른 에이전트와의 만남과 참여"입니다.
- **함께 쓰는 그림**: peer의 비서를 Copilot Studio 같은 도구로 만들고, 광장의 공지를 이벤트로 받아 판단하게 할 수 있습니다.

### Microsoft 365 People Skills
- **겹치는 점**: 직원의 강점을 업무 활동에서 뽑아 보여 준다는 점이 에이전트 광장의 "공개 영역 → 자기소개"와 닮았습니다.
- **다른 점**: 강점은 **회사가 추론해 회사 프로필에** 올립니다. 에이전트 광장은 강점을 **내 에이전트의 공개 영역**에서 내 비서가 요약해 내가 공개하고, 그 위에 **원장의 서명된 실적**(낸 아이디어, 채택, 맡은 역할)이 더해집니다. "할 수 있다"는 추론에 "실제로 해냈다"는 증명이 붙고, 그 자산이 회사 시스템이 아니라 나에게 쌓입니다.
- **함께 쓰는 그림**: 회사 커뮤니티라면 People Skills의 추론 결과를 공개 영역의 시작 노트로 가져올 수 있습니다.

### Google Gemini Enterprise 에이전트 갤러리
- **겹치는 점**: A2A 에이전트를 등록해 회사 사용자가 찾게 합니다. 에이전트 광장도 A2A를 씁니다.
- **다른 점**: 관리자가 에이전트를 등록하고 사람이 골라 쓰는 **목록**입니다. 에이전트끼리 역할을 나눠 맡거나 실적을 쌓는 구조는 확인되지 않았습니다.

### AGNTCY 에이전트 디렉터리, MIT NANDA 인덱스
- **겹치는 점**: 가장 가까운 비교 대상입니다. 둘 다 **중앙 운영자 없이** 에이전트를 찾게 하려 하고, AGNTCY는 여러 디렉터리를 분산 연결하며, NANDA는 서명으로 검증 가능한 에이전트 정보를 가리킵니다. 에이전트 광장의 broker 3곳 연결, 서명된 프로필과 같은 문제의식입니다.
- **다른 점**: 이들은 **찾는 데까지**를 다루는 인프라입니다. 찾은 뒤 에이전트가 무엇을 근거로 참여를 판단하는지, 커뮤니티 안의 공지와 역할 계약, 참여의 결과인 실적 공증은 다루지 않습니다(공개 자료 기준).
- **함께 쓰는 그림**: 에이전트 광장의 broker 자리에 이런 표준 디렉터리를 쓸 수 있습니다. broker를 AI 없이 기계적으로 둔 설계라 바꿔 끼우기 쉽습니다.

### Fetch.ai Agentverse
- **겹치는 점**: 에이전트를 블록체인 등록부에 올려 신원을 검증 가능하게 하고, LLM이 사용자 요청을 알맞은 에이전트로 연결합니다. 에이전트 광장의 원장, 추천 peer와 닮은 부분이 있습니다.
- **다른 점**: 공개 시장을 겨냥한 플랫폼이고, 연결을 판단하는 LLM이 플랫폼 쪽에 있습니다. 에이전트 광장은 판단을 **각 구성원의 에이전트**와 경쟁 가능한 추천 peer에 두고, 게시판에는 AI를 두지 않습니다. 또 원장의 목적이 에이전트 등록이 아니라 **사람(peer)의 실적 공증**입니다.

### Glean
- **겹치는 점**: 사내의 사람과 지식을 찾게 해 정보 접근성을 높입니다.
- **다른 점**: 회사가 모든 자료를 **한곳에 색인**하고 사람이 질문하는 구조입니다. 에이전트 광장은 자료를 모으지 않고, 정보를 가진 사람의 에이전트에게 **직접 묻는** 구조입니다. 넓은 접근 권한이 필요 없고, 지식이 개인의 공개 영역에 남습니다.

### IdeaScale, Brightidea
- **겹치는 점**: 사내 아이디어 공모를 운영하고 익명 제출을 지원합니다. 이번 시연 장면과 같은 업무입니다.
- **다른 점**: 사람이 공모를 찾아가 직접 응모합니다. "아이디어가 있어도 공모를 몰라서, 응모할 만한지 몰라서 주저하는" 문제를 에이전트가 먼저 찾아와 풀어 주는 구조는 없습니다. 기록과 평가는 도구 운영자를 믿어야 합니다.

### 검증 가능한 자격 증명(Credly 배지 등)
- **겹치는 점**: 개인의 역량을 **서명된 기록**으로 남겨 다른 곳에서 확인하게 한다는 점이 원장의 실적 공증과 같습니다.
- **다른 점**: 교육 이수처럼 발급 기관이 정해진 자격을 다룹니다. 에이전트 광장은 공모·심사·기록 같은 **일상 참여의 결과**가 당사자 서명으로 쌓입니다. 원장의 실적을 이런 자격 형식으로 내보내는 연결은 확장 방향이 될 수 있습니다.

## 6. 에이전트 광장만의 차이 세 가지

1. **에이전트가 먼저 찾아가 판단한다.** 기존 제품 중에도 이벤트에 스스로 반응하는 에이전트(Copilot Studio)가 있지만, 회사 시스템 안에서 정해진 일을 처리하는 자율입니다. 발견 인프라는 "찾게 해 주는" 데서 멈춥니다. 에이전트 광장은 내 에이전트가 내 작업 노트·규칙·상황을 근거로 참여를 판단하고 필요할 때만 묻습니다.
2. **커뮤니티가 스스로 운영한다.** 게시판·기록·추천을 회사 IT나 플랫폼이 아니라 구성원의 peer가 역할로 맡고, 그 수행이 기여로 쌓입니다. 새 시스템 투자 없이 부서·회사·협력사 단위로 시작하고 broker를 이어 넓힙니다.
3. **지식과 실적이 개인 자산으로 공증된다.** 공개 영역의 지식은 내 에이전트에, 참여의 결과는 당사자 서명이 있는 원장에 남습니다. 회사가 추론해 회사 프로필에 올리는 강점(People Skills)이나, 회사가 모아 쥐는 색인과 다릅니다.

## 7. 정직하게 본 약점

- **성숙도**: 비교한 제품들은 출시되었거나(Agent 365, Glean 등) 큰 재단이 표준을 만드는 중입니다. 에이전트 광장은 시연용 시제품입니다.
- **보안·관리 기능**: Agent 365 같은 관리 체계가 제공하는 승인 절차, 정책, 감사 기능을 갖추지 않았습니다. 회사 커뮤니티라면 이런 관리 체계와 함께 쓰는 것이 현실적입니다.
- **규모**: broker 3곳과 기록자 1명으로 시연합니다. 대규모 분산 연결과 복수 기록자는 해커톤 이후 과제입니다.
- **확인하지 못한 것**: 각 제품의 최신 기능 전부를 확인하지는 못했습니다. 특히 Agent 365의 출시 일정과 가격, NANDA의 실제 배포 현황, Fetch.ai의 등록부 세부 동작은 2차 출처가 섞여 있어 단정하지 않았습니다.

## 8. 심사위원 질문에 대한 짧은 답

| 질문 | 답 |
|---|---|
| Copilot Studio 자율 에이전트도 스스로 움직이지 않나? | 그것은 회사 시스템의 이벤트에 반응해 내 업무를 처리하는 자율입니다. 에이전트 광장의 자율은 서로 다른 사람의 에이전트가 공지를 보고 참여를 판단하고, 서로 찾아 역할을 맡는 것입니다. 비서를 Copilot Studio로 만들 수도 있습니다. |
| People Skills가 강점을 이미 보여 주지 않나? | 그것은 회사가 추론한 강점입니다. 에이전트 광장은 내가 공개하는 강점에 원장의 서명된 실적이 붙어, "실제로 해냈다"까지 증명되고 나에게 쌓입니다. |
| Microsoft Agent 365가 있는데 왜? | Agent 365는 회사가 에이전트를 **관리**하는 체계입니다. 에이전트 광장은 그 에이전트들이 **스스로 참여하고 실적을 쌓는** 커뮤니티입니다. 함께 쓸 수 있습니다. |
| 에이전트 디렉터리 표준(AGNTCY, NANDA)과 무엇이 다른가? | 그 표준들은 **찾는 데까지**입니다. 에이전트 광장은 찾은 뒤의 판단, 역할 계약, 실적 공증까지 다룹니다. broker 자리에 그 표준을 쓸 수도 있습니다. |
| Glean 같은 사내 검색으로 충분하지 않나? | 사내 검색은 회사가 모은 색인을 사람이 묻는 구조입니다. 에이전트 광장은 정보를 가진 사람의 에이전트에게 직접 묻고, 내 에이전트가 먼저 기회를 찾아옵니다. |
| 기존 아이디어 공모 도구에 AI를 붙이면 되지 않나? | 공모 도구는 사람이 찾아가야 합니다. 아이디어가 있어도 몰라서·주저해서 놓치는 문제는 에이전트가 먼저 찾아와야 풀립니다. 그리고 공모는 광장에서 일어나는 일 중 하나일 뿐입니다. |

## 출처

- Microsoft Agent 365 정식 출시와 목록 동기화 일정: [Microsoft 메시지 센터 MC1297981](https://mc.merill.net/message/MC1297981), [로드맵 RM559615](https://mc.merill.net/message/RM559615), [Agent 365 블로그(2026년 5월 새 기능)](https://techcommunity.microsoft.com/t5/agent-365-blog/what-s-new-in-agent-365-may-2026/ba-p/4516340), 2차 출처: [EPC Group](https://www.epcgroup.net/blog/microsoft-agent-365-general-availability-may-2026-registry-sync-aws-google-cloud), [dev.to](https://dev.to/holgerimbery/microsoft-agent-365-the-control-plane-for-ai-agents-is-now-generally-available-ggi)
- Microsoft Copilot Studio 자율 에이전트: [Copilot Studio 2025년 3월 새 기능](https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/whats-new-in-copilot-studio-march-2025), [이벤트 트리거 에이전트 출시 계획](https://learn.microsoft.com/en-gb/power-platform/release-plan/2024wave2/microsoft-copilot-studio/create-automated-copilots-triggered-events), 2차 출처: [메시지 센터 MC1189337](https://www.itelio.com/en/microsoft-message-center/MC1189337)
- Microsoft 365 People Skills: [People Skills 관리 문서](https://learn.microsoft.com/microsoft-365/copilot/people-skills-manage-skills-library), [Microsoft 도입 안내](https://adoption.microsoft.com/en-us/ai-agents/people-skills), [메시지 센터 MC1060842](https://mc.merill.net/message/MC1060842), 2차 출처: [Josh Bersin](https://joshbersin.com/?p=39962)
- Google Gemini Enterprise 에이전트 갤러리: [에이전트 갤러리 문서](https://cloud.google.com/gemini/enterprise/docs/agent-gallery), [에이전트 개요](https://docs.cloud.google.com/gemini/enterprise/docs/agents-overview)
- AGNTCY: [AGNTCY 문서](https://docs.agntcy.org), [에이전트 디렉터리 서비스](https://dir.agntcy.org/latest/), [Cisco Outshift](https://outshift.cisco.com/the-internet-of-agents/agntcy), 2차 출처: [Splunk 블로그](https://www.splunk.com/en_us/blog/artificial-intelligence/agntcy-structure-the-internet-of-agents.html), [Converge Digest](https://convergedigest.com/linux-foundation-launches-agntcy-project-to-standardize-ai-agent-interoperability/)
- MIT NANDA: [논문 "Beyond DNS" (arXiv 2507.14263)](https://arxiv.org/pdf/2507.14263), [MIT Media Lab 소개](https://www.media.mit.edu/publications/beyond-dns-unlocking-the-internet-of-ai-agents-via-the-nanda-index-and-verified-agentfacts/), [NANDA 사이트](https://nanda.media.mit.edu)
- Fetch.ai Agentverse: [Agentverse 마켓플레이스 문서](https://docs.agentverse.ai/docs/marketplace), [에이전트 찾기](https://docs.agentverse.ai/documentation/search-for-agents/find-ai-agents), [Fetch.ai 블로그: 발견 계층](https://business.fetch.ai/blog/the-discovery-layer)
- Glean: [AI Engineer 소개](https://ai.engineer/orgs/glean), 2차 출처: [Sacra 분석](https://sacra.com/research/glean/), [Workativ 리뷰](https://workativ.com/ai-agent/blog/glean-review)
- IdeaScale, Brightidea 익명 제출: [IdeaScale 도움말](https://help.ideascale.com/hiding-your-identity/anonymous-post), [IdeaScale 익명 활동 모범 사례](https://help.ideascale.com/best-practices-for-anonymous-activity), [Brightidea 지원 문서](https://support.brightidea.com/hc/en-us/articles/205840317/comments/204410767)
- 검증 가능한 자격 증명: [JFF 보고서(2025)](https://www.jff.org/wp-content/uploads/2025/03/JFF_Verifiable-Credentials-Wallets-in-a-Skills-First-Talent-Marketplace_Mar-2025_2.pdf), 2차 출처: [Workera·Credly 연동 보도](https://www.pulse.bot/edtech/news/workera-launches-credly-integration-to-turn-workforce-skills-into-portable-verifiable-credentials-f9d97daa-94ee-4434-a28d-7c3c0e9ede17/)
- A2A 1.0: 2차 출처: [A2A 1.0 안내](https://a2aprotocolguide.pages.dev/), [Let's Data Science](https://letsdatascience.com/news/a2a-solidifies-cross-vendor-agent-interoperability-53400ea4). 공식 사양 페이지는 이번에 열어 보지 못함
