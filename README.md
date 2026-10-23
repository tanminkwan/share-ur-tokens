# Share-Ur-Tokens (SUT)

> **탈중앙화 P2P LLM 토큰 공유 네트워크 (P2P LLM Token Sharing Network)**

개인이 보유한 LLM API 사용 한도(및 로컬 오픈 모델 추론 자원)를 서로 공유하고, 제공한 서비스는 실시간 가치평가를 거쳐 포인트로 돌려받아 다른 모델을 쓰는 데 사용하는 선순환형 무신뢰(Trustless) 분산 플랫폼입니다.

---

## 📚 프로젝트 문서 (Documentation)

- 📌 **[시스템 개요 및 아키텍처](docs/system-overview.md)**: 전체 시스템 비전, 아키텍처, 포인트 순환 구조 및 오픈 에이전트(Cursor 등) 연동
- 🏆 **[해커톤 참가 기획서](docs/hackathon-proposal.md)**: 해커톤 참가용 1~7 문항 기획서 및 2일간의 MVP 구현 계획
- 💎 **[실시간 가치평가 메커니즘](docs/valuation-mechanism.md)**: 제공한 서비스를 모델·토큰 종류·시간대별 수요·공급, 소멸 위험(선불 크레딧 만료·유휴 GPU), 노드 품질로 가치평가해 포인트로 돌려주는 공식
- 🌐 **[P2P 네트워크 및 DID 구조](docs/p2p-and-identity.md)**: libp2p, 상호 은닉(Blind Relay), DID 자급 발급, 분산 브로커 운영 보상
- ⛓️ **[포인트 원장 및 정산](docs/ledger-and-settlement.md)**: 상호신용(공급 +P, 사용 -P, 합계 0) 정산과 Broker 합의형 블록체인 원장
- 🛡️ **[기술 실현 가능성 및 이용 조건 준수 구조](docs/feasibility-and-compliance.md)**: 기술적 타당성 검증, 모든 공급이 공급원의 이용 조건(업체 약관, 모델 라이선스, 조직 정책)을 따르도록 하는 공급 정책 프로파일 구조
- 📊 **[시장 유사 서비스 분석 및 경쟁력](docs/market-analysis-and-competitors.md)**: One-API, Morpheus, Grass 등 기존 서비스 대비 독창적 블루오션 포지셔닝
- 🔒 **[로컬 프라이버시 및 안전한 툴 콜링](docs/privacy-and-tool-calling.md)**: 초경량 로컬 마스킹 파이프라인 및 안전한 금융/상거래 툴 콜링 격리 실행
- 🔄 **[동적 턴 단위 피어 스위칭](docs/dynamic-peer-switching.md)**: 세션 친화(Sticky) 라우팅으로 캐시 효율 확보, 장애 시 무상태 Fallback 및 KV 캐시 전달안 검토 결과
- ⚖️ **[분쟁 해결 및 공급자 보호](docs/dispute-and-indemnity.md)**: 정책 위반 질의의 2중 사전 차단, 서명 증거 기반 Broker 심사, 포인트·신용 한도를 통한 제재와 공급자 보상


