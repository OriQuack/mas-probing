# Current prompts

본문은 역할별 Python multiline 문자열, orchestrator 행동 tool schema는 `schemas.py`에 둡니다.

수정할 때는 기존 역할 소개, 절 구성, 설명 순서, 판단 원칙과 보고 형식을 기본값으로 유지합니다.
실제 입력·도구·출력 계약의 변경이나 구체적인 모호함으로 설명할 수 있는 부분만 바꿉니다.
취향이나 막연한 품질 향상 기대만으로 큰 구성을 다시 쓰지 않습니다. Thinking Before Thinking 분석과
skill은 필요한 수정의 방법을 찾는 데 사용하며, 기존 구성을 대체하는 템플릿으로 사용하지 않습니다.

| 역할 | 모듈 | 입력과 출력 |
|---|---|---|
| Orchestrator | `orchestrator.py` | run 동안 대화 하나: 원 질문·worker(alias·도구·한도)·예산·answer format, 이후 tool 결과로 보고 원문 → tool call `probe` / `execute` / `finish` |
| Probe | `probe.py` | 같은 assignment/context(첫 request는 원 질문 포함) → understanding / plan |
| Worker | `worker.py` | 같은 대화의 새 request: instruction·실제 context(첫 request는 원 질문 포함) → 자유 형식 보고(결과·근거·확인 못 한 것) |
| (미사용) Evaluator | `evaluator.py` | C42부터 runtime에서 쓰지 않는 e7 본문. 참고용으로 남김 |
| Page reader | `reader.py` | 기존 페이지 판독 계약 유지 |

실행은 `v24`, probe는 `r24`입니다. Orchestrator는 보고 원문만 보며 도구 결과 원문은 저장만 합니다.
다른 worker의 보고는 보고 ID(`artifact_ids`)로 골라 context로 전달합니다. 외부 도구는 worker에게만 있습니다.

```bash
python scripts/show_prompts.py --component all
python scripts/show_prompts.py --component orchestrator
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
| state 갱신과 context 행 선택의 시점 | evaluator가 먼저 갱신하고, orchestrator는 갱신된 입력 snapshot에서 행을 선택 |
| refiner가 아는 내용 | probe 평가의 rationale·changes와 최신 state를 받고 지시 표현만 수정 |
| 수정·재탐색이 필요한 때 | 유효한 결과와 충분한 지시는 유지하고, 답에 영향을 줄 빈틈과 새 접근이 있을 때 재검토 |
| 불확실성과 작업 완료의 관계 | 가정·조건부 결과·관측을 구분하며, 수행한 작업의 완료와 답의 확정은 별도로 판단 |

각 prompt는 역할의 작업, 입력의 의미, 판단 기준, 출력 계약을 구분합니다. 같은 기준을 모든 역할에
반복하기보다 각 역할이 내리는 결정과 전달받는 정보에 맞춰 적었습니다. 특정 과제의 이름·정답·검색어는
production prompt에 넣지 않았습니다. 문구 변경이 실제 모델 행동에 미치는 효과는 아직 검증하지 않았습니다.

`v13/r15/e3`는 orchestrator·evaluator·refiner의 도입부에 역할 소개(`You are …`)를 복원하고
수행할 작업을 이어 설명합니다. 나머지 본문과 출력 계약은 동일합니다.


`v14/r16/e4`는 보고와 도구 원문의 조회·근거 참조 계약을 통일합니다. `/tool/N` 주소 대신
저장된 ID를 그대로 사용하도록 입력 설명과 참조 필드 설명만 변경했습니다. 역할 소개·절 구성·판단 원칙은
유지하며, worker/probe 보고 형식과 state의 네 필드도 유지합니다. 과거 checkpoint는 prompt 버전 검사에서
거부하며 변환하지 않습니다. 오프라인 검사는 계약의 동작을 확인할 뿐 실제 모델의 오류 감소를 입증하지 않습니다.


`v15/r17/e5`는 [prompt 검토](../../../docs/reports/2026-10-12-prompt-review.ko.md)의 정보 경계를 보완합니다.
채택할 state에서 바뀌거나 삭제된 이전 행의 선택은 harness가 거부합니다. 도구 기록에는 연결 가능한 호출
이름·인자를 함께 저장하고, reader 답변·이미지·코드 출력의 확인 범위를 구분합니다. Probe 생성 파일과
refiner 조회가 executor에게 자동 전달되지 않음을 설명합니다. 조건부 supported의 의미와 state 정리 기준을
보완하되 역할 소개·절 구성·네 필드 state·전체 승인 방식은 유지합니다. Reader의 자료 부재 설명은 source/part
범위로 한정하며 tools `v7`와 새 cache를 사용합니다. 추가 평가 단계나 호출을 만들지 않습니다.


`r18`은 probe 답변 순서를 `understanding → plan → assumptions → risks`로 바꿉니다.
먼저 접근 계획을 작성하고, 그 계획에서 사용한 가정과 구체적인 실패 가능성을 설명합니다.
Probe에서 본 작업을 실행하지 않는 경계와 빈 assumptions/risks 허용은 유지합니다.
실행 worker의 보고 형식과 evaluator·refiner prompt 본문은 바꾸지 않습니다.


`v16/r19/e6`는 state 갱신을 evaluator의 단독 역할로 정리합니다. 유효한 evaluator 출력은 즉시 저장되고,
orchestrator는 최신 state에서 작업·executor·전달 정보를 선택합니다. `accept_state`, `state_reason`,
`requires_decision`과 승인 전후 행 충돌 검사는 제거했습니다. Refiner의 `can_refine=false`는 초안 유지와
사유 기록으로 끝나며 `refiner_reconsider` 호출은 없습니다. Probe의 understanding → plan → assumptions → risks,
state 네 필드, 기록 ID와 도구 버전 v7은 유지합니다. 위 버전별 설명은 당시 변경 기록입니다.

`v17/r20/e6`는 next_action/select_executor 구분을 제거하고 모든 행동을 같은 판단 루프로 통합한다.
조건은 direct_execution/adaptive_probe이며 evaluator·tools 본문 버전 e6/v7은 유지한다.

`v18/r21/e6`는 유효한 probe 평가 뒤 refiner를 호출한 다음 orchestrator가 행동을 고르게 한다.
Probe 초안과 refiner 원문을 instruction artifact로 보존한다. 같은 작업의 execute는 저장된
`instruction_id`를 선택하며 새 `instruction`과 동시에 쓸 수 없다. Harness는 지시를 그대로 전달한다.
`context_notes`는 context 선택 참고이며 자동으로 붙이지 않는다. Orchestrator의 `refine`·`changes`는
제거하고 evaluator의 `changes`는 유지한다. 직접 실행은 refiner를 호출하지 않는다.

`v19/r22/e6`는 probe의 assumptions에 context·instruction의 미검증 전제도 포함하고, 도구로 확인한
내용은 해당 항목 안에 `observed:`와 출처를 적게 한다. 네 항목과 파서는 유지한다. Probe는 전체 실행을
목표로 하지 않지만 허용된 확인 중 답을 발견하면 근거와 함께 보고한다. Orchestrator는 state가 아직
다루지 않은 원 질문의 부분도 선택할 수 있다. 보고서 선택은 연결 도구 본문의 자동 전달을 뜻하지 않음을
설명하고, 목표 결과·범위가 같은 probe 작업은 저장된 instruction ID로 실행해 기록의 연결을 유지한다.
모델 입력의 `latest_probe`에서 최상위와 중복되는 `instructions`·`evaluation`만 제외하며 trace와
checkpoint의 기존 기록은 유지한다. Evaluator·refiner·reader 본문과 tools v7은 유지한다.

`v20/r23/e7`(C41)은 worker가 run 동안 대화 하나와 workspace 하나를 유지하고 refiner를 없앤다.
Probe는 understanding·plan 두 항목만 묻고, 도구 최대 3회는 plan 단계 확인에 쓴다. Evaluator는 probe 평가에서
plan의 오독·암묵 전제·실패 위험 단계를 찾고, 원 질문이 정한 조건은 가정이 아님을 명시한다. Orchestrator는 probe 뒤
고른 worker 대화의 다음 메시지로 교정과 주의점을 전한다. Worker·probe prompt는 대화와 workspace가 이어진다는 점과
다른 worker의 결과는 context로만 온다는 점을 설명한다. 역할 소개·절 구성·보고 형식·state 네 필드·finish 답 계약은 유지한다.

`v21`은 orchestrator의 probe 설명에 한 문장을 더한다. Probe request가 이미 이해·plan을 물으므로 assignment는 실행용처럼
쓰고 모호함·가정·위험 질문을 덧붙이지 않는다. 나머지 본문은 `v20`과 같다.

`v22/r24`(C42)는 evaluator를 runtime에서 빼고 orchestrator가 run 동안 대화 하나를 유지하게 한다. 행동은 tool call
`probe`·`execute`·`finish`이고, 보고 원문이 보고 ID·worker alias·request 종류·status와 함께 tool 결과로 돌아온다.
Evaluator의 판단 기준 중 orchestrator 결정에 필요한 것을 "Read the reports against the original task"와
"Read the probe responses" 절로 옮겼다. Probe 응답에서 이해의 갈림(지시가 모호함)과 plan의 갈림(유효한 다른 접근인지,
결과를 못 내는 접근인지)을 나눠 보고, 실행 지시는 worker의 이해·plan이 뜻한 바와 다르면 뜻한 바를 밝힌다.
Finish의 답은 항상 answer format의 값 하나이며 해석이 갈리면 원 질문에 가장 잘 맞는 해석을 고른다.
Worker 보고는 자유 형식(`Title:`·4섹션 제거)이고, probe는 `understanding`·`plan` label을 유지하되 understanding을
"무엇을 묻고 어떤 조건이 적용된다고 이해했는지"로 바꾸고 확인 중 드러난 답은 그 단계의 `observed:` 줄에 적게 했다.
세 prompt 전체를 기존 구성·어조를 유지한 채 다듬었다. `REFINER_PROMPTS_VERSION`은 `PROBE_PROMPTS_VERSION`으로 바꿨다.

`v23`은 `probe`·`execute` tool에도 `rationale`을 필수 인자로 둔다. 지금까지 보고가 확인한 것, 남은 것, 이 지시(와 worker)를
고른 이유를 적는다. v22에서는 모델이 tool call과 함께 text를 쓰지 않아 행동 선택 이유가 기록되지 않았다.
같은 `v23`에서 한 메시지에 여러 `probe`·`execute` call을 허용한다. 순서대로 실행되고 각 call에 결과가 돌아오며, 같은 메시지의
execute는 서로의 보고를 보지 않는다. `finish`는 단독 call일 때만 실행한다.
Orchestrator는 실행을 맡길 때 등록된 worker 모두에게 같은 메시지에서 `execute`를 부르도록 권장받는다(독립 수행 후 비교).

`v24`는 orchestrator의 probe 설명에 "call `probe` once per assignment; a single call already reaches every worker"를 더한다.
harness도 한 메시지의 두 번째 probe를 실행하지 않는다.
