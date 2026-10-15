> 2026-10-15 KST 현재 계약: 실행 v24 / probe r24 / tools v7 / checkpoint format 6 (C42, v23·v24 보완).
> Orchestrator가 run 동안 대화 하나를 유지하고 tool call(`probe`·`execute`·`finish`)로 행동한다. Evaluator·state는
> runtime에서 빠졌다(`prompts/evaluator.py`는 미사용 파일로 남김). Worker의 대화·workspace 유지(C41)는 그대로다.
> 아래 C41의 evaluator·state·catalog 관련 부분과 2026-10-12 계약의 state 흐름은 C42로 대체한다.
>
> 2026-10-15 KST 이전 계약: 실행 v21 / probe r23 / evaluator e7 / tools v7 / checkpoint format 5 (C41).
> Worker는 run 동안 대화 하나와 workspace 하나를 유지하고 refiner는 없다. 아래 2026-10-12 계약 중 refiner·probe 격리·
> 저장된 지시 ID에 관한 부분은 C41로 대체한다.
>
> 2026-10-12 KST 계약: 실행 v17 / probe·refiner r20 / evaluator e6 / tools v7.
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
| C35 | perturbation 일관성 실험 2차 설정: 일관성 probe를 첫 노드에서 동점이 깨질 때까지 확장(동점인 worker만 다음 노드를 probe, 최대 전체 노드의 20%: easy 3·medium 7·hard 10개, 각 variant chain은 자기 답을 다음 노드로 넘김, 한도까지 동점이면 문제별 seed). worker를 luna·haiku·Gemini 3.8 Flash(Google Vertex 고정)로 바꾸고 셋 모두 effort medium(`luna-medium`, `haiku-medium`, `flash-medium`). 고른 worker의 호출을 OpenRouter Batch API(`--batch-workers`)로 보낼 수 있게 하고 기본 사용은 flash만(시험 실행에서 Anthropic batch 왕복이 17–25분 이상으로 너무 느리고, haiku·luna는 token 가격이 flash의 1/7.5라 batch 절감이 작음). 실패·만료된 batch의 요청은 2분 뒤 최대 4번 재제출. 문제는 seed 고정 무작위 추출(`--sample`, `--seed`) | 사용자 결정(2026-10-12): 첫 노드는 너무 쉬워 동점이 많음(easy 20/23, hard 19/26), 기존 gemini(3.1 Flash-Lite, effort minimal)는 다른 두 worker와 실력 차가 커서 3.8 Flash로 교체, high는 pilot에 비싸서 세 worker 모두 medium, easy 10·medium 20·hard 10. batch는 pilot 비용을 줄이려는 선택으로 token 가격이 절반. 대신 노드마다 batch 왕복(수 분~최대 24시간)이 필요하고, batch는 provider `only`·`allow_fallbacks`만 받으므로 `require_parameters`·`data_collection: deny`를 보낼 수 없음(`llm/specs.py`의 "service tier를 쓰지 않음" 원칙의 예외, 이 실험에 한정). batch 결과 body에 `usage.cost`나 provider가 없으면 token 수×표준가×0.5 추정·batch 고정 provider로 채우고 표시하며, 실제 청구액은 batch 단위로 `openrouter_batches.jsonl`에 기록 | src/perturbation_consistency/{batch,runner}.py, scripts/run_perturbation_consistency.py, llm/specs.py `luna-medium`·`haiku-medium`·`flash-medium`, llm/client.py `SERVED_PROVIDER_ALIASES` |
| C36 | perturbation 일관성 실험의 답 동치 판정 version 2(`longcot_math.EQUIVALENCE_VERSION`): LongCoT 공식 비교 전에 값을 바꾸지 않는 표기 변환(LaTeX 근호·로그·삼각함수를 sympy 호출로, `\text{}` 제거, 단독 수의 천 단위 쉼표, 원소 하나인 집합, 집합 앞 `x \in`). 공식 비교가 판정하지 못할 때만 집합은 순서 무시, tuple은 원소별, 닫힌 상수는 차이가 정확히 0(sympy strict evalf)인지로 일치 판정. 밑 없는 `\log`는 자연로그. "all integers n ≥ 13" 같은 서술형은 변환하지 않음 | LongCoT 파서는 LaTeX `\sqrt{}`·`\log`를 읽지 못해 같은 값이 문자열이 같을 때만 일치했음. 이전 node_0 probe에서 답이 갈린 사례의 약 절반이 표기 차이였음(trace 분석, 2026-10-12). 기록된 실행에 적용하면 probe 147개 중 8개의 일관성이 올라가고(만장일치 99→105), 정답 채점은 node 답 39건이 일치로 바뀜(14가지 표기 쌍 모두 수동 확인, 잘못된 일치 없음). float·상대오차 비교는 큰 수((2^2019−1)^2018 vs 3)와 아주 작은 차이(3^2021−2^2021 vs 거기서 1을 뺀 값)에서 잘못된 일치를 내서 쓰지 않음. 이미 보고된 분석은 version 1로 계산된 그대로 둠 | src/perturbation_consistency/longcot_math.py, manifest·summary의 `equivalence_version` |
| C37 | perturbation pilot: 어떤 perturbation이 worker 일관성을 정보 있게 만드는지 node 하나 단위로 비교. 대상은 답을 요구하는 node 중 의존 node도 모두 답을 요구하는 것(linear·dag, seed 고정, 문제당 하나): hard 첫 node 8·중간 node 8, medium 2·2. 중간 node에는 의존 node의 **정답을 입력값으로 넣음**(대상 node 자신의 정답은 넣지 않음). 조건 5개 × 3 sample × worker 3개: `repeat`(같은 prompt 반복, 대조군), `instruction`(단계별·계획·원리 지시), `surface`(Sonnet paraphrase, Given/Conditions/Find 재구성, 문제 주제와 관련 있지만 풀이에 필요 없는 참인 사실 한 문장 — Sonnet이 쓰고 참·문제 불변·힌트 없음을 따로 확인), `methods`(Sonnet이 낸 서로 다른 접근 3개를 하나씩 배정), `avoid_first`(처음 떠오른 방법을 적고 그 방법 없이 풀기). 모든 prompt 끝에 `method =`·`answer =` 줄. 재작성은 수식·숫자·placeholder 보존 검사와 Sonnet의 같은 문제 확인을 통과해야 하고, 두 번 실패하면 그 sample을 뺌 | 사용자 결정(2026-10-12): 소수 문제로 perturbation을 먼저 고르고 큰 set으로 확대, hard 위주, 조건당 3번, 재작성·접근 목록은 worker가 아닌 Sonnet 5.5. LongCoT는 요구된 node의 정답만 주므로 중간 node를 떼어 풀려면 의존 node 정답을 입력으로 줄 수밖에 없음(정답을 채점에만 쓰던 원칙의 예외, 이 pilot에 한정). 단일 node라 chain이 없어 worker 호출은 batch 왕복 한 번에 끝남 | src/perturbation_consistency/perturb.py, scripts/{prepare,run,analyze}_perturbation_pilot.py, llm/specs.py `sonnet-medium` |
| C38 | segment pilot: node 하나 대신 linear chain의 node_0부터 node_1–4 중 첫 요구 node까지를 한 묶음으로 한 번의 호출에 풀게 함(medium 13·hard 8, 해당 문제 전부). 채점은 마지막 node(정답 있음), 입력값으로 정답을 주지 않음. 응답 끝에 node마다 `node_i = …` 줄, `method =`, `answer =`(마지막 node). 변형은 묶음 전체 단위: `instruction`(단계별·chain 전체 계획·값을 넘기기 전 검산), `surface`(node label을 유지한 묶음 전체 paraphrase, Given/Dependencies/Find 재구성, 관련 note), `methods`(묶음 전체 진행 전략 3개), `avoid_first`, `repeat` 대조군. 재작성·전략은 Sonnet 5.5 effort high(`sonnet-high`). 수식·숫자·placeholder·node label 보존 검사, 같은 chain 확인, 수동 검토 후 실행. worker 출력 상한은 이 실행에서만 올릴 수 있음(`--max-tokens`) | 사용자 결정(2026-10-12): 단일 node pilot은 정답률 0.87–0.90으로 너무 쉬워 조건 차이를 볼 수 없었음. 묶음은 오류 전파 때문에 어렵고, 마지막 답에 정답이 있어 C32의 정답 입력 예외가 필요 없으며, "첫 확인 가능한 중간 답까지의 subtask"라는 RQ의 단위와 맞음. 묶음을 하나의 문제로 보고 계획·진행 방식을 흔드는 쪽이 node별 변형보다 목적에 맞음 | src/perturbation_consistency/segment.py, scripts/prepare_segment_pilot.py, scripts/run_perturbation_pilot.py `--max-tokens`, llm/specs.py `sonnet-high` |
| C39 | segment routing: linear chain의 첫 묶음(node_0부터 node_1–k 중 첫 요구 node까지, k = easy 8·medium 6·hard 4; easy 20·medium 14·hard 8, 해당 문제 전부)을 worker마다 조건 3개 × 5 sample로 probe(전부 batch). `repeat`, `instruction`(문제 뒤에 붙이는 고정 문구: zero-shot CoT, Plan-and-Solve+, step-back, analogical prompting, joint chain-of-verification), `surface`(Sonnet paraphrase, Re2 다시 읽기, 문제를 감싸는 형식 변경, 문제 순서 변경, GSM-IC식 무관한 문장 한 개 삽입). paraphrase와 무관한 문장은 자동 검사(paraphrase는 placeholder·node label·숫자 보존과 같은 chain 판정, 수식 문자열 비교는 화폐 기호 `$`·수식 분할에서 오탐이 나서 쓰지 않음; 무관한 문장은 삽입 위치와 검사 모델)와 수동 검토(점수 대상 정답과 같은 숫자가 든 문장도 탈락)를 거치고 item당 후보 최대 3개(자동·검토 탈락 포함), 끝내 통과 못 한 무관한 문장 4개는 Claude가 직접 써서 같은 자동 검사를 거침(`claude_manual`로 기록, 정답과 같거나 가까운 숫자 없음). probe 뒤 worker 셋 모두(`haiku-medium`, `luna-medium`, `flash-lite-high`) 자기 probe 답 15개의 최빈값에서 시작해 나머지 node를 하나씩 3번 반복 진행하고, 일관성으로 고른 worker·무작위·사후 최고는 이 실행에서 계산. 진행은 첫 틀린 요구 node에서 멈추고 이후 요구 node는 오답 | 사용자 결정(2026-10-12): 의미 있던 조건만 남기고 sample을 늘림, 변형은 학회 게재 기법에서 고름(Kojima NeurIPS 2022, Wang ACL 2023, Zheng ICLR 2024, Yasunaga ICLR 2024, Dhuliawala Findings ACL 2024, SPUQ EACL 2024, Re2 EMNLP 2024, FormatSpread ICLR 2024, BatchPrompt ICLR 2024, GSM-IC ICML 2023; step-back·CoVe는 한 번의 호출, 예시 없는 형태로 줄임). Gemini 3.8 Flash는 혼자 너무 강해 선택이 "Flash 고르기"가 되므로 Gemini 3.5 Flash-Lite(effort high)로 교체. 멈춤 판정을 위해 실행 중에 요구 node 정답을 읽음(모델에는 보이지 않음; 정답은 채점에만 쓴다는 원칙의 예외, 이 실험에 한정). 묶음 이후 node는 C29 고정 pipeline과 같은 variant 0 | src/perturbation_consistency/segment_routing.py, scripts/{prepare_segment_routing,run_segment_continuation}.py, llm/specs.py `flash-lite-high` |


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

## 2026-10-15 (KST): worker 대화 유지, probe는 이해·plan만, refiner 제거 (C41, v20/r23/e7)

사용자 결정. GAIA non-web 비교(2026-10-13 보고서)에서 공식 점수 차이는 adaptive 답에 붙은 단서에서 나왔다.
사용자 진단은 probe가 worker에게 assumptions·risks를 억지로 묻고, 그 답이 evaluator의 미검증 state와 refiner의
단서 요구를 거쳐 답까지 간다는 것이다. 가정·잘못된 이해·실패 위험은 원 질문을 아는 controller가 판단하고,
교정은 지시문 rewrite가 아니라 대화로 전한다. 전부 한 번에 바꾸고 기여도는 이후 ablation으로 나눈다.

| ID | 선택 | 이유 / 대안 | 위치 |
|---|---|---|---|
| C41a | 두 조건 모두 worker마다 run 하나에 대화 하나. Probe·execute request가 같은 대화에 순서대로 쌓인다. 첫 request만 원 질문을 담는다 | 사용자 결정(이후 execute·probe도 같은 대화). direct만 stateless로 두면 조건 차이에 대화 유지 효과가 섞임 | agents/worker, harness |
| C41b | Workspace는 `work/<worker_id>/`. probe scratch 복사와 web fork 제거. 다른 worker의 결과는 artifact context로만 전달 | 대화가 언급하는 파일이 실행에도 있어야 함. 공용 폴더 합치기는 이름 충돌 | harness |
| C41c | Request가 예외로 끝나면 대화는 그 request 이전으로 남고 실패 보고만 저장. Context window 초과도 같은 경로이며 대화를 자르지 않음. `workers[].conversation`에 이전 보고 ID와 최근 입력 토큰 수 | 사용자 결정(자르지 않고 실패로 기록) | agents/worker, harness |
| C41d | Probe는 understanding·plan 두 항목. 도구 최대 3회는 plan 단계 확인용 | 억지 가정·위험 목록 제거. 도구 횟수는 사용자 지시로 유지 | prompts/probe |
| C41e | Evaluator probe 평가가 plan의 오독·암묵 전제·실패 위험 단계를 찾고, 원 질문이 정한 조건은 가정이 아님을 명시. 실행·state 기준은 유지 | 판단을 controller로 이동 | prompts/evaluator |
| C41f | Refiner·`instruction.refined`·`instruction_id`·`instructions` 입력 제거. Orchestrator의 instruction은 `instruction` artifact로 저장하고, probe 뒤 execute의 instruction은 그 worker 대화의 다음 메시지로 교정·주의점을 전한다 | 사용자 결정(refiner 폐기) | harness, prompts/orchestrator, schemas |
| C41g | State·artifact 구조 유지. 걷어낸 것은 지시문 ID, 같은 worker 보고의 재선택 안내, probe 격리뿐 | Controller는 판단마다 새로 시작하므로 state가 유일한 기억. worker 간 전달과 근거 인용은 artifact로만 가능. 사용자 결정 | memory, prompts |

유지: finish 답 계약, "adaptive면 첫 행동 probe" 문장, 예산·한도, worker 도구·보고 4섹션, tools v7.
`REFINER_PROMPTS_VERSION` 이름은 probe 문구 버전으로 유지한다(r23).
v21: sanity 6 run(`2026-10-15_gaia-nonweb-conversation-sanity`)에서 orchestrator가 probe 초안에 "예상되는 모호함을
설명하라", "유일하게 정해지는지 설명하라"를 직접 넣었다. Plan만 묻는다는 결정과 어긋나므로 orchestrator의 probe
설명에 한 문장을 더한다: probe request가 이미 이해·plan을 묻으니 assignment는 실행용처럼 쓰고 모호함·가정·위험
질문을 덧붙이지 않는다. Direct 실행 지시와 evaluator 기준은 바꾸지 않는다. Checkpoint format 5는 worker별 대화·toolbox
상태를 저장하고 fingerprint에 포함한다. 과거 checkpoint는 변환하지 않는다. 오프라인 검사는 계약 동작만 확인한다.


Haiku 장문 요금 예약(C41 보완, 2026-10-15): 대화 유지 뒤 첫 72-run 배치(`2026-10-15_gaia-nonweb-conversation-comparison`)에서
haiku 요청이 116,816 입력 토큰에 도달했고, 이 크기에서는 입력·출력 모두 5배 단가가 청구됐다(92,588 토큰까지는 기본 단가).
비용이 예약 상한을 넘어 client가 `error_infra`로 끝냈고 runner의 안전 규칙이 남은 36 run을 건너뛰었다. 이 배치는
중단 기록으로 보존하고 같은 72 run을 새 디렉터리(`2026-10-15_gaia-nonweb-conversation-comparison-rerun`)에서 다시 실행한다.
`llm/specs.py`의 haiku 예약은 추정 토큰(byte bound / 1.8)이 92,000을 넘으면 장문 단가(입력 5e-7, 출력 2.5e-6)를 쓴다.
1.8은 haiku 호출 470개에서 관측한 최소 byte/token 비율 1.86보다 작다. 장문 예약 자체는 byte bound를 쓴다.
요청·모델 identity·도구는 바꾸지 않는다.

## 2026-10-15 (KST): evaluator 제거, orchestrator 대화 하나와 tool call (C42, v22/r24)

사용자 결정. v21 오답 21개를 trace로 읽은 결과([실패 유형 보고서](reports/2026-10-15-gaia-nonweb-failure-modes.ko.md)),
최종 답은 대부분 evaluator 판단이 정했다. Evaluator는 지금 도구로 채울 수 없는 출처·증명을 요구했고, 해석을 판단하는
방향이 run마다 달랐다. 사용자 진단: subtask를 만든 orchestrator가 그 의도를 가장 잘 아는데, evaluator가 중간에 끼어
context가 끊긴다. 자연스러운 interaction을 유지하고 인위적인 장치는 뺀다.

| ID | 선택 | 이유 / 대안 | 위치 |
|---|---|---|---|
| C42a | Evaluator·state·`read_memory`·catalog·`state_rows`를 runtime에서 제거. `prompts/evaluator.py`는 import하지 않는 파일로 남김 | 사용자 결정(삭제 말고 빼기) | harness, records |
| C42b | Orchestrator는 run 동안 대화 하나. 첫 user 메시지에 원 질문·worker·예산·answer format. 행동은 tool call `probe`·`execute`·`finish`이고, 결과로 보고 원문(보고 ID·worker·request 종류·status)과 남은 예산이 돌아온다 | 사용자 결정(tool calling, 기존 행동 이름 그대로) | agents/orchestrator, prompts/schemas |
| C42c | 메시지 하나에 tool call은 첫 번째만 실행, 나머지는 "Not run". 잘못된 인자는 오류를 tool 결과로 돌려주고 연속 2회면 run error. Tool call 없는 답은 한 번 다시 요청. 실행 한도 도달 시 `finish`만 제공하고 `tool_choice=required` | 기존 repair 1회와 같은 취지. 강제 finish는 특정 함수 지정 대신 도구를 하나로 줄여 client 변경 없음 | agents/orchestrator, harness |
| C42d | Orchestrator에게 worker를 `worker_1`, `worker_2`(pool 순서)로 보이고 model·가격·대화 토큰 수는 보이지 않음. 내부 기록은 실제 ID, 대응표는 run.json `worker_aliases` | 사용자 결정(익명화, 가격·토큰 제거) | harness |
| C42e | Orchestrator는 보고 원문만 본다. 도구 결과 원문은 저장만 함. 다른 worker 결과는 `artifact_ids`로 보고 원문을 context로 전달하고, instruction에 그 보고가 무엇이고 어떻게 쓸지 적는다 | 사용자 결정 | records, prompts/orchestrator |
| C42f | Worker 실행 보고는 자유 형식(`Title:`·4섹션 제거). Probe는 `understanding`·`plan` label 유지, `Title:` 제거, understanding은 "무엇을 묻고 어떤 조건이 적용된다고 이해했는지". 확인 중 드러난 답은 그 단계의 `observed:` 줄에 | 사용자 결정 | prompts/worker, prompts/probe |
| C42g | Orchestrator prompt: probe 응답에서 이해가 갈리면 지시가 모호했다는 뜻이니 뜻한 바를 밝히고, plan이 갈리면 유효한 다른 접근인지 결과를 못 내는 접근인지 따로 확인. plan의 전제(명시하지 않은 것 포함) 판단. 실행 지시는 "이해·plan이 뜻한 바와 다르면 뜻한 바를 말한다". Evaluator의 실행 평가 기준 중 필요한 것을 "Read the reports" 절로 옮김 | 사용자 결정. 판단을 지시한 주체에게 | prompts/orchestrator |
| C42h | Finish: `answer`는 항상 answer format의 값 하나. 해석이 갈리면 원 질문에 가장 잘 맞는 해석, 근거 한계와 고른 해석은 `rationale`에 | 사용자 결정(답 정책). 실패 분석의 더 강한 해석 원칙은 넣지 않음 | prompts/orchestrator |
| C42i | `memory.py`→`records.py`(`Records`), `controller.py` 삭제, 빈 `refine/` 삭제, `REFINER_PROMPTS_VERSION`→`PROBE_PROMPTS_VERSION`(run.json `probe_prompts_version`), `RunConfig.evaluator_model` 삭제 | 사용자 요청(파일 구조 정리). 과거 manifest의 `refiner_prompt_versions`는 script가 fallback으로 읽음 | src, scripts |

유지: worker 대화·workspace(C41a–c), probe 도구 3회, worker 도구, 예산·한도, 조건 이름, answer format, adaptive는
probe로 시작(문구는 "`probe` tool이 있으면 probe로 시작"), tools v7. Orchestrator의 instruction은 계속 `instruction`
record로 저장한다. Checkpoint format 6은 orchestrator 대화와 alias 대응표를 저장하고 fingerprint에 포함한다.
대화를 자르지 않는 규칙(C41c)은 orchestrator 대화에도 적용한다. Prompt 전체를 기존 구성·어조를 유지한 채 다듬었다
(사용자 지시: 모호한 표현을 구체적으로, 같은 대상에 같은 단어). 오프라인 검사는 계약 동작만 확인한다.

C42 보완(2026-10-15, 사용자 결정, v22 표적 재실행 뒤):
- v23: `probe`·`execute` tool에 `rationale`을 필수 인자로 추가한다. v22 22 run의 orchestrator 메시지 85개 중 tool call과 함께
  text를 쓴 것이 0개라 행동 선택 이유가 남지 않았다. `rationale`은 행동·delegation 기록과 trace에 저장한다.
- 305ac316(Polish Raymond → Magda M.), 5a0c1adf(Malko Competition)는 웹 조회가 필요한 사실 문제라 새 non-web 실험에서 뺀다
  (`run_nonweb_comparison.py`의 `EXCLUDED_TASKS`, 34문제). 같은 유형인 cf106601은 사용자가 지정하지 않아 유지한다. 이미 끝난
  36문제 실험 기록은 바꾸지 않는다.
- v23(같은 날, 사용자 결정 A): 한 메시지의 여러 `probe`·`execute` call을 순서대로 모두 실행한다(C42c의 "첫 call만 실행"을
  대체). v22에서 85개 메시지 중 6개가 두 worker에게 같은 실행을 동시에 보내 독립 확인을 하려 했고, 첫 call만 실행돼
  다음 메시지에서 다시 호출했다. 같은 메시지의 execute는 서로의 보고를 보지 않으며 call마다 실행 1회로 센다. 한도를
  넘는 call과 다른 call과 함께 온 `finish`는 오류 결과로 돌려주고 실행하지 않는다. Checkpoint는 행동마다 남은 행동 목록
  (`pending_actions`)을 저장하고, instruction record는 그 행동을 실행할 때 저장한다.
- v23(같은 날, 사용자 결정): orchestrator prompt가 실행을 맡길 때 등록된 worker 모두에게 같은 메시지에서 `execute`를
  부르도록 권장한다. 각 worker는 독립적으로 수행하고 orchestrator는 보고를 비교한다. 한 worker만 부르는 경우는 그 worker
  자신의 이전 보고에 관한 작업(예: 계산 단계 수정)이거나 남은 실행 횟수가 worker 수보다 적을 때다. Probe 뒤에는 각
  worker가 자기 plan대로 수행한다. 실행 횟수 한도(12)는 call마다 센다.
- Rate limit 처리(같은 날): HTTP 429는 OpenRouter가 과금하지 않으므로 client가 $0 확정으로 정산하고(과금 불명으로 세지
  않음), 일반 일시 오류와 별도로 최대 5회(15·30·60·120·240초 대기) 재시도한다. v22 표적 재실행에서 429 재시도가 과금 불명
  호출로 세여 runner가 남은 run을 건너뛴 일 때문이다. `run_nonweb_comparison.py`는 `--reps`(반복 수, 반복 단위로 순서
  배치)와 `--parallel`(동시 실행 쌍 수)을 받는다. 34문제 × 2조건 × 2반복(136 run)은 rate limit을 피하려고 한 번에 한
  run씩 실행한다(`2026-10-15_gaia-nonweb-v23-34tasks-2reps`).
- v24(같은 날, 사용자 결정): v23 34문제 × 2반복에서 adaptive 68 run 중 30 run이 같은 `probe`를 한 메시지에 두 번
  불러 각 worker가 같은 probe에 두 번 답했다("worker 모두 부르기" 권장을 probe에도 적용한 것으로 보인다). harness는
  한 메시지의 두 번째 `probe`를 실행하지 않고 오류 결과를 돌려준다. Orchestrator prompt의 probe 설명에 "probe는
  과제당 한 번 부르면 모든 worker에게 간다"를 더했다.
