# Orchestrator–worker framework

단일 orchestrator가 run 동안 대화 하나를 유지하며 다음 결과와 executor를 고르고, worker 보고를 직접 읽고, 최종 답을 낸다.
Harness는 원본 기록, 실제 전달 context, 예산·trace·checkpoint를 관리한다. 후보는 pool에 등록된 worker 전부이며
기본 pool은 `gen_luna`, `gen_haiku`다. 모델 레지스트리의 다른 모델을 자동으로 후보에 넣지 않는다.

## 현재 두 조건

| 조건 | 흐름 |
|---|---|
| `direct_execution` | `execute` → 보고가 tool 결과로 돌아옴 → 다음 `execute` 또는 `finish` |
| `adaptive_probe` | 처음에는 `probe`; 이후 매번 `probe` / `execute` / `finish` 중 선택. Probe는 모든 worker의 이해·plan을 tool 결과로 돌려줌 |

Orchestrator는 `luna-high`를 쓴다. 위임은 순차 실행한다. Evaluator와 refiner는 없다(C42, C41).
각 worker는 run 동안 대화 하나와 workspace 하나를 유지한다. Probe와 execute request가 같은 대화에 차례로 쌓인다.
별도 사전 verification, follow-up probe, self_review, delegator, memory agent, vector DB는 없다.

## Orchestrator 대화

첫 user 메시지는 원 질문, worker 목록, 예산, answer format이다. Worker는 `worker_1`, `worker_2`(pool 순서)로
보이며 도구·실행당 도구 한도·context window만 표시한다. 모델 이름·가격·대화 토큰 수는 보이지 않는다(C42d).
행동은 tool call이다(`prompts/schemas.py`의 `action_tools`).

| tool | 인자 | 결과 |
|---|---|---|
| `probe` | `instruction`, `artifact_ids`, `rationale` | 모든 worker의 probe 보고 원문과 남은 예산 |
| `execute` | `worker_id`(alias), `instruction`, `artifact_ids`, `rationale` | 그 worker의 실행 보고 원문과 남은 예산 |
| `finish` | `answer`, `rationale` | run 종료 |

보고는 `Report aNNNNN from worker_k (probe|execution request, status S):` 머리줄 뒤에 원문 그대로 붙는다.
메시지 하나에 `probe`·`execute` call이 여러 개 있으면 순서대로 실행하고 각 call에 결과를 돌려준다. 같은 메시지의
execute들은 서로의 보고를 보지 않는다(독립 실행). `finish`는 그 메시지의 유일한 call일 때만 실행하고, `probe`는 메시지당 하나만 실행한다(한 번으로 모든 worker에게 간다). 잘못된 call은
오류를 tool 결과로 돌려주고 나머지 유효한 call은 실행한다. 유효한 call이 없는 메시지가 연속 2회면 run을 오류로 끝낸다.
Checkpoint는 각 probe·execute 직전에 그 메시지의 남은 행동 목록과 함께 저장한다. Tool call 없는 답은 한 번 다시 요청한다. 실행 한도에 도달하면 `finish`만
제공하고 tool call을 요구한다. 대화는 자르지 않으며 context window를 넘으면 실패로 기록된다.
`finish`의 `answer`는 항상 answer format의 값 하나이고, 해석이 갈리면 원 질문에 가장 잘 맞는 해석으로 답하며
근거 한계와 고른 해석은 `rationale`에 쓴다(C42h). 대화 전문은 `orchestrator.jsonl`에 저장한다.

## 기록과 전달

`records.py`의 `Records`는 `artifacts/aNNNNN.json`에 원본을 저장한다. Record에는 harness가 부여하는 `id`, 실제
생성자 `worker_id`, `stage`(`instruction`·`probe`·`execution`), 응답 전문 `body`, 종료 `status`가 있다.
Orchestrator의 probe·execute instruction은 `instruction` record로 저장하고 그대로 전달한다.
도구 원문은 해당 보고의 `tool_records`와 `tNNNNN` record로 저장하며 원 보고의 `parent_id`, 호출 `name`·`arguments`를
보존한다. Orchestrator는 보고 원문만 보고 도구 원문은 보지 않는다(C42e).

다른 worker의 결과는 orchestrator가 `artifact_ids`로 고른 보고 원문을 context로만 받는다. Context는 "earlier work;
may contain errors or unverified claims"로 표시된다. Orchestrator는 instruction에 그 보고가 무엇이고 어떻게 쓸지
적는다. 같은 worker의 이전 request·보고·도구 결과·파일은 그 worker의 대화와 workspace(`work/<worker_id>/`)에 남는다.
Orchestrator 대화는 worker에게 가지 않는다.

Probe는 등록 worker 모두에게 같은 assignment와 context를 각자 대화의 새 request로 보낸다. Worker는 plan 단계 확인용
도구를 최대 3회 쓰고 `understanding`(무엇을 묻고 어떤 조건이 적용된다고 이해했는지)·`plan` 두 항목으로 답한다.
도구로 확인한 단계와 확인 중 드러난 답은 그 단계의 `observed:` 줄에 출처와 함께 적는다. Orchestrator가 이해의
갈림(지시가 모호함)과 plan의 갈림(유효한 다른 접근인지, 결과를 못 내는 접근인지)을 나눠 판단하고, plan의 전제를
원 질문과 자기 의도에 대조한다. Probe 뒤 execute의 instruction은 고른 worker 대화의 다음 메시지이며, 이해나 plan이
뜻한 바와 다르면 뜻한 바를 밝힌다. Request가 예외로 끝나면(context window 초과 포함) 대화는 그 request 이전으로
남고 실패 보고만 저장된다. 실행 보고는 자유 형식이다.

## 예산과 실패

기본 최대 위임 12회는 `execute` 횟수다. Probe는 별도로 집계한다. 실행 도구 20회,
run LLM 400회·도구 400회·$5·3시간 상한을 유지한다. 모든 호출은 run 예산에 포함된다.
각 probe 라운드는 별도 LLM 60회·$1 상한을 쓴다. 소진 시 받은 보고와 중단 사실을 tool 결과로 돌려주고
같은 대화로 돌아간다. 자동 executor 배정은 없다. Run 전체 상한 초과는 종료한다.

유료 검색은 task당 100 credits다. 실제 Serper POST 직전 reserve하며 probe와 실행이 같은 counter를
공유한다. Cache 적중은 제외한다. 성공 응답은 billed, 429·인증/credit 거부는 nonbillable, timeout·판정 불가능한
실패는 unknown으로 구분한다. Unknown은 청구 확정 비용에 합치지 않지만 한도의 여유를 소비한다. 상한 후
추가 유료 요청을 막고 cache·무료 fallback은 허용하며 worker에게 제한을 표시한다.

일부/전체 probe 실패도 원본과 상태를 저장해 orchestrator에게 그대로 보인다. 자동 실행이나 재검토는 없다.
Probe에서 충분한 근거를 찾으면 execute 없이 finish할 수 있다.

## Checkpoint와 버전

선택한 probe 또는 execute 수행 전에 format 6 checkpoint를 `checkpoints/aN`에 저장한다. 행동 기록·실행 횟수·
pending action(tool call ID와 원 인자 포함)·record pool·orchestrator 대화·alias 대응표·worker별 대화와 toolbox 상태·
누적 예산·검색 credit·workspace를 함께 저장한다. 복원 시 pending action을 현재 조건으로 다시 검증하며, 허용되지
않으면 거부하고 probe를 execute로 바꾸지 않는다. Fingerprint, 모델·도구 설정, 실행 `v24`·probe `r24`를 검사한다.
이전 checkpoint는 변환하지 않는다. 도구는 `v7`, cache는 `tools_v7.sqlite`이며 기존 원본·snapshot·cache를 수정하지 않는다.

구현은 scripted model·fake web/HTTP로 검증한다. 오프라인 계약 검사는 실제 모델의 성능 향상을 입증하지 않는다.
도구 reader의 AOrchestra 출처와 blocklist·sandbox·gold-answer 격리는 기존과 같다.
Adaptive의 첫 probe는 prompt 지시이며 runtime이 강제하지 않는다. 구조건 `multi_worker_probe`는 새 실행에서 거부한다.
