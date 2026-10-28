# SUT 로컬 프라이버시 보호 및 안전한 툴 콜링 (Privacy & Safe Tool Calling)

> **로컬 초경량 마스킹 파이프라인과 금융/상거래 툴 콜링(Tool Calling)의 안전한 로컬 격리 실행 메커니즘**

---

## 1. 프라이버시 보호 핵심 원칙: "로컬 경비견과 원격 슈퍼두뇌"

복잡한 코딩과 고난도 추론은 원격 Peer의 거대 LLM(OpenAI, Anthropic 등의 상용 API 모델)을 빌려 쓰지만, **민감 정보 감지 및 마스킹은 사용자 로컬 PC의 50MB 초경량 엔진(경비견)이 전담**합니다.

```mermaid
flowchart LR
    subgraph Local_Device["사용자 로컬 PC (경비견)"]
        User["사용자 입력"] --> Presidio["초경량 마스킹 엔진 (50MB)\n- 정규식 + MS Presidio/SpaCy\n- 0.01초 소요, RAM 100MB 미만"]
        Presidio --> Masked["마스킹된 텍스트\n([MASKED_KEY], [MASKED_ACC])"]
    end

    subgraph P2P_Network["SUT P2P 네트워크 (스니핑 무력화)"]
        Masked --> Peer["공급자 Peer\n(가짜 플레이스홀더만 보임 🛡️)"]
    end

    subgraph Remote_LLM["원격 AI 인프라 (슈퍼두뇌)"]
        Peer --> OpenAI["상용 LLM API (OpenAI / Anthropic)\n(대규모 모델의 추론력)"]
    end
```

---

## 2. 왜 로컬에 똑똑한 거대 LLM이 필요 없는가?

"생성(Generation)"과 "감지(Detection)"의 연산량 차이 때문입니다.

| 구분 | 로컬 SUT Agent (마스킹 경비견) | 원격 공급자 Peer (AI 슈퍼두뇌) |
| :--- | :--- | :--- |
| **수행 작업** | 이미 쓰여진 텍스트에서 민감 정보 밑줄 긋기 | 논리 추론, 코드 생성, 심층 분석 창작 |
| **필요 모델 크기** | **50MB ~ 100MB (규칙 + 초경량 NER)** | **대규모 (상용 모델은 크기 비공개, 데이터센터 GPU에서 서빙)** |
| **요구 하드웨어** | 일반 사무용 노트북 CPU (RAM 100MB) | 수천만 원대 데이터센터 GPU |
| **소요 시간** | **0.01초 미만 (체감 불가)** | 수 초 단위 스트리밍 |

### 현업 표준 3단계 초경량 마스킹 스택
1. **1단계: 규칙 및 체크섬 알고리즘 (0.001초, RAM 1MB)**:
   - **API Key**: `sk-[a-zA-Z0-9]{48}`, `ghp_...` (정규식 1줄로 100% 탐지)
   - **주민번호, 전화번호, 이메일, 신용카드 번호**: 자릿수 및 룬(Luhn) 알고리즘으로 검증 탐지
2. **2단계: 초경량 자연어 NER 엔진 (0.01초, RAM 50~100MB)**:
   - **Microsoft Presidio + SpaCy**: 마이크로소프트의 오픈소스 표준 도구. 거대 모델 없이도 문맥 속 인명, 회사명, 주소를 정확히 라벨링.
3. **3단계: (선택) 초소형 SLM (RAM 300MB)**:
   - 더 정교한 문맥 마스킹이 필요할 경우 `SmolLM2-135M` 또는 `Qwen2.5-0.5B`를 로컬 백그라운드 구동.

---

## 3. 사전 마스킹 & 사후 역마스킹 (Pre-Masking & Post-De-masking)

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자 (Cursor / IDE)
    participant CA as 소비자 SUT Agent (로컬)
    participant PA as 공급자 Peer (원격)
    participant LLM as OpenAI 엔드포인트

    User->>CA: 1. 원본 요청 ("sk-live-1234 키로 결제 모듈 짜줘")
    Note over CA: 2. [사전 마스킹 (Pre-masking)]<br/>sk-live-1234 ➔ [MASKED_KEY_1]<br/>(원본 매핑 테이블은 로컬 메모리에만 보관!)
    CA->>PA: 3. 마스킹된 텍스트 전송 ("[MASKED_KEY_1]로 결제 모듈 짜줘")
    Note over PA: 공급자가 트래픽을 스니핑해도<br/>가짜 플레이스홀더만 보이므로 유출 불가! 🛡️
    PA->>LLM: 4. OpenAI 호출
    LLM-->>PA: 5. 코드 응답 반환 ("apiKey = [MASKED_KEY_1]")
    PA-->>CA: 6. 응답 전달
    Note over CA: 7. [사후 역마스킹 (Post-de-masking)]<br/>[MASKED_KEY_1] ➔ sk-live-1234 로컬 복원
    CA-->>User: 8. 최종 복원된 코드 수신 ("apiKey = sk-live-1234")
```

---

## 4. 은행 및 상거래 툴 콜링(Tool Calling)의 안전성

> **핵심 원리: "LLM은 실행하지 않고, 판단(JSON 생성)만 한다."**

LLM이나 중간 공급자 Peer는 사용자의 은행이나 쇼핑몰에 직접 접속할 권한도 없고, 기술적으로 접속할 수도 없습니다.

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant CA as 소비자 SUT Agent (로컬)
    participant PA as 공급자 Peer (중계자)
    participant LLM as OpenAI
    participant Bank as 은행 API 서버

    User->>CA: "내 계좌(110-1234)에서 5만원 송금해줘"
    Note over CA: 로컬 마스킹: 110-1234 ➔ [MASKED_ACC_1]
    CA->>PA: "[MASKED_ACC_1]에서 5만원 송금하는 Tool 호출해줘"
    PA->>LLM: 프롬프트 전달
    
    Note over LLM: 판단(텍스트 생성)만 수행:<br/>{"tool": "transfer", "account": "[MASKED_ACC_1]", "amount": 50000}
    
    LLM-->>PA: Tool Call JSON 반환
    PA-->>CA: Tool Call JSON 전달 (공급자는 은행 접속 불가)
    
    Note over CA: [100% 로컬 격리 실행]<br/>1. [MASKED_ACC_1] ➔ 110-1234 복원<br/>2. 내 PC 안의 공인인증서/OTP 사용!
    
    CA->>Bank: 사용자 PC에서 은행으로 직접 HTTPS 호출
    Bank-->>CA: "송금 성공 (잔액: 45만원)"
    CA-->>User: "5만원 송금이 완료되었습니다."
```

### 공급자 Peer에게 절대 전달되지 않는 정보
1. **금융 인증서 및 비밀번호**: 공인인증서, OTP, 결제 토큰은 공급자 PC를 전혀 거치지 않고 사용자 PC에만 존재.
2. **실제 계좌번호 및 주민번호**: 네트워크 구간에서는 `[MASKED_ACC_1]` 같은 가짜 토큰으로 마스킹되어 전송.
3. **최종 금융 트랜잭션 결과 원문**: 은행 서버와 사용자 PC 간의 직접 암호화 통신으로 격리 보호.

---

## 5. 결론

SUT 플랫폼을 통해 다른 Peer가 공유한 토큰을 쓰더라도:
- **추론(머리)**만 원격 Peer의 상용 LLM을 빌려 쓰는 것이며,
- **보안 검문(마스킹)과 실제 금융 실행(손발)**은 **사용자의 로컬 PC 내부에서 100% 프라이빗하게 격리 완결**되므로 민감 정보 유출 위험이 원천 차단됩니다.
