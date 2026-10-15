# GAIA instruction 비교: 사후 최고 instruction oracle

기존 408경로의 점수만 사용한 사후 분석이다. 추가 모델 호출은 없다. 원본 점수와 실행은 변경하지 않았다.

문제마다 네 instruction의 **3회 평균 정답률** 중 최고를 고르고, 34문제를 동일 가중으로 평균하면
oracle 정답률은 **86.3%(88/102)**다. Naive 76.5%보다 +9.8%p, 고정 verify 81.4%보다 +4.9%p다.
같은 실행으로 선택과 평가를 모두 하므로, 독립적인 새 실행에서 얻은 성능 상한으로 해석하지 않는다.
각 반복마다 다른 instruction의 정답을 고르는 pass@4나 12회 중 한 번이라도 맞힌 문제 비율과는 다르다.

| 정책 | 정답률 | naive 대비 |
|---|---:|---:|
| naive 고정 | 76.5% | — |
| verify 고정 | 81.4% | +4.9%p |
| 문제별 사후 최고 instruction | 86.3% | +9.8%p |

Oracle − naive의 paired task bootstrap 95% CI는 +2.9~+17.6%p다. 최고값 선택으로 생기는 편향을
제거하는 CI는 아니다. 34문제 중 7문제에서 naive보다 높고, 23문제는 네 후보 점수가 모두 같다.
세 문제(cca530fc, cf106601, e142056d)는 12개 실행이 모두 오답이었다.

## 실행 잡음 기준선

MoNaCo와 같은 취지로 문제별 실행 점수 12개를 섞어 네 후보에 3개씩 재배정한다. 후보 효과가 없다는
교환 가능성 가정 아래, 섞은 사후 최고와 섞은 naive의 차이를 계산한다(20,000회, seed 0).

- 잡음만 있는 기준선의 oracle 정답률 평균: 85.3%.
- 잡음 기준선의 oracle − naive 평균: +6.65%p, 95% 무작위화 범위 +1.96~+11.76%p.
- 관측 oracle − naive +9.80%p는 이 범위 안이다. 단측 permutation p = 0.136.

잡음 기준선의 naive는 각 섞기에서 다시 계산하며 평균은 네 고정 후보의 전체 평균인 약 78.7%다.
따라서 기준선 oracle 정답률에서 실제 naive 76.5%를 빼면 위의 null 차이와 일치하지 않는다.
이 기준선에서도 최대값 선택만으로 상당한 이득이 생긴다. 관측 headroom이 실행 잡음보다 크다고
확인되지는 않았으며, 실제 instruction 선택 성능을 주장하려면 선택과 평가를 분리한 새 실행이 필요하다.

## 원본

- [본 실행 보고서](2026-10-15-gaia-instruction-execution.ko.md)
- [Oracle 계산 결과와 문제별 최고 후보](../../outputs/experiments/2026-10-15_gaia-instruction-execution-34tasks-3reps/analysis/oracle_summary.json)
- [재현 스크립트](../../outputs/experiments/2026-10-15_gaia-instruction-execution-34tasks-3reps/analyze_oracle.py)
