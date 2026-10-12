# Shared-state orchestrator–worker framework

단일 orchestrator가 기록을 보고 다음 결과와 executor를 고른다. Harness가 원본 artifact와 현재 state,
실제 전달 context, 예산·trace·checkpoint를 관리한다. 후보는 pool에 등록된 worker 전부이며 기본 pool은
`gen_luna`, `gen_haiku`다. 모델 레지스트리의 다른 모델을 자동으로 후보에 넣지 않는다.

## 현재 두 조건

| 조건 | 위임 한 번의 흐름 |
|---|---|
| `direct_execution` | 작업·context·executor 선택 → 실행 → evaluator → 다음 orchestrator 판단에서 state 제안 검토 |
| `multi_worker_probe` | 초안·context 선택 → 모든 worker 독립 probe 1회 → evaluator → executor·전달 기록 선택 → 필요한 refiner → 실행 → evaluator → 다음 판단 |

Orchestrator·evaluator·refiner는 `luna-high`를 쓰며 호출과 prompt를 분리한다. 위임은 순차 실행한다.
별도 사전 verification, follow-up probe, self_review, connected probe, delegator, memory agent, vector DB는 없다.
최종 답을 evaluator에게 다시 보내지 않는다.

## 기록과 전달

`memory.py`의 `Memory`는 `artifacts/aNNNNN.json`에 원본을 저장한다. Artifact에는 harness가 부여하는
`id`, 실제 생성자 `worker_id`, `stage`, 모델의 첫 줄 `Title:`에서 얻는 `title`, 응답 전문 `body`가 있다. JSON 평가의 제목은 모델의 `title` 필드에서 읽고 본문은 원 응답 그대로 보존한다.
제목 누락 시 기본 제목과 `missing_title`을 남기고 본문을 보존한다. Probe·실행·평가는 자동 저장한다.
도구 원문은 기존 tool trace와 해당 보고의 `tool_records`에 보존한다. Catalog에는 보고 단위 목록과
`tool_count`만 제공하며, `aNNNNN/tool/N`으로 연결된 도구 원문을 조회한다. 파일·자료 참조는 보고와
도구 원문에 보존한다. 중요한 자료가 필요하면 해당 보고와 도구 참조를 context에 선택한다.

State는 다음 네 항목만 갖는 목록이다. 별도 state ID, conflict column, graph는 없다.

| 필드 | 값 |
|---|---|
| `type` | `observation`(관측), `assumption`(가정·해석), `result`(결과), `progress`(진행) |
| `content` | 조건·대상·시점을 포함한 주장/작업; 충돌·조건부 결과·탐색 실패와 단서도 여기에 기록 |
| `status` | 앞 세 종류: `unverified`, `supported`, `rejected`; 진행: `incomplete`, `complete`, `blocked` |
| `refs` | 근거 artifact ID 목록 |

Evaluator가 유효한 이전 항목을 유지한 **전체 교체 목록**을 제안한다. Orchestrator가 채택/거부와 이유를
남긴 뒤 harness가 변경 전후·평가 근거를 trace에 기록한다. 참조 검사는 사실 확인을 뜻하지 않는다.
Probe의 계획을 진행 완료로 취급하지 않는다. 실행 평가는 원 질문·근거와 지시 준수를 함께 검토한다.

Orchestrator는 `artifact_ids`, `state_rows`를 선택한다. Harness가 실제 본문·출처·상태를 context로 만든다.
선택한 state의 refs 보고 본문도 함께 전달해 worker가 조회할 수 없는 ID만 받지 않게 한다.
행 번호는 판단 입력 snapshot의 0-based 위치이며 영구 ID가 아니다. 선택 snapshot·실제 context·최종 지시는
trace와 checkpoint에 저장된다. State 채택 전 snapshot에서 선택을 해석하므로 아직 채택하지 않은 새 정보는
artifact로 전달할 수 있다. Refiner는 승인된 변경을 표현하며 state를 판정하지 않는다. 새 판단이 필요하면
`reconsider`를 반환하고 orchestrator가 기존 초안 유지/새 작업 작성을 한 번 결정한다.

각 판단은 원 질문·현재 state·artifact catalog·관련 평가에서 시작한다. 과거 보고 전문을 대화에 누적하지 않는다.
Controller의 JSON `read_memory` 행동은 원본 읽기만 제공하며 판단당 최대 3라운드다. 외부 검색·파일 실행은
worker에게만 있다. 새 보고 전문과 실제 instruction/context/종료 상태는 evaluator에게 직접 주되 도구 원문
전체는 자동 첨부하지 않는다. 모든 실제 모델 입력은 기존 messages/LLM trace에 보존한다.

Probe는 같은 초안과 context를 받고 각자 독립 대화·scratch workspace에서 최대 도구 3회를 쓴다.
Executor에게 probe 대화와 파일을 자동 이어주지 않는다. Rewrite 여부와 관계없이 orchestrator가 선택한
probe 관측 artifact는 전달한다. 실행 worker는 `Title:`과 Result / Evidence / Interpretation / Unfinished를 쓴다.

## 예산과 실패

기본 위임 12회, 실행 도구 20회, run LLM 400회·도구 400회·$5·3시간을 유지한다. 위임 전 probe·평가·선택·
수정·조회·수정 요청은 별도 LLM 60회·$1 상한과 run 상한 모두에 포함된다. 위임 전 상한이 소진되면 추가
사전 호출 없이 마지막 승인 선택을 쓰며, 선택 전이면 pool 등록 순서의 첫 worker로 초안을 실행하고 사유를 기록한다.
Run 전체 상한 초과는 종료한다.

유료 검색은 task당 100 credits다. 실제 Serper POST 직전 reserve하며 scratch fork와 실행이 같은 counter를
공유한다. Cache 적중은 제외한다. 성공 응답은 billed, 429·인증/credit 거부는 nonbillable, timeout·판정 불가능한
실패는 unknown으로 구분한다. Unknown은 청구 확정 비용에 합치지 않지만 한도의 여유를 소비한다. 상한 후
추가 유료 요청을 막고 cache·무료 fallback은 허용하며 worker와 orchestrator에게 제한을 표시한다.

일부/전체 probe 실패도 원본과 상태를 저장해 평가한다. 전체 실패 시 초안과 capability로 선택하며 성공한
확인이 있었다고 처리하지 않는다. 잘못된 JSON·참조는 1회 수정 요청한다. Evaluator가 계속 실패하면 이전
state와 새 보고를 보존하고 실패를 orchestrator에 전달한다. Refiner 실패 시 승인된 초안·context를 실행한다.

## Checkpoint와 버전

초안 선택 이후, probe 이전에 format 2 checkpoint를 저장한다. Artifact pool, state, 평가, context 선택 snapshot,
실제 context, 누적 예산·검색 credit, workspace·도구 상태를 포함한다. 복원 시 fingerprint, 모델·도구 설정,
실행 `v13`·probe/refiner `r15`·evaluator `e3`을 검사한다. 이전 checkpoint는 변환하지 않는다.
도구는 `v6`, cache는 `tools_v6.sqlite`이며 기존 원본·snapshot·cache를 수정하지 않는다.

구현은 scripted model·fake web/HTTP로 검증한다. 오프라인 계약 검사는 실제 모델의 성능 향상을 입증하지 않는다.
도구 reader의 AOrchestra 출처와 blocklist·sandbox·gold-answer 격리는 기존과 같다.
