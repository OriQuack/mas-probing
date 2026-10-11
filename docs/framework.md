# Minimal orchestrator–worker framework

## 목적과 경계

단일 orchestrator가 원 문제를 보고 subtask를 위임하고 결과를 종합합니다. Worker의 모델·system prompt·도구는
미리 등록합니다. 연구 개입은 **위임 직전 instruction 검토와 수정**을 담당하는 `InstructionRefiner`입니다.
Task 분해·배정·최종 답은 orchestrator, 실행과 상태 관리는 harness가 담당합니다.

## 실행 흐름

```text
orchestrator: delegate(context, instruction)
  → 위임 직전 checkpoint
  → InstructionRefiner (또는 baseline)
      probe/예측 응답 → analysis → 필요한 사전 확인 → rewrite
  → worker 실행
  → 보고를 orchestrator에 전달
  → 다음 위임 또는 finish
```

Orchestrator는 도구에 직접 접근하지 않습니다. 검색·파일 읽기·계산·쟁점 확인은 worker에게 맡깁니다.
사용자에게 추가 질문하는 escalation은 구현 범위에서 제외합니다.

## Worker 호출

```python
call_worker(worker_id, original_task, instruction, context="") -> report
```

- `worker_id`: 등록된 worker. Orchestrator가 고르는 role은 고정 executor로 매핑됩니다.
- `original_task`: 모든 호출에 동일하게 주는 전체 문제와 첨부파일 정보.
- `context`: 이전 보고에서 이번 작업에 필요한 정보. 출처와 확인 여부를 표시합니다.
- `instruction`: 현재 subtask의 작업·범위·해석·가정·확인 절차·완료 기준.
- `report`: 자유 텍스트 결과. 실행 보고에는 Result / Evidence / Interpretation / Unfinished를 요구합니다.

Worker는 호출 간 대화를 유지하지 않습니다. 필요한 이전 결과는 orchestrator가 context에 명시합니다.
생성 파일은 workspace에 남고 경로를 보고합니다. 원 질문과 지시가 충돌하면 worker가 이를 보고합니다.

## InstructionRefiner

입력은 원 문제, 초안 instruction, context, 실행 worker, probe worker와 위임 직전 orchestrator 대화입니다.
Orchestrator 측 검토는 해당 대화의 복사본에서 진행하고 복사본은 폐기합니다.

Probe는 현재 subtask에 대해 네 가지를 묻습니다.

| 항목 | 확인하는 것 |
|---|---|
| understanding | 산출물과 담당 범위의 이해 |
| choices | 입력이 명시하지 않은 해석·가정과 선택 |
| risks | 잘못된 결과나 미완료를 낳을 구체적인 위험 |
| plan | 전체 subtask의 실행 단계와 위험 대응 |

실제 응답 또는 예측 응답을 원 문제와 초안에 대조합니다. 채택한 쟁점은 `clarify`,
`needs_verification`, `defer_to_execution`, `not_relevant` 중 하나로 판단합니다.
사전 확인은 `needs_verification`에만 수행합니다. 쟁점이 없으면 초안을 유지합니다.

출력은 실행 instruction과 `context_additions`입니다. 기존 context는 유지하고, 실행에 필요한 새로운 관측을
출처·확인 여부와 함께 덧붙입니다. Probe transcript 전체를 자동 전달하지 않습니다.
수정된 지시와 추가 context는 실행 보고와 함께 orchestrator에도 보입니다.

## 구성과 실험 경계

Role별 routing과 동일 subtask를 수행할 수 있는 복수 probe worker를 모두 지원합니다.
기본 `multi` pool은 일반 역할 하나, executor `gen_luna` 하나, probe-only `gen_haiku` 하나입니다.
따라서 여러 전문 worker가 본 작업을 병렬 분담한다는 의미가 아닙니다.

Probe의 도구 허용, 응답 수, 후속 질문, 실행 대화 연결은 설정으로 제어합니다.
기본 probe·사전 확인은 별도 대화와 scratch workspace에서 수행합니다.
실행 worker 선택 효과는 instruction 수정 효과와 구분해야 합니다.

Runtime은 모델·도구 비용, 호출·시간 예산, 오류, trace, checkpoint와 restore를 관리합니다.
현재 프롬프트와 설정은 [실험 안내](experiments.md), 실제 문구는 [Prompt 안내](../src/minpilot/prompts/README.md)를 봅니다.

## 출처와 이식

이 프레임워크는 OWL 실행 구조와 프롬프트를 사용하지 않습니다. 이전 pilot에서 웹 backend/cache,
blocklist, sandbox, GAIA loader/scorer와 고정 split 등 프레임워크 독립 요소를 재사용했습니다.
`tools/reader.py`의 페이지 판독과 분할은 AOrchestra
`benchmark/gaia/tools/extract_url_jina.py` @ `14a1a2051d6b` (Apache-2.0)에서 가져왔습니다.
원 판독 프롬프트는 유지하고 fetch chain, 모델, 비용·trace 처리를 이 프로젝트에 맞췄습니다.
다른 framework로 옮길 때는 `RefineContext`를 구현합니다.
