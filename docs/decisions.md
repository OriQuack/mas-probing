> 2026-10-12 KST 현재 계약: 실행 v17 / probe·refiner r20 / evaluator e6 / tools v7.
> `adaptive_probe`가 이전 `multi_worker_probe`를 대체한다. Orchestrator는 매번 probe/execute/finish/read_memory를
> 고르며 probe 뒤 자동 실행과 별도 executor 선택 호출은 없다. 최대 12회는 execute 횟수다.
> Probe 라운드와 refinement는 각각 $1/LLM 60회 보조 상한이며, 소진 시 자동 executor 배정하지 않는다.
> Format 3 checkpoint는 probe·execute 공통 행동 번호 aN을 쓴다. 아래 이전 결정 중 충돌하는 흐름은 이 계약으로 대체한다.

# 현재 구현 결정

현재 유지하는 설계의 요약입니다. 실험 순서와 과거 변경은
[역사적 결정 기록](history/decisions-before-cleanup.md)에 있습니다. 현재 동작은 framework 문서와 코드로 확인합니다.

| 항목 | 현재 결정 | 구현 |
|---|---|---|
| 조정 | orchestrator 하나가 delegate/finish를 동적으로 선택 | harness, agents/orchestrator |
| 실행 | role별 executor 고정; worker 호출 간 상태 없음 | config, agents/worker |
| 전달 | 원 문제 + context + instruction; context와 실행 지시 분리 | prompts/worker |
| 개입 | InstructionRefiner는 위임 전에 instruction과 추가 사실을 반환 | refine/base |
| 검토 대화 | orchestrator 대화 복사본에서 검토하고 폐기 | refine/review |
| 응답 처리 | probe 응답 익명화·순서 무작위화; 실제 worker ID는 로그에 유지 | refine/review |
| 검증 | needs_verification만 사전 확인; 나머지는 명시·실행 확인·제외 | refine/review |
| 정보 전달 | context 유지, 추가 관측은 출처·검증 상태와 함께 context_additions | prompts, harness |
| 후속 조정 | 실제 전달 instruction과 추가 context를 orchestrator에도 표시 | prompts/orchestrator |
| 격리 | probe/check는 별도 대화·scratch; 연결은 명시한 variant만 | harness |
| 오류 | 검토 예산 초과·재시도 후 잘못된 응답이면 원 초안 실행, 별도 상태 기록 | refine/review |
| 페이지 판독 | read_url은 reader 답; read_url_text/find_in_url은 원문 확인 | tools/reader, tools/web |
| 최종 답 | orchestrator가 GAIA 형식으로 답; 별도 answerer 없음 | data/gaia, prompts/orchestrator |
| 재개 | 위임 직전 checkpoint; 버전·모델·도구·상태 fingerprint 검사 | harness |
| 연구 집계 | 같은 checkpoint에서 조건별 restore; 누락/실패 포함; 과제별 동일 가중 | scripts/score_runs |

## 2026-10-11 구조 정리

| ID | 선택 | 대안 / 이유 | 위치 |
|---|---|---|---|
| C01 | 현재 prompt만 runtime 지원; r5 전용 코드·설정·테스트 제거 | 과거 구현을 함께 유지하면 현재 검토 경로가 복잡해짐. 당시 코드 snapshot은 근거로 유지 | prompts, refine, config |
| C02 | 역할별 Python 파일에 완성된 multiline prompt 본문과 입력 처리를 함께 둠; 응답 계약은 schemas.py | 별도 txt·로더와 문구 조각 조립을 제거. 짧은 정책·공통 문구는 공유하고, 본문 가독성을 위해 일부 중복 허용. 136개 조합의 출력 동일성 확인 | src/minpilot/prompts |
| C03 | 현재 조건 이름을 동작 기준으로 변경; 옛 label은 원본에서 유지 | 과거 결과를 현재 버전 결과처럼 바꾸지 않음 | configs/refiners, docs/experiments.md |
| C04 | 최신 종합 보고서의 주요 317개 실행과 분석·snapshot 보존 | 초기 탐색/중단 세션과 검증한 중복 자료 제거. 이동 전후 원본 파일 SHA-256 일치 확인 | reports/retention.json |
| C05 | manifest의 run_roots로 원본 실행만 탐색 | 재귀 run.json 탐색은 workspace·trace 복사본 중복을 낳음 | artifacts.py |
| C06 | prompt 본문을 Python 소스로 배포하고 code_hash에 포함 | 별도 템플릿 리소스 패키징 없이 문구 변경도 코드 출처에 기록 | prompts, harness |
| C07 | 과거 checkpoint 경로·조건 이름은 restore·`--compare`에서 자동 변환하지 않고 실험 안내에 변환 방법만 둠 | 자동 변환하면 `restored_from`과 condition 기록이 실험마다 섞일 수 있음. 사용자 결정(2026-10-11) | docs/experiments.md |
| C08 | 이동 대응표 조회를 `artifacts.migrate_path` 하나로 통일. CLI `resolve`는 대응표 우선, run/checkpoint 해석은 실제 경로 우선 | 두 구현이 `docs/decisions.md` 같은 재사용 경로에서 다른 답을 냄 | artifacts.py, scripts/experiments.py |
| C09 | `code_hash`는 패키지의 `.py`만 해시(템플릿 txt 없음) | 중간 설계의 `.txt` 포함 흔적 제거. 현재 해시 값은 변하지 않음 | harness |
| C10 | 실행 prompt v8: orchestrator를 역할 설명과 네 개의 의미별 섹션으로 재작성; 중간 결과가 다음 작업을 바꾸는 지점에서 분리하고 같은 결과를 위한 실행은 묶음 | 사용자 요청(2026-10-11). 별도 delegator·고정 단계·추가 출력 필드 없이 작업 선택 기준을 명시. Worker/refiner는 유지; 분해·정확도 개선 효과는 미검증 | prompts/orchestrator |
| C11 | 실행 v9/refiner r10: 실행 worker와 probe의 system prompt 분리; probe 문구·파서를 probe.py에 모으고 choices를 assumptions로 변경 | 사용자 요청(2026-10-11). 같은 전문 역할·도구를 쓰되 수행과 수행 전 설명을 구분. 실제·예측 probe는 같은 renderer 사용; 연결 실행은 과거 대화를 보존하고 system만 실행용으로 전환. Analysis는 명칭만 맞추고 검토·rewrite 정책은 유지 | prompts/worker, prompts/probe, agents/worker |
| C12 | Refiner r11: 분석·rewrite를 목적별 섹션으로 재작성. 정상적인 subtask 범위 한정과 원 질문 왜곡을 구분; 해석 차이와 실행 방식 차이, 사전 확인과 실행 중 확인을 구별 | 사용자 요청(2026-10-11). 미해결 해석의 강제 확정·무조건 답 산출을 피하고 실제 근거 한계를 보고하도록 명확화. Simulation/verification 문구 정리; pipeline·스키마·worker/probe는 유지. 효과는 미검증 | prompts/refiner |
| C13 | direct_check 조건·전용 구현·설정 제거; baseline, self_review, 실제 probe 유지 | 사용자 요청(2026-10-11). 예측/실제 응답의 같은 질문·검토 절차 비교를 우선하고 응답 없는 검토 경로를 제거. 남은 prompt 출력은 동일하여 버전 유지; 과거 기록·snapshot은 보존 | config, refine, prompts/refiner, configs/refiners |
| C14 | 실행 v10/refiner r12: 같은 결과를 위한 worker 내부 실행과 다음 질문 선택의 위임 경계를 구분. 결과를 좌우하는 context 주장의 근거 확인·미검증 표시를 명시하고 probe 중복·refiner 추상어를 축소 | 사용자 요청(2026-10-11). 구체적이지만 결과에 영향 없는 우려의 not_relevant 사용을 명확화. 역할·pipeline·스키마는 유지; 검증 행동 명확화에 따른 효과는 미평가 | prompts/orchestrator, prompts/worker, prompts/probe, prompts/refiner |
| C15 | restore한 baseline은 선택 사항. recording run이 checkpoint 이후 이어서 푼 부분을 baseline으로 쓸 수 있음. 단, restore를 같은 도구·검색 환경에서 바로 이어 돌릴 때만. checkpoint를 나중에 재사용하거나 환경이 바뀌면 baseline을 restore | 두 run은 같은 대화·초안에서 출발한 같은 조건의 시행이고, 남는 차이는 실행 시점과 환경뿐. 사용자 결정(2026-10-11). `score_runs.py --compare`는 restore arm끼리만 짝지으므로 fresh baseline과의 비교는 별도로 함 | CLAUDE.md, scripts/score_runs.py |
| C16 | tools v5: Wayback snapshot을 직접 읽을 때 header에 실제로 받은 capture 날짜(reader의 최종 URL)를 표기. 요청 날짜와 다르면 함께 표기하고, 최종 URL이 없으면 날짜를 확정하지 않음. cache는 `tools_v5.sqlite`로 분리 | 사례 분석(2026-10-10 §4.1)에서 요청 날짜가 실제 capture 날짜처럼 표기되어 16d825ff·a7feb290의 판단에 영향. 사용자 결정(2026-10-11). Crawl4AI가 redirect된 capture URL을 보고하는 것을 확인함 | tools/web.py, tools/config.py |
| C17 | LongCoT·MoNaCo를 `~/data2/datasets/{LongCoT,MoNaCo}`에 고정 revision으로 내려받고(`scripts/fetch_datasets.py`, `SOURCE.json`에 출처 기록), `minpilot.data.longcot`·`minpilot.data.monaco`로 읽음. 기본 loader는 질문만 반환하고 답·LongCoT `problem` metadata·MoNaCo decomposition·reasoning chain은 채점·분석용 함수로만 반환 | 사용자 요청(2026-10-11). 홈 디스크 용량 문제로 데이터는 /data2. GAIA loader와 같은 정답 분리. LongCoT `problem`에는 정답 유도 값(예: chess `final_fen`)이 있음. MoNaCo는 재배포 금지라 저장소에 복사하지 않음. 주석을 모델 입력으로 주는 실험은 별도 조건으로 선언 | scripts/fetch_datasets.py, data/longcot.py, data/monaco.py |


## 2026-10-11 KST shared state·평가·선택 구현

아래 결정이 위 표의 고정 executor·refiner 중심 runtime을 대체한다. 과거 결정과 원본 기록은 보존한다.

| ID | 선택 | 이유 / 범위 | 위치 |
|---|---|---|---|
| C18 | `direct_execution`, `multi_worker_probe` 두 condition; pool 등록 worker 전부 executor 후보 | 전체 구성 비교 후 ablation. 이전 preset/CLI와 checkpoint를 새 의미로 재사용하지 않음 | config, configs/conditions, harness |
| C19 | Immutable artifact + evaluator의 네 필드 state 전체 교체 제안, orchestrator 채택/거부 이유 | 사실 판단·원본·전달 context를 구분. 행 번호는 입력 snapshot에서만 유효 | memory, harness |
| C20 | Controller JSON read_memory 최대 3라운드, 보고별 tool_count와 artifact/tool/N 조회 | 외부 도구 권한 없이 필요할 때 원문 조회. 모든 도구를 catalog 항목으로 만들지 않음 | controller, memory |
| C21 | Probe/실행 evaluator 공통 도입, refiner는 승인 변경의 표현만; 별도 verification·follow-up·self_review·연결 실행 제거 | Probe 계획·가정과 실행 관측·결과를 구별. 새 판단은 orchestrator로 한 번 반환 | prompts, harness |
| C22 | 실행 v11, probe/refiner r13, evaluator e1, checkpoint format 2 | 원본 pool/state·선택 snapshot·누적 budget/credit 저장; 과거 형식 변환 없음 | prompts, harness |
| C23 | tools v6 별도 cache; 실제 Serper POST마다 task당 100-credit 예약 | Fork/재시도/복원 공유. billed·nonbillable·unknown 구분; unknown은 headroom 소비. Cache/무료 fallback 허용 | tools/search_budget, backends, web |
| C24 | 위임 전 $1/60-LLM 소진 후 추가 사전 호출 없음 | 마지막 승인 선택 또는 pool 첫 worker로 초안 fallback, 실패 이유 기록. Run 전체 상한은 종료 | harness |
| C25 | 오프라인 계약 검증만 수행; 유료 fresh 비교는 별도 계획 | 사례 walkthrough를 모델 성능 개선 증거로 취급하지 않음. eval_v1 열람·튜닝·실행 금지 유지 | tests, docs/experiments.md |
| C26 | 실행 v12, probe/refiner r14, evaluator e2: 입력 가시성·근거·판단 권한·출력 필드 설명 정리 | 사용자 요청. Thinking Before Thinking 분석 세 문서와 agent-prompt-engineering skill의 작성 원칙을 적용. 기존 역할·호출 순서·스키마를 유지하며 충분한 지시와 지지된 결과의 보존, 전체 state 채택, snapshot 행 선택, refiner 전달 범위를 명시. 특정 과제 문구나 논문 제어 구조는 복제하지 않음. 모델 효과는 미평가 | prompts, prompts/README.md |

| C27 | 실행 v13, probe/refiner r15, evaluator e3: orchestrator·evaluator·refiner 도입부에 역할 소개 복원 | 사용자 요청. You are …로 역할을 밝힌 뒤 수행할 작업을 설명. 나머지 본문·흐름·스키마는 유지 | prompts |

## 2026-10-12 KST live 진단

| ID | 선택 | 이유 / 범위 | 위치 |
|---|---|---|---|
| C28 | 주요 GAIA 탐색 5개 × 두 조건 각 1회 fresh, 총 10회. Run당 $1·15분, 전체 $10 상한; 조건 순서 교차 | 사용자 요청으로 유료 live 테스트 수행. PubChem·spin glass는 기존 비용을 보고 제외. 실행 전에 계획·순서·상한을 manifest에 저장하고 실행 중 prompt/package 코드는 고정. 초기 import 오류의 무호출 시작 실패 10건도 별도 보존·실패 집계. 알려진 비용 $0.88999526, 비용 불명 LLM 1건. 양쪽 2/5이며 시간 한도 4건 포함. 과거 arXiv baseline의 실제 26분보다 짧은 한도여서 단순 성능 비교에 제한 | outputs/experiments/2026-10-12_gaia-key-traces-live-retry, reports/2026-10-12-gaia-key-traces-live.ko.md |

## 2026-10-12 KST 별도 실험: perturbation 일관성

| ID | 선택 | 이유 / 범위 | 위치 |
|---|---|---|---|
| C29 | 첫 subtask perturbation 일관성으로 worker를 고르는 실험을 `minpilot` framework 밖 별도 패키지 `perturbation_consistency`로 구현. LongCoT math chain을 노드 단위로 실행하고, 각 worker가 첫 노드를 풀이 방식 지시만 다른 n개 variant(단계별 CoT·Plan-and-Solve·풀고 검산·Step-back·풀이 지시 없음)로 풀어 동치 답 최대 묶음 비율로 선택. 비교는 같은 노드 단위 실행의 고정 worker 반복. LongCoT 공식 math 비교에 표기 정리, LLM fallback judge 없음 | 사용자 결정(2026-10-11): worker luna-high·haiku-high·gemini, 문제 본문 불변·풀이 방식 variant n=5, baseline은 같은 노드 단위 실행, linear easy 23·hard 26. framework와 섞이지 않게 별도 패키지로 두고 minpilot의 LLM client·trace·loader만 사용. 노드 간 값 전달은 benchmark 의존관계를 따르는 실험 장치. 결과는 reports/2026-10-12-longcot-perturbation-consistency.ko.md (branch에서는 C18로 기록했다가 main 병합 시 재번호) | src/perturbation_consistency, scripts/*perturbation*, outputs/experiments/2026-10-1*_longcot-perturbation-consistency-* |


## 2026-10-12 KST 기록 참조 통일

| ID | 선택 | 이유 / 범위 | 위치 |
|---|---|---|---|
| C30 | 실행 v14, probe/refiner r16, evaluator e4. 보고와 도구 결과를 저장된 ID로 조회·인용·context 선택. State 네 필드와 행 선택은 유지 | 사용자 피드백. Live 진단의 `/tool/N` 조회 주소와 state 근거 ID 혼동을 줄이기 위한 계약 변경. 도구 원문에 `tNNNNN` ID와 원 보고 `parent_id`를 부여하고 보고의 `tool_ids`로 연결한다. Catalog에 도구 본문은 추가하지 않는다. Prompt의 역할·절 구성은 유지하고 참조 설명만 수정한다. 실제 모델의 개선 효과는 미검증 | memory.py, prompts, tests/test_context.py |


## 2026-10-12 KST prompt 검토 반영

| ID | 선택 | 이유 / 범위 | 위치 |
|---|---|---|---|
| C31 | 실행 v15, probe/refiner r17, evaluator e5, tools v7. 채택 제안에서 변경·삭제된 이전 state 행 선택 거부, 도구 호출 이름·인자 연결, 전달 경계·조건부 지지·state 정리 기준 보완 | 사용자 승인. 이전 snapshot 행 번호는 유지하되 바뀐 행을 현재 판단으로 전달하는 것을 validation과 기존 1회 수정 요청으로 막는다. 도구 기록의 ID·state 네 필드·전체 승인·역할과 호출 구조는 유지한다. 이미지 재전달은 추가하지 않는다. Reader의 답 없음은 제공된 source/part에 한정하고 새 tools_v7 cache를 사용한다. 기존 run·cache는 보존하며 실제 모델 개선 효과는 미검증 | harness.py, memory.py, prompts, tools/config.py, tests/test_context.py |


## 2026-10-12 KST probe 답변 순서

| ID | 선택 | 이유 / 범위 | 위치 |
|---|---|---|---|
| C32 | Probe/refiner 식별자 r18. Probe 답변을 understanding → plan → assumptions → risks 순으로 작성 | 사용자 요청. 계획을 먼저 작성하고 그 계획에 사용한 가정과 실패 가능성을 설명하게 한다. Probe는 본 실행이 아니며, 실행 worker의 보고·state·평가 흐름·refiner 본문은 유지한다. 실제 모델 효과는 미검증 | prompts/probe.py |


## 2026-10-12 KST evaluator 단독 갱신

| ID | 선택 | 이유 / 범위 | 위치 |
|---|---|---|---|
| C33 | 실행 v16, probe/refiner r19, evaluator e6. Evaluator의 유효한 state 출력을 즉시 저장하고 orchestrator는 작업·executor·context 선택만 수행 | 사용자 결정. `accept_state`, `state_reason`, `requires_decision`, `_adopt` 및 변경된 이전 행 선택 검사를 제거한다. 전체 목록 교체는 저장 방식으로 유지한다. Refiner는 `can_refine=false`이면 초안 유지·사유 기록으로 끝내며 별도 재검토 호출을 제거한다. 평가 실패 시 기존 state와 원본을 유지하고 orchestrator에게 재평가 권한을 넘기지 않는다. Tools v7·기존 기록은 유지. C18의 승인 방식과 C31의 행 충돌 검사를 대체하며 모델 효과는 미검증 | harness.py, memory.py, controller.py, prompts, tests |


## 2026-10-12 KST evaluator 단독 갱신 live 진단 계획

| ID | 선택 | 이유 / 범위 | 위치 |
|---|---|---|---|
| C34 | Secret Santa → OpenCV → Freud 순서, `multi_worker_probe` fresh 각 1회. Run당 $0.30·15분, 합계 $0.90 상한. v16/r19/e6, tools v7 고정 | 사용자 요청. 기존 저비용 탐색 과제 3개로 갱신·선택·전달 계약을 확인한다. 전체 비교나 개선 효과 추정은 하지 않는다. 실행 전에 manifest·planned.csv·코드 snapshot을 저장하며 실행 중 production 코드를 바꾸지 않는다. 모든 호출·실패·비용 불명과 검색 credit을 집계하고 eval_v1은 접근하지 않는다 | outputs/experiments/2026-10-12_evaluator-owned-state-live; reports/2026-10-12-evaluator-owned-state-live.ko.md |

C34 결과: 예정 3회 모두 정상 종료, 2/3 정답, 총 알려진 비용 $0.18047882·비용 불명 0건·Serper 61 credit. State 갱신 10건과 context 선택 13건의 계약 검사 통과, 참조/JSON 수정 요청 0건. Secret Santa 답 보류와 probe 해결 후 추가 실행은 남은 문제로 기록했다. 개선 효과를 추정하지 않는다.


## 2026-10-12 (KST): probe 평가 뒤 rewrite, 저장된 지시 선택 (v18/r21/e6)

유효한 probe 평가마다 executor 선택 전에 refiner가 표현을 수정하거나 유지한다. Refiner는 최신 state와
평가 rationale·changes를 받고 state를 바꾸지 않는다. Orchestrator는 그 결과를 보고 finish/probe/execute를
선택한다. Probe 초안과 refiner 원문은 artifact로 보존하며 실행은 instruction_id로 저장된 지시를 그대로
전달한다. 새 작업 직접 실행은 새 instruction을 허용하고 refinement는 하지 않는다. Context notes는
orchestrator의 선택 참고다. 평가 실패는 rewrite를 생략하고 refiner 실패·수정 불가·보조 예산 소진은 초안
ID를 유지한 채 다음 판단으로 돌아간다. Probe/refinement 각각 $1·60회와 run 공통 예산을 유지한다.
Checkpoint format 4이며 과거 checkpoint 변환은 하지 않는다. Tools v7과 evaluator e6는 유지한다.

## 2026-10-12 (KST): probe·위임 문구 보완과 입력 중복 제거 (v19/r22/e6)

사용자 피드백에 따라 probe 가정에는 context·instruction의 미검증 전제도 포함한다. 도구 관측은 기존
네 항목 안에 `observed:`와 출처를 적으며 파서와 보고 항목은 유지한다. 전체 실행을 목표로 삼지는 않되
허용된 확인 중 발견한 답은 근거와 함께 보고한다. Orchestrator는 state 미해결 항목뿐 아니라 아직 state가
다루지 않은 원 질문의 부분도 위임할 수 있다. 보고서 선택만으로 연결 도구 본문이 전달되지 않음을 명시한다.
목표 결과와 범위가 같은 probed assignment는 방법·표현 변경으로 새 지시를 만들지 않고 저장된 ID로
실행해 probe→실행 귀속을 유지한다. 수정본이 있어도 초안은 목록에 남기는 기존 선택 정책을 유지한다.

모델 입력을 만들 때 `latest_probe` 복사본에서 중복 `instructions`·`evaluation`을 제외한다. Refiner 결과와
상태는 유지하고 trace·checkpoint의 전체 probe 기록은 변경하지 않는다. 실행 v19·probe/refiner r22로
올리며 evaluator e6·tools v7·checkpoint format 4는 유지한다. Evaluator 판단 기준과 refiner 경계의 추가
수정은 보류하고 reader·시간 기준·must_finish는 변경하지 않는다. 검증은 오프라인으로 한정하며 모델의
행동 개선을 입증하는 변경으로 보고하지 않는다.
