# Current prompts

본문은 역할별 Python multiline 문자열, JSON 응답 계약은 `schemas.py`에 둡니다.

수정할 때는 기존 역할 소개, 절 구성, 설명 순서, 판단 원칙과 보고 형식을 기본값으로 유지합니다.
실제 입력·도구·출력 계약의 변경이나 구체적인 모호함으로 설명할 수 있는 부분만 바꿉니다.
취향이나 막연한 품질 향상 기대만으로 큰 구성을 다시 쓰지 않습니다. Thinking Before Thinking 분석과
skill은 필요한 수정의 방법을 찾는 데 사용하며, 기존 구성을 대체하는 템플릿으로 사용하지 않습니다.

| 역할 | 모듈 | 입력과 출력 |
|---|---|---|
| Orchestrator | `orchestrator.py` | 원 질문·현재 state·목록·평가·worker capability·예산 → 작업/context 선택, probe 후 executor 선택, 최종 답 |
| Probe | `probe.py` | 원 질문·같은 초안/context → Title, understanding / assumptions / risks / plan |
| Evaluator | `evaluator.py` | probe 또는 실행의 새 보고 전문·실제 instruction/context·종료 상태 → 전체 state 제안·이유·필요 변경 |
| Refiner | `refiner.py` | 원 질문·승인 초안·executor·context·관련 state·승인 변경 → 지시 표현 또는 reconsider |
| Worker | `worker.py` | 원 질문·최종 instruction·실제 context → Title, Result / Evidence / Interpretation / Unfinished |
| Page reader | `reader.py` | 기존 페이지 판독 계약 유지 |

실행은 `v13`, probe/refiner는 `r15`, evaluator는 `e3`입니다. Controller는 JSON `read_memory`를 판단당
최대 3라운드 사용합니다. 보고 ID로 본문을 읽고 `artifact_id/tool/N`으로 연결된 도구 원문을 읽습니다.
외부 도구는 worker에게만 있습니다. Refiner는 probe 수집·analysis·verification을 수행하지 않습니다.
새 판단이 필요하면 반복 검토 없이 orchestrator로 돌려보냅니다.

```bash
python scripts/show_prompts.py --component all
python scripts/show_prompts.py --component evaluator
```

규칙과 실행 데이터는 system/user 메시지로 나눕니다. 원 질문 범위, 관측/가정/조건부 결과, 집계 기준,
탐색 실패·다음 단서를 보존하도록 합니다. ArXiv의 과도한 역사적 증명 요구, Secret Santa의 답 보류,
USDA의 포함 기준 변경, Freud의 반복 탐색을 오프라인 walkthrough로 확인합니다. 이 검사는 실제 모델
행동이나 성능 개선의 증거가 아닙니다. 과거 prompt는 당시 실험 snapshot을 사용합니다.

## 문구를 정리한 기준

`v12/r14/e2`는 역할·호출 순서·JSON 스키마를 유지하면서 입력 설명과 판단 기준을 풀어 쓴 버전입니다.
[작성 분석](../../../docs/thinking-before-thinking-prompt-writing.ko.md),
[engineering 분석](../../../docs/thinking-before-thinking-prompt-engineering.ko.md),
[연구 분석](../../../docs/thinking-before-thinking-analysis.ko.md)과 저장된
`agent-prompt-engineering` skill을 다시 검토했습니다. 논문의 문구나 제어 구조를 복제하지 않고,
실제 입력과 출력 소비자가 요구하는 내용을 기준으로 다음 모호함을 해소했습니다.

| 모호했던 부분 | 현재 설명 |
|---|---|
| 목록에 보이는 제목과 실제 근거의 차이 | 제목은 조회 대상을 고르는 단서이며, 본문과 도구 원문은 필요할 때 읽음 |
| state 갱신과 context 행 선택의 시점 | 전체 목록을 채택하거나 거부하며, 행 번호는 채택 전 입력 snapshot에서 해석 |
| refiner가 아는 내용 | 평가 전문을 받지 않으므로 orchestrator의 `changes`에 승인 변경과 이유를 담음 |
| 수정·재탐색이 필요한 때 | 유효한 결과와 충분한 지시는 유지하고, 답에 영향을 줄 빈틈과 새 접근이 있을 때 재검토 |
| 불확실성과 작업 완료의 관계 | 가정·조건부 결과·관측을 구분하며, 수행한 작업의 완료와 답의 확정은 별도로 판단 |

각 prompt는 역할의 작업, 입력의 의미, 판단 기준, 출력 계약을 구분합니다. 같은 기준을 모든 역할에
반복하기보다 각 역할이 내리는 결정과 전달받는 정보에 맞춰 적었습니다. 특정 과제의 이름·정답·검색어는
production prompt에 넣지 않았습니다. 문구 변경이 실제 모델 행동에 미치는 효과는 아직 검증하지 않았습니다.

`v13/r15/e3`는 orchestrator·evaluator·refiner의 도입부에 역할 소개(`You are …`)를 복원하고
수행할 작업을 이어 설명합니다. 나머지 본문과 출력 계약은 동일합니다.
