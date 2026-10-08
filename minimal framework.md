# Minimal Orchestrator–Worker Framework

- **기본 구조**
  - 단일 orchestrator가 전체 문제를 subtask로 나누고, 도구를 사용하는 worker들에게 위임한다.
  - AOrchestra의 구조를 참고하되, worker의 모델·system prompt·도구는 미리 등록된 설정으로 관리한다.

- **1. 호출 interface와 방법의 경계**

  ```python
  call_worker(
      worker_id: str,
      original_task: str,
      instruction: str,
  ) -> report: str
  ```

  - **`worker_id`:** 호출할 worker의 식별자.
  - **`original_task`:** 시스템이 해결할 최상위 과제의 전체 문제·요청문.
    - 예: “첨부 CSV에서 2025년 고유 주문 수와 월별 매출을 보고하라.”
    - 모든 worker 호출에 동일하게 전달하며, 전체 목적의 기준점으로 고정한다.
  - **`instruction`:** 이번 worker에게 요청하는 작업.
    - **Probe:** 검토할 subtask 지시 + 질문.
    - **본 실행:** 수정된 subtask 지시.
  - **`report`:** Probe 응답 또는 실행 결과·실패 이유. 생성한 파일이 있으면 경로를 포함한다.
  - **방법 모듈: `InstructionRefiner`**
    - **입력:** 원 task, 초안 instruction, 실행 대상 worker, probe에 참여할 worker들.
    - **내부:** Probe → 응답 대조 → 쟁점 판단·확인 → Instruction 수정.
    - **출력:** 수정된 instruction.
    - Subtask 분해·배정과 최종 결과 종합은 harness가 담당한다. 이식·비교하는 개입 단위는 이 모듈이다.

- **2. Probe 질문**
  - 질문은 **현재 subtask**를 기준으로 답하게 한다.
  - **문제 이해:** 무엇을 해야 하는 문제로 이해했는가?
    - 범위, 대상, 방향 차이를 확인한다.
  - **중요 가정:** 무엇을 가정했으며, 그 가정이 달라지면 무엇이 바뀌는가?
    - 결과를 바꿀 수 있는 미정 조건이나 잘못된 전제를 확인한다.
  - **실패 조건:** 작업을 진행하면서 무엇이 실패할 수 있으며, 어떻게 대응할 것인가?
    - 실행 중 발생할 위험과 대응이 빠진 부분을 확인한다.
  - **실행 계획:** 이 subtask 전체를 어떤 단계와 방법으로 수행할 계획인가?
    - Subtask 내부의 접근 방식, 단계 누락, 단계 간 의존 관계를 확인한다.

- **3. 실행 instruction**
  - **정의**
    - 원 task에 더하는 **현재 subtask의 실행 지시**. 담당 범위와 해석·가정·수행 조건·완료 기준을 구체화한다.
  - **예시 — 주문 수 집계 담당 worker**

    ```text
    이번 작업: 첨부 CSV에서 2025년의 고유 주문 수를 집계하라.
    집계 기준: 동일 주문 ID의 여러 상품 행은 주문 한 건으로 계산하라.
    확인 사항: 날짜 열의 시간대 기준과 주문 ID 누락 여부를 확인하라.
    반환 내용: 집계값, 적용한 날짜 기준, 중복·누락 처리 내용을 보고하라.
    ```

  - **Probe 결과 반영**
    - 판단·확인한 쟁점을 적용 기준이나 확인 절차로 바꿔 instruction에 반영한다.
    - Probe transcript 전체를 실행 worker에게 자동으로 넘기지 않는다. 원 task와 기존 자료의 제공 방식은 유지한다.

- **4. Worker 구성과 실행 조건**
  - **Worker pool — 두 구성을 모두 시험**
    - **역할별 routing:** Subtask의 담당 worker에게 반복·변형 probe를 수행한다.
    - **중복 후보:** 같은 subtask를 수행할 수 있는 여러 worker의 응답을 대조한다.
    - 복수 worker를 쓰는 조건에서도 실행 worker를 고정할 수 있다. Worker 선택까지 시험하면 instruction 개선 효과와 구분한다.
  - **쟁점 확인**
    - Orchestrator는 원 task와 worker 응답을 근거로 판단한다.
    - **환경 도구에 직접 접근하지 않는다.** 검색·파일 읽기·코드 실행 등 필요한 확인은 worker에게 위임한다.
    - 사용자에게 추가 질문하는 escalation은 우선 제외한다.
  - **Runtime**
    - 자료 접근, 호출별 예산·오류 처리, 모든 모델·도구 호출 비용을 관리한다.
    - Probe와 본 실행의 대화는 기본적으로 분리하되, 연결하는 조건도 시험한다.
    - Probe 중 도구 허용 여부와 질문 수는 실험 조건으로 관리한다. 파일·환경 상태는 대화 초기화와 별도로 관리한다.