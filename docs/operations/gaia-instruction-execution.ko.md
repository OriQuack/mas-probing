# GAIA non-web 첫 subtask instruction 비교

`gaia-instruction-execution-v1`은 orchestrator 밖 별도 실험이다. 기존 GAIA non-web 34문제에서
검토된 공통 첫 subtask와 naive·clarify·structured·verify를 비교한다. Probe와 instruction 선택은 없다.
각 문제·조건을 독립적으로 3회 실행한다(총 408경로). 후보는
`outputs/analysis/2026-10-15_gaia-nonweb-subtask-instructions-verify-v2/`에서 가져온다.

각 경로는 `haiku-medium`의 새 대화·workspace에서 시작한다. 첫 요청은 원 task, 공통 첫 subtask,
조건별 add-on이다. 두 번째 요청은 모든 조건에서 같은 완료 지시이며, 첫 요청의 대화·도구 결과·파일을
유지한 같은 worker가 원 task를 끝까지 푼다. 첫 요청에서 답이 나와도 공통 두 번째 요청을 수행한다.
이후 별도 orchestrator나 evaluator는 없다. category 지시는 첫 요청에만 추가하며 이전 대화에는 남는다.
GAIA 답 형식은 공통으로 제공하고 마지막 `Final answer:`를 extraction v1로 읽는다.

도구는 `read_file`, `view_image`, `run_python`이다. 각 요청 도구 20회, 경로 전체 도구 40회·LLM 100회·
3시간·$0.20 상한이다. 전체 금액 상한은 $81.60이며 예상 평균 비용이 아니다. 이미지 URL 조회는 이
standalone 실험의 local-only toolbox에서 차단한다(`v7-gaia-local-v1`, 경로별 별도 cache).
원 GAIA 정답과 Annotator Metadata는 준비·실행에서 읽지 않는다. 채점만 정답 열을 읽는다.

반복 단위로 실행하며 원 task 순서를 유지하고 조건 순서를 seed `1000*rep+task_index`로 섞는다.
한 번에 경로 2개를 시작한다. 첫 HTTP 429가 발생하면 영구히 경로 1개로 줄이고, 이미 실행 중인 경로의
후속 HTTP 요청도 파일 lock으로 직렬화한다. 이미 전송된 요청은 취소하지 않는다. 기존 client의 429
backoff를 유지한다. 과금 불명·인프라 오류 시 새 경로 시작을 중단하고 기록을 보존한다.
완료·오류 경로를 결과에 따라 다시 뽑지 않는다. 재개는 아직 시작하지 않은 경로만 실행한다.

실험에는 source/input hash와 src snapshot이 저장된다. 실행은 snapshot의 runner로 수행한다.
`planned.csv`, `batch.jsonl`, `progress.json`, 경로별 `run.json`·두 요청 결과·원본 trace를 보존한다.
모든 계획 경로를 채점하고 non-ok/missing은 실패로 센다. 반복을 문제 내에서 평균한 뒤 문제 동일 가중,
naive 대비 paired task bootstrap 95% CI를 보고한다. 탐색 표본이므로 독립 평가 집합 성능 주장이 아니다.

```bash
python scripts/run_gaia_instruction_execution.py prepare --experiment <new experiment> --source <reviewed candidates>
python <experiment>/snapshot/scripts/run_gaia_instruction_execution.py execute --experiment <experiment>
python <experiment>/snapshot/scripts/run_gaia_instruction_execution.py score --experiment <experiment>
```
