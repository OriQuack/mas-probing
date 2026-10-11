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
