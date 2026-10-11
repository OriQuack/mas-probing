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
