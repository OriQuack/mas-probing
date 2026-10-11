# 실험·용어·산출물 안내

## 서로 다른 축

| 용어 | 정확한 의미 |
|---|---|
| experiment | 하나의 목적과 비교 설계를 가진 실행 묶음. 폴더와 manifest로 식별 |
| batch | `run_batch.py` 한 번의 실행. 하나의 experiment에 여러 batch가 있을 수 있음 |
| run | 한 문제를 한 조건으로 한 번 실행한 기록 |
| condition / arm | 비교 조건. 조건과 fresh/restore, pool, override 여부를 함께 구분 |
| replicate | 같은 조건의 반복. 기존 label의 `_r0`, `_r1`은 반복 번호 |
| fresh / restore | 처음부터 실행 / 위임 직전 checkpoint에서 재개 |
| delegation / d0 | worker 위임 한 번 / 0부터 센 첫 위임. 독립 subtask 개수와 같지 않음 |
| role / executor / probe worker | 위임 역할 / 고정 실행 worker / 실행 전 질문에 답하는 worker |
| context / instruction | 이전 보고 정보 / 현재 작업 지시 |
| trace stage | `orchestrator`, `execution`, `refine.review/probe/followup/analyze/verify/rewrite` 등 실행 내부 태그 |

과거 실험의 stage 1~4, Phase A/B는 실험 진행 순서였으며 trace의 `stage`와 무관합니다.
새 실험은 순서 대신 **목적을 이름에 씁니다**. 이름만으로 모델·프롬프트·도구 조건을 추측하지 않습니다.

## 현재 조건

모든 현재 preset은 refiner `r9`를 사용합니다. `configs/refiners/`에 있습니다.

| 설정 이름 | 수집 방법 | Probe 도구 |
|---|---|---|
| baseline | 검토 없이 초안 실행 | 해당 없음 |
| self_review | orchestrator가 executor 응답 예측 | 없음 |
| executor_probe | executor 실제 응답 1회 | 없음 |
| executor_probe_tools | executor 실제 응답 1회 | 최대 3회 |
| multi_worker_probe | executor와 Haiku 독립 응답 | 각 최대 3회 |
| direct_check | 응답 수집 없이 검토·필요한 확인 | probe 없음 |

수집 뒤 analysis → 필요한 verification → rewrite는 공유합니다. 기본 설정의 검토 예산과 사전 확인 한도는
동일하지만 실제 사용량, 모델, 응답 수·도구 기회는 다를 수 있습니다. 함께 기록하고 비교합니다.
`direct_check`는 비교를 위한 기능이며 현재 전체 성능 결과가 없습니다.

`variants/`에는 pool 전체 probe/예측, executor 2회 probe, 후속 질문, 대화 연결, 연결 후 재작성 생략
기능 preset이 있습니다. 현재 프롬프트로 동작하며 과거 r5 조건의 재현이라고 부르면 안 됩니다.

Pool 이름은 `multi`(일반 역할 하나 + executor/probe-only worker), `single`(동일 역할·worker 하나),
`role_routing`(web/file 역할), `redundant`(동일 작업의 복수 후보)입니다. 모델 선택은 각 YAML에 명시합니다.

## 버전

| 식별자 | 축 | 현재 값 / 규칙 |
|---|---|---|
| `PROMPTS_VERSION` | orchestrator·worker 및 원 문제 포장 | `v7`; restore 시 동일해야 함 |
| `REFINER_PROMPTS_VERSION` | probe·예측·분석·확인·재작성 | `r9`; 위임 후 개입이므로 더 최신 버전 사용 가능 |
| `tools_version` | 도구 동작 | ToolConfig에 기록; restore 동일성 검사 |
| `blocklist_version` | 오염 필터 | 별도 축; 더 최신 필터는 허용 |

`v`, `r`은 모델 버전·실험 단계·반복 수를 뜻하지 않습니다. 프롬프트 식별자는 출처 확인을 위해 유지했습니다.
과거 코드별 세부 변경은 [역사적 결정 기록](history/decisions-before-cleanup.md), 결과 해석은
[최신 종합 보고서](reports/2026-10-10-synthesis.ko.md)를 봅니다.
현재 runtime에는 이전 prompt 구현이 없습니다. 과거 실행의 당시 코드 snapshot은 해당 실험에 보존합니다.
v5/v6 checkpoint를 현재 v7 코드로 복원하는 것은 지원하지 않습니다.

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
| c3_probe_multi | multi_worker_probe |
| 역사적 B / C | 예측 응답 / 실제 응답. 당시 버전은 기록을 확인; 현재 preset과 동일하다고 가정하지 않음 |
| r5 | 삭제한 과거 refiner 구현. 현재 코드에서 선택 불가 |

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

## 실행 예

```bash
python scripts/run_batch.py --tasks data/splits/baseline_v1.csv --pool multi \
  --refiner baseline --reps 1 --purpose "Baseline recording" \
  --experiment outputs/experiments/<date>_baseline-recording
python scripts/run_batch.py --checkpoints checkpoints.txt \
  --refiners baseline self_review executor_probe multi_worker_probe --reps 3 \
  --purpose "Real versus predicted probe answers" \
  --experiment outputs/experiments/<date>_probe-answer-comparison
python scripts/score_runs.py outputs/experiments/<experiment> \
  --expected outputs/experiments/<experiment>/planned.csv \
  --compare self_review multi_worker_probe
```

문제 split은 고정입니다. `baseline_v1`은 탐색용 50문제이며 평가 집합이 아닙니다.
`eval_v1`은 본 평가까지 실행·열람·튜닝에 사용하지 않습니다.
실행 라벨링은 [failure codebook](evaluation/failure-codebook.md)와
[labelling protocol](evaluation/labelling-protocol.md)을 봅니다.
