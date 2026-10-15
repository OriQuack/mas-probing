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

## 2026-10-13 (KST): 문제별 instruction 합의 선택 실험

사용자 확정 설계: 기존 segment-routing의 41개 대상에서 naive와 문제별 생성한 개념·유사 문제,
의미 명료화, 국소 검산 지시를 비교한다. Sonnet-high는 전체 문제문만 보고 후보를 생성하고,
worker 3명이 후보별 3회씩 첫 묶음을 푼다. 선택은 답 9개의 최대 동치 묶음 비율이며 최고 동점은
문제 ID와 seed 0에 따른 균등 무작위다. 교차 worker 일치율은 보조 분석이다.

사용자 후속 결정에 따라 각 후보의 전체 worker probe 답 9개 최빈값에서 haiku가 뒤 node를 3회
이어 풀며 해당 지시를 유지한다(`instruction-selection-v2`). 출발 답 동점은 worker 등록 순서와
sample 순서에서 가장 먼저 나온 답을 사용한다. 여러 worker의 답 결합 효과도 실험에 포함된다.
첫 틀린 요청 node에서 종료한다. 모든 후보를 실행해 naive·무작위·축별 고정·사후 최고와 비교한다.
사후 최고는 문제마다 3회 평균 점수가 가장 높은 후보 하나다. 후보 생성 실패와 누락 실행은 제외하지 않는다.
이는 probe 답 확보와 지시 선택의 합친 효과를 보는 탐색 실험이며 독립 지시 전이 검증은 아니다.

별도 `perturbation_consistency.instruction_selection` 모듈과 `scripts/run_instruction_selection.py`로 구현한다.
기존 orchestrator prompt 버전·실험 원본은 유지하고 새 실험 version, 후보 해시, 코드 snapshot을 기록한다.
이번 범위는 구현·오프라인 검증·dry-run까지이며 유료 실행 상한은 실행 시 필수 지정이다.
운영 절차는 [instruction 선택 실험](operations/instruction-selection.ko.md)을 따른다.

후속 사용자 요청으로 후보 생성도 현재 Codex 세션에서 직접 수행할 수 있는 session 모드를 추가했다
(`instruction-selection-v3`). 41문제의 첫 묶음 전문과 뒤 node 발췌문을 근거로 축별 지시 123개를
작성·자기 검토하고, 작성 주체·입력 범위·검토 기록·추가 API 비용 0을 기록해 가져온다.
별도 생성 모델을 호출한 결과나 독립 reviewer 검증으로 표시하지 않는다.
이후 probe·continuation은 기존 batch transport를 우선 사용할 수 있도록 준비한다.

외부 LLM 검토 피드백을 원문과 대조한 뒤 후보 r2에서 5개 지시만 수정했다: easy_1 clarify의
끝 두 자리 명시, hard_19 local_check의 임계값 방향 선가정 제거, medium_2 clarify·local_check의
급수 표기 점검 중립화, easy_2 local_check의 명시·정당화된 균등성 허용이다. 나머지 118개는 동일하다.
기존 고정본은 보존하고 `outputs/experiments/2026-10-13_instruction-selection-session-r2`를 준비했다.
medium_2 node_3의 원문 분모가 n=1에서 0이라는 표기 이슈는 별도 기록하며 원문 수정·문제 제외는 하지 않는다.
사용자가 선택한 실행 방식은 probe batch / continuation sync이며, 이 후보 수정 단계에서는 유료 호출하지 않았다.

### 2026-10-13: instruction-selection probe 수집 복구

기존 로컬 수집기 종료 후 원격 19개 batch를 GET으로 확인했다. 모두 in_progress이며 실패 기록은 없다. 종료 원인은 미확인이다. 동결된 실행 코드는 변경하지 않고 별도 GET 전용 collector를 Slurm CPU 작업 6132로 실행한다. 새 요청은 제출하지 않는다. 기존 미완료 128개의 random custom_id 대응 관계는 trace에 남아 있지 않으므로 추정하지 않고 원격 원본을 보존한다. 추가 1,220개는 영구 저장된 매핑으로 수집한다. 공동 sanity review 후 rollout gate를 유지한다. 상세: `outputs/experiments/2026-10-13_instruction-selection-session-r2/probe_remote_recovery/recovery_report.ko.md`.

### 2026-10-14: 매핑 유실 probe 128개 재제출

사용자의 명시적 승인으로 기존 미완료 128개 슬롯(Haiku 43, Flash-Lite 85)을 동일한 동결 prompt/worker 설정으로 재제출했다. 제출 전에 deterministic custom_id 및 전체 요청 매핑을 `probe_replacements/requests.jsonl`에 저장했다. 기존 매핑 유실 batch 16개는 원본 보존 및 분석 제외, 해당 슬롯에는 replacement 응답만 사용한다. 추가 호출의 보수적 최대 예약액을 포함하면 총 $62.8568로, 기존의 넉넉한 예산 지시와 추가 실행 승인에 따라 probe cap을 $70으로 조정했다. 예산 변경 및 제외 batch 목록은 `probe_replacements/authorization.json`에 저장했다. GET 전용 collector는 새 source를 지원하도록 갱신하고 Slurm으로 재시작한다. 공동 sanity check 전 rollout 금지를 유지한다.

## 2026-10-14 (KST): MoNaCo oracle 설정 문제별 instruction 합의 선택 (C40)

> 현재 설계(v7)의 정본은 [운영 문서](operations/monaco-instruction-selection.ko.md)다. 이 절은 결정과 이유의 시간순
> 기록이라 앞 문단의 설정(규칙 정규화 합의, judge `luna` effort none 등)은 뒤 문단에서 바뀌었다.

사용자 결정. LongCoT `instruction-selection-v3`의 후보 4개·worker 3명×3회·최대 동치 묶음/9 선택·seed 동점 규칙을
MoNaCo로 옮긴다(`monaco-instruction-selection-v1`). 질문과 oracle 문서만 주고 문제 전체를 한 번에 푼다.
gold decomposition과 node 분할은 쓰지 않는다. Oracle 문서는 공개된 gpt-4o oracle 실행의 `input_documents`다.
대상은 시간 비의존·문서 4만 글자 이하 pool 540개에서 seed 0으로 20문제다. 평가는 probe와 분리해 haiku-medium이
후보마다 3회 새로 실행한다. 같은 표본으로 선택·평가하면 점수가 낙관적으로 나오기 때문이다. 채점은 공개 judge
prompt 두 종류를 그대로 쓰고 judge는 비용을 낮추려고 `luna`(effort none)로 한다. 공개 채점의 두 결함
(셈 gold 0/1의 Yes/No 표기, `###` 앞 빈 항목 계산)은 따르지 않는다. 답 동치는 숫자의 부호·소수점을 유지하고
구두점을 일괄 삭제하지 않는 정규화 집합 비교다. 기존 LongCoT 코드는 수정하지 않고 importlib로 재사용한다.
운영 절차는 [MoNaCo instruction 선택](operations/monaco-instruction-selection.ko.md).

같은 날 사용자 지시로 seed 20문제와 겹치지 않는 2문제(805, 1250) end-to-end 점검을 sync로 실행했다. 후보는
이 세션이 질문만 보고 작성·자기 검토했다(session 모드). 단계 누적 상한은 judge 검증 $0.2, probe $3, 실행 $1,
judge $0.5, 호출당 $0.15였고 기록 비용은 약 $0.27이다. HTTP 429 실패 slot이 선택을 바꾼 것, 답 형식 차이로
합의가 깎인 것, 근거 요구 instruction의 답 보류·과소 집계를 확인했다. 결과는
[2문제 점검 보고서](reports/2026-10-14-monaco-instruction-selection-e2e.ko.md). 20문제 본 실행은 하지 않았다.

점검 후 사용자 결정으로 `monaco-instruction-selection-v2`로 바꿨다. (1) 답 동치는 규칙 정규화 대신 문제당
`luna`(effort none) 한 번 호출로 그 문제의 probe 답 36개를 묶는다. 입력은 질문과 서로 다른 `ANSWER:` 줄 원문만이며
순서는 seed로 섞고 worker·후보는 표시하지 않는다. 규칙 정규화 합의는 진단용으로만 남긴다. (2) client 재시도 후에도
실패한 호출(`error`)은 재실행 때 다시 하며 slot당 최대 3번이다. 기록은 덧붙이기만 하고 slot의 마지막 기록을 쓴다.
(3) 429를 줄이려고 sync 동시 실행 기본값을 12에서 4로 낮췄다. Worker prompt와 정규화는 바꾸지 않았다.
같은 날 사용자 지시로 묶기를 공개 답 쌍으로 검증했다(기록 비용 $0.011).
[묶기 검증 보고서](reports/2026-10-14-monaco-answer-clustering-validation.ko.md).
이어 사용자 결정으로 judge와 묶기 모델을 `luna-low`(effort low, 새 spec)로 바꿨다(`monaco-instruction-selection-v3`).
v3로 seed 20문제·이전 점검과 겹치지 않는 중간 난이도 2문제(1707, 910; 공개 GPT-4o·Llama oracle 평균 점수
0.4–0.8, 최고 0.6 이상) end-to-end 점검을 sync로 실행했다. 후보는 sonnet-high가 생성했다. 기록 비용 $0.61.
[중간 난이도 2문제 점검 보고서](reports/2026-10-14-monaco-instruction-selection-e2e-hard.ko.md).
점검 결과에 따라 사용자 결정으로 `monaco-instruction-selection-v4`로 바꿨다. (1) 답 파싱은 마지막 `ANSWER:`
뒤 JSON 값을 읽는다(여러 줄 허용, 값 하나는 한 항목 목록). (2) 목록 답에서 완전 일치 합의가 2/9 동점으로
무너져 합의를 항목 단위로 잰다. luna-low가 문제당 한 번 probe 답의 항목을 같은 대상끼리 묶고, 후보 점수는
가장 중심인 답의 9개 slot(자신 포함) 평균 항목 F1이다. 항목 하나짜리 답에서는 최대 묶음/9와 같다.
(3) probe 36개 답의 항목 다수결 답을 비교 정책으로 넣었다가 실행 전에 사용자 결정으로 뺐다. instruction 4개와
worker 3종을 섞은 앙상블이라 instruction 하나의 효과를 재는 이 실험의 질문에 답하지 않는다.
같은 날 사용자 지시로 v4 20문제 본 실행을 sync로 실행했다(기록 비용 $3.51). 단계 누적 상한은 judge 검증 $0.2(첫 시도
$0.05는 동시 예약액보다 작아 재실행), 생성 $1.5, probe $4, 묶기 $0.2, 실행 $0.6, judge $0.3이다. 미리 정한 규칙을 바꾸지
않았고, 행 안 목록 답 허용과 빈 답 처리는 사후 분석으로만 보고했다.
[20문제 본 실행 보고서](reports/2026-10-14-monaco-instruction-selection.ko.md).
본 실행에서 목록 judge prompt가 응답 전체의 답 수를 세게 되어 있어, luna-low가 실행 응답의 근거·제외 절 항목까지 셌다
(같은 최종 답이 0.31–0.67로 갈림). 사용자 결정으로 `monaco-instruction-selection-v5`에서 judge를 `luna-high`로 바꾸고,
judge에는 파싱한 최종 답을 `ANSWER:` 한 줄로 넘긴다(파싱 실패만 원문). 공개 프로토콜은 원문을 넘기지만 공개 답은 자유
문장이고 우리 답은 JSON 목록이라 최종 답만으로 채점할 수 있다. 같은 실행 240회를 재채점했다
(`scripts/rejudge_monaco_instruction_selection.py`, $0.07). 분석에 사후 최고의 무작위 섞기 기준선(`hindsight_null`)을
더했다. 사후 최고 − naive를 0과 비교하면 선택 편향 때문에 headroom을 과대평가한다.
사용자 요청으로 probe 답 720개도 같은 judge로 채점했다(`scripts/judge_monaco_probes.py`, 분석 전용, $0.21). gold를 읽으므로
선택에는 쓰지 않고, 합의가 probe 정답을 못 가리키는지와 probe 정답이 실행으로 안 이어지는지를 나누는 데만 쓴다.
사용자 결정으로 `monaco-instruction-selection-v6`에서 목록 점수의 recall을 1로 제한한다(겹친 수를 gold 값 개수 이하로).
judge가 gold보다 많은 겹친 항목을 내면 점수가 1을 넘었다(원래 judge 실행 2건, probe 2건; 재채점 실행 0건). 기록된
judgement는 그대로 두고 영향은 저장된 judge 응답으로 다시 계산해 보고서에 적었다.
**v5와 v6는 하나로 합쳐 분석한다.** v6의 변경은 recall 상한이라는 작은 버그 수정이고 결과에 주는 영향은 무시할 수
있다(재채점 실행 0건, probe 채점 결과 0.001). 따라서 v5 재채점 20문제와 v6 추가 문제를 같은 실험의 문제로 합쳐 보고,
v5 쪽은 다시 실행하거나 재채점하지 않는다. 사용자 결정(2026-10-14).
같은 날 사용자 지시로 v6 30문제를 추가로 전체 실행한다(sync, `2026-10-14_monaco-instruction-selection-extra30`).
대상은 pool 540개에서 이미 쓰거나 점검한 126문제(본 실행 20, 묶기 검증 100, 점검 805·1250·486·415·910·1707)를 뺀
414개 중 seed 1로 30개다(정렬한 목록에서 `random.Random(1).sample`). gold는 보지 않고 골랐다. 단계 누적 상한은 judge
검증 $0.5, 생성 $2, probe $8, 묶기 $0.5, 실행 $1.5, judge $0.5, probe 채점 $0.6이다. 처음 20문제에서 고른 가설
(항상 clarify, probe 점수로 고르기)은 이 30문제에서 따로 확인하고, 합친 50문제 결과는 별도로 보고한다.
실행 비용 $4.48(probe 채점 포함). 두 가설 모두 재현되지 않았다(clarify −0.027, probe 점수로 고르기 +0.008).
[추가 30문제·50문제 합산 보고서](reports/2026-10-14-monaco-instruction-selection-extra30.ko.md).
사용자 결정(2026-10-14)으로 `monaco-instruction-selection-v7`에서 답 형식과 대상을 바꾼다. 목적은 oracle 설정의
instruction headroom 확인이며 대상 선정에 gold 기반 정보를 써도 된다. (1) 답 형식은 JSON 목록 대신 자유 서술 뒤 마지막
`Answers:` 줄이다(공개 실행 출력과 같은 꼴). JSON 형식은 v1의 규칙 비교 합의를 위해 넣은 것이었고, yes/no 질문에 항목
이름(1809)·개수 질문에 목록(559, 1700)을 내게 하는 부작용이 있었다. judge에는 답 줄만 넘긴다. (2) 합의용 항목은 문제당
`luna-low` 한 번으로 답 줄을 나누고, 항목이 줄의 그대로인 연속 구간이며 나머지가 구분자뿐인지 코드로 확인한 뒤 기존 항목
묶기를 쓴다. 확인에 끝내 실패한 줄은 실패 slot이다. (3) 대상은 pool 540문제 전체(이전에 쓴 문제 포함)에서 공개
GPT-4o·Llama-3.1-405B oracle 점수 평균이 0이나 1인 문제를 빼고 층화한 50문제다. 목록 5구간 × 6(gold 값 100개 초과
제외), 단일 답은 한 실행만 맞힘·부분 점수 × 10. 앞의 50문제에서 공개 점수 평균과 haiku naive 점수의 Spearman 상관은
0.76이었고, 후보 간 점수 차이는 0.4–0.8 구간에서 가장 컸다(0.22, 0.8 이상 0.08). (4) 후보는 수학용 세 축 대신
문서 QA 기법에 근거한 decompose(Least-to-Most), clarify(Metacognitive Prompting, 해석만), structured(Tab-CoT)다.
v6 후보 50문제 분석에서 local_check는 recall을 깎았고(빈 답 아닌 목록 실행 recall 0.557, naive 0.626), 생성기가
질문만 보고 넣은 해석(282 "empire", 443 "received")이 항목을 뺐다. 지시는 질문만 본 작성·검토 subagent가 쓰고,
사용자가 데이터셋 수준 규칙(amendment 2: 용어는 보통 뜻으로, 범주·조건 묶음으로 행을 거르는 표 열 제거, 맥락이 보여 주는
조건은 충족)으로 50문제에 같이 고쳤다. 이 규칙은 이전 결과를 보고 정했고 적용한 세션은 층 표를 봤다(문제별 결과로 고친 것
아님). 작성 기록은 `outputs/analysis/2026-10-14_monaco-method-instruction-candidates/`. 생성 모드(sonnet-high)는 없애고
`import-candidates`만 둔다. 실행 횟수(3회)는 바꾸지 않았다. v6 이전 결과와 합치지 않으며, 합산 분석 스크립트는 v5·v6
후보 이름으로 고정했다(기존 합산 결과를 그대로 재현함을 확인). 이번 범위는 구현과 오프라인 검증이며 유료 실행은 하지
않았다.
같은 날 사용자 지시로 v7을 sync(동시 2, 429가 나면 1, 그래도 나면 2시간 쉼)로 실행한다. batch는 쓰지 않는다. 먼저 50문제 중
459(목록)·1018(단일) 2문제로 전 단계를 돌려 확인하고, 통과하면 50문제 전 단계를 돌린다. 첫 sanity 디렉터리
(`2026-10-14_monaco-instruction-selection-v7-sanity`, judge 검증 2·probe 10회 기록)는 재시도 규칙을 바꾸려고 멈췄고 그대로
둔다. 사용자 결정으로 재시도 규칙을 바꿨다: probe는 오류·길이 초과·답 줄 없음을 한 번 다시 하고, judge·나누기·묶기는 실패한
호출과 형식이 틀린 응답을 3번까지 다시 한다(4번 시도). 실행은 오류만 다시 한다. 단계 누적 상한(본 실행)은 judge 검증 $0.5,
probe $25, 나누기 $2, 묶기 $1, 실행 $4, judge $1.5이고 호출당 $0.05–0.15다.
결과(2026-10-14 실행 완료, $9.54): 합의 선택 0.657, naive 0.655(+0.002, CI −0.030–+0.041). 사후 최고 +0.054는 잡음 기준선 +0.047과 구분되지 않는다. 목록 문제에서 합의율은 점수를 예측하지 못했고, 손실 대부분은 목록 수집·수 세기와 문서 밖 gold였다. [v7 보고서](reports/2026-10-15-monaco-instruction-selection-v7.ko.md).

### 2026-10-14: probe collector Slurm checkpoint 및 최대 5회 재큐잉

사용자 요청으로 사용자 서비스를 중지하고 Slurm 작업 6142로 수집을 전환했다. 6시간 allocation 종료 120초 전 B:USR1을 받아 collector에 USR1을 전달하고 checkpoint 저장·정지 후 scontrol requeue를 실행한다. SLURM_RESTART_COUNT < 5인 경우만 재큐잉한다(초기 실행 + 최대 5회). checkpoint는 batch ID, 영구 request map 경로, 수집 건수 및 재시작 횟수를 저장한다. 재실행은 기존 journal을 읽고 GET으로만 수집하며 이미 저장된 슬롯을 건너뛴다. GET timeout을 연결 5초/읽기 20초로 제한해 신호 후 정지 시간을 확보했다. 오프라인 신호/checkpoint 테스트와 별도 모델 호출 없는 Slurm 재큐잉 권한 테스트를 수행했다. 공동 sanity review 전 rollout gate는 유지한다.

### 2026-10-14: Gemini 서버 실패 407개 및 길이 제한 24개 일괄 재시도

사용자 명시 요청으로 flash-lite-high 431개를 256/175개 두 batch로 한 번씩 재제출했다. 기존 saved body와 provider pin을 그대로 재사용하여 토큰 상한 32768과 reasoning high도 유지한다. 길이 제한도 재시도하므로 최초 결과와 재시도 결과를 구분해 보고한다. 기존 results.jsonl과 trace는 덮어쓰지 않으며 retry 요청/결과는 probe_retry_431/에 보존한다. 분석용 effective_results.jsonl은 재시도 대상 슬롯의 기존 실패를 제외하고 재시도 결과를 성공 여부와 무관하게 채택한다. 재시도 완료 전에는 해당 슬롯을 미완료로 둔다. select/rollout은 기존 results.jsonl을 직접 읽으면 안 되고 공동 sanity review에서 effective_results 입력 연결을 확인한 후 진행해야 한다. 추가 최악 예약액은 $35.6011, 모든 기존 요청과 재시도를 포함한 보수적 최대 예약액은 $98.4579로, 추가 실행 승인에 따라 probe cap을 $110으로 기록했다. 기존 실패 batch의 실제 과금 여부는 여전히 미확인이다. Slurm 작업 6142를 checkpoint 후 재큐잉해 새 수집 코드를 로드한다. GET-only 및 최대 5회 재큐잉 제한을 유지한다.

### 2026-10-14: Haiku 재제출 43개 즉시 sync 및 406개 조건부 예약

사용자 승인으로 Haiku 재제출 43개는 기존 batch를 분석에서 무시하고 동일 prompt/model 설정의 sync로 전환한다(Slurm 6155, 동시 4개). 나머지 406개는 오늘 21:25 KST 이후 원격 batch 상태를 확인한다(Slurm 6156). 그때도 처리 중이면 종료 상태까지 조회만 반복하며, batch status expired 또는 completed의 개별 error.type=expired인 슬롯만 sync로 실행한다. 성공한 batch 응답과 다른 종류 오류는 재실행하지 않는다. sync 활성화 슬롯의 분석에는 sync 결과만 사용하며 원래 batch/trace는 보존한다. 추가 sync 예산 상한은 두 작업 합계 $11(43개 $2, 406개 $9)로, 이전 보수적 예약 상한 $98.4579와 합쳐 기존 probe $110 cap 안에 둔다. sync client 기본 transient 재시도 2회와 기존 validation을 사용한다. 이미 시작됐지만 결과가 없는 sync 슬롯은 재실행하지 않고 별도 검토한다. 원래 결과·retry journal을 보존하며 effective_results.jsonl은 공용 파일 lock으로 재생성한다. frozen 실험 코드는 변경하지 않는다. 예약·개별 만료 판별·동일 본문·중복 방지·sync 우선 반영은 오프라인 검증했다. 공동 sanity review 전 rollout gate를 유지한다.

### 2026-10-14: probe 실행 sanity 점검 및 90개 단일 재시도

사용자가 sanity check와 문제 슬롯 재시도를 명시 승인했다. effective 1476개 전체에서 누락/중복/예상 외 슬롯, 동결 해시, 실제 prompt-message 대응, worker 설정/슬롯 대응, 원본 출력 재파싱과 164개 묶음의 9표/support 일치를 검사했으며 구조 오류는 0건이다. endpoint 비교 경고 64건을 정답 없이 검토했다. 부연설명/표기/기호치환 차이는 재실행하지 않고 유지한다. 요청한 node의 encoded answer 대신 중간 기하 비율을 node 줄에 쓴 2건만 형식 문제로 포함했다. length 87개, no_answer 1개와 합계 90개(Haiku36, Gemini54)를 동결된 동일 body로 1회 sync 재시도한다(Slurm6159, 동시4, round budget$9). 최초 실패·원본 trace·effective snapshot은 보존하고 새 시도는 성공 여부와 무관하게 최상위 유효 결과로 반영한다. 이전 보수적 예약+sync cap+이번 cap 합계가 $120 이내이므로 추가 승인에 따른 probe 총상한을 $120으로 기록한다. 기존 batch 수집 작업6142는 필요한 probe 수집 완료로 종료했다. 재시도 후 post_retry_sanity를 자동 저장하며 공동 검토 전 continuation gate를 유지한다. 상세: probe_sanity_review/baseline_audit.json 및 probe_sanity_retry/authorization.json.

### 2026-10-15: 최종 probe snapshot에서 sync continuation 시작

최종 sanity 보고를 사용자와 확인한 뒤 기존 실행 승인에 따라 continuation을 시작했다(Slurm6162, Haiku sync, 동시4, 총492 rollout, 단계$60/rollout$3). 길이 제한40개는 실패 표로 유지하며 후보별 분모9를 바꾸지 않는다. 원래 runner는 results.jsonl을 읽으므로 raw 실패 기록과 혼동하지 않도록 새 파생 실험 `2026-10-15_instruction-selection-session-r2-continuation`에 effective_results를 불변 results.jsonl snapshot으로 복사하고 그 해시도 manifest frozen_hashes에 추가했다. 원래 기록은 수정하지 않았다. 기존 동결 구현으로 41개 선택과 164개 후보 시작값을 계산하고 최종1476개로 전수 재계산하여 일치를 검증했다. 각 후보의 전체9개 최빈값에서 시작해 같은 지시를 유지하며 첫 요청 node 오답에서 종료한다. 원래 probe 비용과 재시도 이력은 부모 실험에 남아 있으며 파생 실험 분석에서 별도 합산해야 한다. Slurm 종료120초 전 완료 결과와 trace 위치를 checkpoint한 뒤 최대5회 재큐잉한다. 미완료 rollout은 기존 runner 정책대로 처음부터 재실행하고 이전 비용노출도 예산에 포함한다.

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


### 2026-10-15: continuation 종료 후 무인 monitor 및 간단 분석

사용자가 부재 중에도 continuation 종료 후 간단 분석을 진행하도록 명시 승인했다. 읽기 전용 Slurm monitor6164를 60초 간격으로 구성했고 최대5회 재큐잉한다. 분석6165는 continuation6162의 afterany dependency로 등록했다. 종료 후 동결 해시/선택 provenance/시작값/누락·중복을 확인하고 기존 고정 분석 함수를 실행한다. 분석은 문제 단위 가중치와 paired bootstrap CI를 유지하며, 결과·node순서 plot 및 간단 한국어 보고서를 analysis/brief.ko.md에 저장한다. 작업 실패로 미완료이면 보고서를 잠정으로 명시한다. 부모 probe 비용에서 batch journal과 terminal archive를 batch ID로 중복 제거하고 sync 비용을 별도로 합산한다; 미제공 청구는 0이 아닌 미확인으로 보고한다. Monitor/분석은 추가 모델 호출을 하지 않는다. 오프라인으로 결과 해석 분기·미완료 표시·비용 중복 방지·미확인 과금 보존을 검증했다.

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

## 2026-10-15 (KST): GAIA non-web 첫 subtask instruction 3반복, probe 없음

사용자 결정. 기존 non-web 34문제의 세션 subagent 작성·검토 첫 subtask를 고정하고, subtask만 보고 작성한
clarify·structured·verify와 naive를 각 3회 비교한다. decompose는 작은 subtask에서 개입 여지가 작아
verify로 교체했다. 작성 revision 1과 verify revision 2는 그대로 보존한다. Probe나 합의 선택은 하지 않는다.
`haiku-medium` 한 worker가 첫 subtask를 수행한 뒤 동일 대화·workspace에서 공통 완료 지시로 원 task를
끝까지 푼다. 두 요청을 합친 경로당 $0.20, 전체 408경로 $81.60 상한. 병렬 2경로로 시작하며 첫 429부터
1경로와 직렬 API 요청으로 줄인다. 기존 전체 orchestrator framework는 변경하지 않는다.
세부 설계와 실행·채점은 [운영 문서](operations/gaia-instruction-execution.ko.md)에 기록한다.
