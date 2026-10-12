# Shared-state orchestrator–worker framework

단일 orchestrator가 기록을 보고 다음 결과와 executor를 고른다. Harness가 원본 artifact와 현재 state,
실제 전달 context, 예산·trace·checkpoint를 관리한다. 후보는 pool에 등록된 worker 전부이며 기본 pool은
`gen_luna`, `gen_haiku`다. 모델 레지스트리의 다른 모델을 자동으로 후보에 넣지 않는다.

## 현재 두 조건

| 조건 | 위임 한 번의 흐름 |
|---|---|
| `direct_execution` | 작업·context·executor 선택 → 실행 → evaluator의 state 갱신 → 다음 판단 |
| `adaptive_probe` | 처음에는 probe 지시; 매번 probe / execute / finish / read_memory 선택 → probe 평가·state 갱신 → refiner → 다음 행동 선택; execute는 실행 평가 후 다음 판단 |

Orchestrator·evaluator·refiner는 `luna-high`를 쓰며 호출과 prompt를 분리한다. 위임은 순차 실행한다.
별도 사전 verification, follow-up probe, self_review, connected probe, delegator, memory agent, vector DB는 없다.
최종 답을 evaluator에게 다시 보내지 않는다.

## 기록과 전달

`memory.py`의 `Memory`는 `artifacts/aNNNNN.json`에 원본을 저장한다. Artifact에는 harness가 부여하는
`id`, 실제 생성자 `worker_id`, `stage`, 모델의 첫 줄 `Title:`에서 얻는 `title`, 응답 전문 `body`가 있다. JSON 평가의 제목은 모델의 `title` 필드에서 읽고 본문은 원 응답 그대로 보존한다.
제목 누락 시 기본 제목과 `missing_title`을 남기고 본문을 보존한다. Probe·실행·평가는 자동 저장한다.
도구 원문은 기존 tool trace와 해당 보고의 `tool_records`에 보존하며, `tNNNNN` ID로도 저장한다.
Catalog에는 보고 단위 목록과 연결된 `tool_ids`를 제공하고 도구 본문은 넣지 않는다.
보고의 `aNNNNN`과 도구 결과의 `tNNNNN`은 모두 같은 ID 조회 계약을 사용한다.
`read_memory.refs`, state의 `refs`, context 선택의 `artifact_ids`에 저장된 ID를 그대로 쓴다.
도구 결과에는 원 보고의 `parent_id`, 원 tool message, 연결할 수 있는 호출의 `name`·원 `arguments`를 보존한다.
이미지 payload는 이 조회로 전달하지 않으며 reader 답변도 source 전문과 구분한다. 이전의 `/tool/N` 주소는 사용하지 않는다.

State는 다음 네 항목만 갖는 목록이다. 별도 state ID, conflict column, graph는 없다.

| 필드 | 값 |
|---|---|
| `type` | `observation`(관측), `assumption`(가정·해석), `result`(결과), `progress`(진행) |
| `content` | 조건·대상·시점을 포함한 주장/작업; 충돌·조건부 결과·탐색 실패와 단서도 여기에 기록 |
| `status` | 앞 세 종류: `unverified`, `supported`, `rejected`; 진행: `incomplete`, `complete`, `blocked` |
| `refs` | 근거 artifact ID 목록 |

Evaluator는 새 보고를 평가하고 유효한 이전 항목을 유지한 **전체 갱신 목록**을 작성한다.
Harness는 형식·참조 ID를 검사한 뒤 목록을 바로 저장하고 변경 전후·평가 근거를 trace에 기록한다.
Orchestrator는 state를 승인·거부하거나 근거 상태를 다시 판정하지 않는다. 참조 검사는 사실 확인을 뜻하지 않는다.
Probe의 계획을 진행 완료로 취급하지 않는다. 실행 평가는 원 질문·근거와 지시 준수를 함께 검토한다.

Orchestrator는 갱신된 state에서 다음 작업·executor·`artifact_ids`·`state_rows`를 선택한다.
Harness가 선택한 본문·출처·상태와 state의 refs 기록을 context로 만든다. 행 번호는 해당 판단 입력의
0-based 위치이며 영구 ID가 아니다. 선택 중 state는 바뀌지 않으며 snapshot·실제 context·최종 지시는
trace와 checkpoint에 저장된다. 승인 전후 목록이나 변경 행의 충돌 검사는 없다.
유효한 probe 평가마다 refiner를 한 번 호출한다. Refiner는 원 질문·초안·실제 probe context·최신 state·
평가의 이유와 수정 지적·worker 목록·artifact 목록을 받아 표현을 수정하거나 초안을 유지한다.
Executor와 최종 context는 아직 선택되지 않는다. 새 사실 판단·답 기준 변경·state 갱신은 하지 않는다.
`context_notes`는 orchestrator의 context 선택 참고이며 실행 context에 자동으로 붙이지 않는다.

Probe 초안은 `instruction.draft`, 유효한 refiner 응답 원문은 `instruction.refined` artifact로 저장한다.
Orchestrator는 probe 작업을 실행할 때 `instruction_id`와 executor·context를 선택한다. Harness는 저장된
지시를 그대로 전달한다. `instruction_id`와 새 `instruction`은 동시에 받을 수 없다. 새 작업의 직접 실행은
새 instruction을 작성할 수 있으며 refiner를 호출하지 않는다. Orchestrator의 `refine`·`changes`는 거부하고
Evaluator의 `changes`는 유지한다.

각 판단은 원 질문·현재 state·artifact catalog·관련 평가에서 시작한다. 과거 보고 전문을 대화에 누적하지 않는다.
Controller의 JSON `read_memory` 행동은 원본 읽기만 제공하며 판단당 최대 3라운드다. 외부 검색·파일 실행은
worker에게만 있다. 새 보고 전문과 실제 instruction/context/종료 상태는 evaluator에게 직접 주되 도구 원문
전체는 자동 첨부하지 않는다. 모든 실제 모델 입력은 기존 messages/LLM trace에 보존한다.

Probe는 같은 초안과 context를 받고 각자 독립 대화·scratch workspace에서 최대 도구 3회를 쓴다.
Executor에게 probe 대화와 파일을 자동 이어주지 않는다. Rewrite 여부와 관계없이 orchestrator가 선택한
probe 관측 artifact는 전달한다. 실행 worker는 `Title:`과 Result / Evidence / Interpretation / Unfinished를 쓴다.

## 예산과 실패

기본 최대 위임 12회는 `execute` 횟수다. Probe는 별도로 집계한다. 실행 도구 20회,
run LLM 400회·도구 400회·$5·3시간 상한을 유지한다. 모든 호출은 run 예산에 포함된다.
각 probe 라운드(평가 포함)와 probe 평가 후 refinement는 각각 별도 LLM 60회·$1 상한을 쓴다.
Probe 상한 소진 시 반환된 자료와 기존 state를 보존하고 평가 실패를 알린 뒤 같은 판단 루프로 돌아간다.
자동 executor 배정은 없다. Refinement 상한 소진 시 초안 ID를 보존하고 orchestrator의 다음 판단으로 돌아간다.
Run 전체 상한 초과는 종료한다.

유료 검색은 task당 100 credits다. 실제 Serper POST 직전 reserve하며 scratch fork와 실행이 같은 counter를
공유한다. Cache 적중은 제외한다. 성공 응답은 billed, 429·인증/credit 거부는 nonbillable, timeout·판정 불가능한
실패는 unknown으로 구분한다. Unknown은 청구 확정 비용에 합치지 않지만 한도의 여유를 소비한다. 상한 후
추가 유료 요청을 막고 cache·무료 fallback은 허용하며 worker와 orchestrator에게 제한을 표시한다.

일부/전체 probe 실패도 원본과 상태를 저장해 평가한다. 잘못된 JSON·참조는 1회 수정 요청한다.
Evaluator가 계속 실패하면 이전 state와 새 보고를 보존하고 실패를 orchestrator에 전달한다.
Probe 평가 실패 시 refiner를 생략한다. Refiner 실패·수정 불가 시 원 초안 ID를 선택할 수 있다.
자동 실행이나 재검토는 없다. Probe 직후 판단에는 원 초안 ID·실제 context·새 보고 전문·최신 평가·
refiner 결과와 상태·사용 가능한 instruction ID/전문/context notes를 제공한다. 다음 판단부터 과거 본문은 기록 조회로 읽는다.

## Checkpoint와 버전

선택한 probe 또는 execute 수행 전에 format 4 checkpoint를 `checkpoints/aN`에 저장한다.
공통 행동 번호·첫 행동 여부·행동 기록·실행 횟수·pending action·instruction artifact·선택 ID·실제 전달 지시를 함께 저장한다.
복원 조건이 pending action을 허용하지 않으면 거부하며 probe를 execute로 바꾸지 않는다. Artifact pool, state, 평가, context 선택 snapshot,
실제 context, 누적 예산·검색 credit, workspace·도구 상태를 포함한다. 복원 시 fingerprint, 모델·도구 설정,
실행 `v18`·probe/refiner `r21`·evaluator `e6`을 검사한다. 이전 checkpoint는 변환하지 않는다.
도구는 `v7`, cache는 `tools_v7.sqlite`이며 기존 원본·snapshot·cache를 수정하지 않는다.

구현은 scripted model·fake web/HTTP로 검증한다. 오프라인 계약 검사는 실제 모델의 성능 향상을 입증하지 않는다.
도구 reader의 AOrchestra 출처와 blocklist·sandbox·gold-answer 격리는 기존과 같다.

Orchestrator 입력에는 `request` 없이 `available_actions`와 `first_action`을 제공한다.
Memory 조회는 first_action을 바꾸지 않는다. Adaptive의 첫 probe는 prompt 지시이며 runtime이 강제하지 않는다.
Probe에서 충분한 근거를 찾으면 execute 없이 finish할 수 있다. 구조건 `multi_worker_probe`는 새 실행에서 거부한다.
