> 현재 비교는 `direct_execution`과 `adaptive_probe`다. Probe 뒤 자동 실행하지 않는다.
> Execute 최대 12회, probe 별도 집계. Probe 라운드와 refinement 각각 $1/LLM 60회 보조 상한.
> Format 3 checkpoint는 행동 수행 전 `aN`에 저장하며, 조건에 맞지 않는 pending action은 거부한다.
> 아래 과거 실험과 snapshot은 당시 조건 의미로 해석한다. 새 성능 효과는 평가하지 않았다.

# 실험·용어·산출물 안내

## 서로 다른 축

| 용어 | 정확한 의미 |
|---|---|
| experiment | 하나의 목적과 비교 설계를 가진 실행 묶음. 폴더와 manifest로 식별 |
| batch | `run_batch.py` 한 번의 실행. 하나의 experiment에 여러 batch가 있을 수 있음 |
| run | 한 문제를 한 조건으로 한 번 실행한 기록 |
| condition / arm | 비교 조건. 조건과 fresh/restore, pool, override 여부를 함께 구분 |
| replicate | 같은 조건의 반복. 기존 label의 `_r0`, `_r1`은 반복 번호 |
| fresh / restore | 처음부터 실행 / 선택한 행동 직전 checkpoint에서 재개 |
| delegation | execute 한 번. 최대 12회이며 probe는 소비하지 않음 |
| action / a0 | probe·execute 공통 행동 번호 / 0부터 센 첫 행동. Checkpoint 경로에 사용 |
| executor / probe worker | 선택된 실행 worker / 독립 probe에 답하는 pool worker |
| context / instruction | 이전 보고 정보 / 현재 작업 지시 |
| trace stage | `orchestrator`, `probe`, `evaluator.probe`, `refiner`, `execution`, `evaluator.execution` |

과거 실험의 stage 1~4, Phase A/B는 실험 진행 순서였으며 trace의 `stage`와 무관합니다.
새 실험은 순서 대신 **목적을 이름에 씁니다**. 이름만으로 모델·프롬프트·도구 조건을 추측하지 않습니다.

## 현재 조건과 버전

| 조건 | 실행 |
|---|---|
| `direct_execution` | 작업·context·executor 선택 → 실행 → evaluator의 state 갱신 |
| `adaptive_probe` | probe / execute / finish / read_memory 선택 → probe 평가·state 갱신 → refiner → 다음 판단; execute는 실행 평가 후 판단; 첫 probe는 prompt 지시 |

Orchestrator·evaluator·refiner는 `luna-high`를 별도 호출합니다. 초기 `multi` pool의 `gen_luna`, `gen_haiku` 모두
executor 후보입니다. 다른 pool도 등록 worker 전체를 공개합니다. 역할별 고정 executor는 없습니다.
사전 verification, 후속 probe, self_review, connected variant는 현재 runtime에서 지원하지 않습니다.
`configs/conditions/`가 현재 설정이며 `configs/refiners/`는 과거 preset을 식별하는 자료입니다.
이전 CLI `--refiner`, `--refiners`, `--refine-at`, override 옵션을 새 의미로 재사용하지 않습니다.

| 식별자 | 현재 값 | 복원 |
|---|---|---|
| 실행 | `v18` | 동일 버전만 |
| Probe/refiner | `r21` | 동일 버전만 |
| Evaluator | `e6` | 동일 버전만 |
| Tools | `v7`, `tools_v7.sqlite` | 도구 설정 동일; 기존 cache 유지 |
| Checkpoint | format 4 | 행동 선택 후/probe 또는 실행 전; instruction artifact·선택 ID 보존; 과거 format 변환 없음 |

Artifact 원본·state 교체 전후·context 선택 snapshot·executor 선택 이유·evaluator 갱신 근거·실제 지시·도구 원문을
trace로 연결합니다. `render_trace.py`는 해당 이벤트와 모델/도구 호출을 표시합니다. 비용은 모든 단계·재시도·
조회·실패 호출을 포함합니다. `score_runs.py`의 기존 `refine_usd`는 과거 의미를 유지하며 현재 실행에는
`probe_usd`, `refinement_usd`, `n_probes`, `evaluator_usd`, Serper billed/unknown credit 열을 추가합니다. 전체 비교는 `cost_usd`를 봅니다.

Run 상한은 위임 12회, LLM/도구 각각 400회, $5, 3시간입니다. Probe 라운드와 probe 평가 후 refinement 각각의 보조 상한은 LLM 60회/$1입니다.
Serper는 task당 100 credits이며 probe와 실행·재시도를 합산하고 cache는 제외합니다. 429 등의 비과금 응답과
과금 불명 시도를 구분합니다. Unknown은 한도의 여유를 소비하고 알려진 청구 비용과 별도로 기록합니다.
한도 이후 cache/무료 fallback이 가능하며 제한 상태를 입력과 trace에 표시합니다.

이전 v10/r12 및 그 이전 조건·checkpoint는 당시 snapshot으로 재현합니다. 아래 과거 이름 대응은 원본 기록을
읽기 위한 것이며 현재 runtime preset이 아닙니다. 과거 실행·snapshot·cache는 수정하지 않습니다.

## 과거 이름 대응

| 과거 이름 | 지금 찾을 곳 / 의미 |
|---|---|
| stage 1 / stage 2 / c2-insight | 폐기한 초기 refiner·도구 탐색. 요약 이력만 유지 |
| stage 3 v5 / v6 | baseline-original-reporting / baseline-interpretation-reporting |
| stage 4 / s4 | probe-condition-comparison (Serper, 47문제 × 3조건) |
| Phase A / rA | refiner-regression-check (기존 초안, 선택 7문제 × 3조건 × 2회) |
| Phase B / rB | updated-prompt-diagnostics (선택 8문제, fresh와 restore, 추가 재시도) |
| A / A_none | baseline |
| c1_self_review | self_review |
| c2_probe_executor | executor_probe |
| c2_probe_tools | executor_probe_tools |
| c3_probe_multi | adaptive_probe |
| 역사적 B / C | 예측 응답 / 실제 응답. 당시 버전은 기록을 확인; 현재 preset과 동일하다고 가정하지 않음 |
| r5 | 삭제한 과거 refiner 구현. 현재 코드에서 선택 불가 |

### 과거 실험을 다시 쓸 때

- **채점·짝지은 비교:** 원본 run의 `condition`은 당시 이름(`A_none`, `c2_probe_tools`, `c3_probe_multi` 등)으로
  남아 있습니다. 과거 실험에 `score_runs.py --compare`를 쓸 때는 당시 이름을 씁니다
  (예: `--compare A_none c3_probe_multi`). 기록에 없는 이름을 주면 비교 결과가 출력되지 않습니다.
- **Restore:** `run_batch.py --checkpoints`와 `run_task.py restore`는 이동 대응표를 쓰지 않고 주어진 경로를
  그대로 엽니다. 과거 실험의 `cks*.txt`는 정리 전 `outputs/sessions/...` 경로이므로 먼저 현재 경로로 바꿉니다.
  현재 코드(v18)에서는 기존 v7 `2026-10-10_updated-prompt-diagnostics/base`의 checkpoint도 restore할 수 없습니다. 당시 코드 snapshot을 사용하거나 v18로 새 checkpoint를 생성해야 합니다.

```bash
while read -r ck; do python scripts/experiments.py resolve "$ck"; done \
  < outputs/experiments/2026-10-10_updated-prompt-diagnostics/cks.txt > checkpoints.txt
```

## 산출물 규칙

```text
outputs/experiments/<date>_<purpose>/
  manifest.json          목적, 조건, prompt 버전, run_roots, 설정
  planned.csv            계획한 모든 실행; 누락도 채점 분모에 포함
  batches/<timestamp>/  배치별 인수와 code_snapshot.tar.gz (기존 실험은 root snapshot)
  runs/<task>/<run>/     원본 trace, run.json, work, checkpoint, refine
  analysis/              해당 실험의 보조 분석
  logs/                  실행 프로세스 로그
```

기존 복합 실험은 manifest의 `run_roots`가 `base/runs`, `restore/runs`, `restore_serper_redo/runs`를 가리킵니다.
원본 실행 안의 과거 label·절대경로는 출처 정보로 유지했습니다. 이동 위치는 다음 명령으로 찾습니다.

```bash
python scripts/experiments.py list
python scripts/experiments.py resolve outputs/sessions/<old-experiment>/runs/<task>/<run>
python scripts/experiments.py verify
```

보존된 주요 실행은 317회입니다. 각 실험의 `checksums.json`에 원본 실행 파일 해시가 있습니다.
전체 보존·이동·삭제 목록은 [retention.json](reports/retention.json)입니다.
오래된 초기 탐색, 중단된 비교, 동일한 raw trace 복사본과 ZIP을 제거했습니다.
도구 cache는 실행 원본과 별개로 유지합니다.

새 실험도 목적·조건·원본 실행 위치를 manifest에 기록합니다. `run_batch.py`가 자동 작성합니다. 여러 batch를 추가해도 snapshot은 배치별로 유지합니다.
임시 중간 결과는 실험 폴더 안에 두고, 읽을 보고서는 `docs/reports/`에 등록합니다.
재귀 `**/run.json`은 workspace 복사본까지 중복 집계하므로 사용하지 않습니다.
채점은 실험별로 수행합니다. 서로 다른 실험을 한 번에 합산하는 입력은 거부합니다.
과거 checkpoint 경로는 도구가 이동 대응표로 찾아 비용·짝지은 비교에 사용합니다.

## 실행 예와 다음 비교

```bash
python scripts/run_task.py fresh --task-id <id> --pool multi --condition direct_execution
python scripts/run_task.py fresh --task-id <id> --pool multi --condition adaptive_probe
python scripts/run_task.py restore --checkpoint <v18-run>/checkpoints/a0 --condition adaptive_probe
python scripts/run_batch.py --tasks <exploratory-tasks.csv> --pool multi --condition direct_execution \
  --reps <fixed-reps> --purpose "Shared state fresh comparison" \
  --experiment outputs/experiments/<date>_shared-state-comparison
```

위 예는 사용법이며 이번 구현에서 유료 실행하지 않았습니다. 오프라인 scripted model·fake web/HTTP 검사를
먼저 완료합니다. 기존 탐색 task의 두 조건 **fresh** 비교는 반복 수·총 지출·실행 순서를 별도로 확정한 뒤
수행합니다. 최초 비교는 전체 구성의 효과이며 기능별 기여는 후속 ablation으로 확인합니다. 누락/실패도 각
조건 분모에 포함하고 반복은 task 안에서 평균한 뒤 task를 동일 가중합니다.

`score_runs.py --compare`는 기존 restore pairing 전용입니다. 전체 구성 fresh 비교의 조건 순서/집계 계획은
실험 전에 별도로 확정하며 restore 비교를 fresh 비교처럼 해석하지 않습니다.

문제 split은 고정입니다. `baseline_v1`은 탐색용 50문제이며 평가 집합이 아닙니다.
`eval_v1`은 본 평가까지 실행·열람·튜닝에 사용하지 않습니다.
실행 라벨링은 [failure codebook](evaluation/failure-codebook.md)와
[labelling protocol](evaluation/labelling-protocol.md)을 봅니다.
