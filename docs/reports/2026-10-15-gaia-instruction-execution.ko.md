# GAIA non-web: 첫 subtask instruction 3반복, probe 없음

채점 완료: 2026-10-15 22:12 KST.

Verify의 관측 정답률이 81.4%로 가장 높았다(naive 76.5%, +4.9%p). Naive 대비 95% CI는
−3.9~+13.7%p다. Clarify·structured도 각각 +2.0%p이며, 세 후보 모두 CI가 0을 포함해 이득은 확인되지 않았다.
408경로 모두 정상 종료했고 비용은 $1.8075였다. 429·과금 불명 호출은 0건이었다.

기존 non-web 34문제에서 공통 첫 subtask를 고정하고 naive·clarify·structured·verify를 각각 3회 실행했다.
모든 경로는 `haiku-medium`의 새 대화·workspace에서 시작한다. 첫 요청에서 해당 subtask와 add-on을 수행하고,
같은 worker가 동일한 두 번째 완료 지시로 원 GAIA task를 끝까지 푼다. Probe·instruction 선택·후속 orchestrator는 없다.

## 설정과 해석 범위

- `gaia-instruction-execution-v1`, 34문제 × 4조건 × 3반복 = 408경로.
- Category 지시는 subtask만 보고 작성·독립 검토했다. 첫 subtask는 질문과 도구 명세로 작성했다.
- 22문제는 중간 결과를, 12문제는 첫 요청에서 최종 답도 나올 수 있는 작업을 배정했다. 모든 경로는 두 번째 요청까지 수행했다.
- 도구는 로컬 read_file·view_image·run_python. 요청당 도구 20회, 경로당 도구 40회·LLM 100회·3시간·$0.20 상한.
- 반복은 새 대화·workspace에서 수행하며 반복 내 조건 순서를 seed로 섞었다. 실행은 고정한 source snapshot을 사용했다.
- 공식 GAIA scorer와 answer extraction v1. Non-ok/missing은 실패. 반복을 문제 내 평균한 후 문제 동일 가중, paired task bootstrap 95% CI.
- 기존 탐색 집합이므로 독립 평가 집합 성능 추정이 아니다. 전체 orchestrator 방식과의 직접 비교도 아니다.
- Verify의 추가 확인은 실제 도구·토큰 사용을 늘릴 수 있다. 결과는 동일한 사용량이 아니라 동일한 상한 아래의 전략 비교다.

## 결과

| 조건 | 정답/102경로 | 정답률 | naive 대비 (%p) | 95% CI (%p) | 비용 |
|---|---:|---:|---:|---:|---:|
| naive | 78/102 | 76.5% | +0.0 | [+0.0, +0.0] | $0.3828 |
| clarify | 80/102 | 78.4% | +2.0 | [-6.9, +9.8] | $0.4515 |
| structured | 80/102 | 78.4% | +2.0 | [-2.9, +6.9] | $0.5134 |
| verify | 83/102 | 81.4% | +4.9 | [-3.9, +13.7] | $0.4598 |

조건별 3반복 정답 수:

| 조건 | 반복 1 | 반복 2 | 반복 3 |
|---|---:|---:|---:|
| naive | 26 | 26 | 26 |
| clarify | 24 | 30 | 26 |
| structured | 26 | 27 | 27 |
| verify | 28 | 29 | 26 |

## 실행 상태와 비용

총 기록 비용 $1.8075. 과금 불명 호출 0건.
첫 429 이후 직렬 전환 여부: False.

| 조건 | 실행 상태 |
|---|---|
| naive | {"ok": 102} |
| clarify | {"ok": 102} |
| structured | {"ok": 102} |
| verify | {"ok": 102} |

경로당 평균 사용량(두 요청 합계):

| 조건 | LLM 호출 | 도구 호출 | 경로 시간(초) |
|---|---:|---:|---:|
| naive | 3.79 | 1.87 | 27.07 |
| clarify | 3.88 | 1.94 | 33.16 |
| structured | 3.87 | 1.93 | 31.79 |
| verify | 4.01 | 2.10 | 32.12 |

## 읽는 방법

Naive 대비 CI가 0을 포함하면 이 표본에서 방향이 확정됐다고 해석하지 않는다. 정답 수 차이만으로
개선이 입증됐다고 하지 않는다. 세 후보의 동시 탐색이며 CI는 다중 비교 보정을 하지 않은 값이다.
첫 subtask의 결과·대화·도구 산출물이 후속 해결에 미치는 효과를 포함한다. Category의 후속 요청 재주입은 없다.

## 원본

- [실험 manifest](../../outputs/experiments/2026-10-15_gaia-instruction-execution-34tasks-3reps/manifest.json)
- [문제별·경로별 점수](../../outputs/experiments/2026-10-15_gaia-instruction-execution-34tasks-3reps/analysis/scores.csv)
- [집계와 문제별 평균](../../outputs/experiments/2026-10-15_gaia-instruction-execution-34tasks-3reps/analysis/summary.json)
- [408경로 대화·병렬 실행 검증](../../outputs/experiments/2026-10-15_gaia-instruction-execution-34tasks-3reps/analysis/audit.json)
- [설계와 운영](../operations/gaia-instruction-execution.ko.md)
