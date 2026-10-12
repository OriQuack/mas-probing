# GAIA 주요 trace live 재실행 — 2026-10-12 KST

현재 `v13/r15/e3`, tools `v6`를 실제 모델·웹 도구로 실행했다. 같은 5개 탐색 과제를 두 조건에서 각 1회 fresh로 실행했다. 실행 중 prompt와 package 코드는 수정하지 않았다.

이 표본은 이미 분석한 사례이며 반복은 1회다. 전체 구성과 실행 한도가 과거와 다르므로 prompt 변경의 효과나 일반화 성능을 입증하는 비교가 아니다.

## 사전에 정한 실행 범위

- 대상: Secret Santa, USDA, Freud, arXiv, OpenCV. 모두 고정 `baseline_v1`에 속하는지 확인했다. `eval_v1`은 열람·실행하지 않았다.
- 제외: PubChem(기존 평균 $0.388/최대 $0.914), spin glass(최근 평균 $0.240/최대 $0.249). 주요 사례 중 비용이 낮은 5개를 선택했다.
- 두 조건 각 1회, 총 10회. 각 run $1·15분, 전체 $10 상한. 위임 12회, 실행 도구 20회, run LLM/도구 각각 400회와 기존 위임 전 상한을 유지했다.
- Pool은 `multi`; Luna와 Haiku 모두 executor 후보. 과제 두 개를 병렬 실행하고 같은 과제의 조건은 순차 실행했다. 과제 순서는 Secret Santa, USDA, Freud, arXiv, OpenCV; 첫 조건은 과제마다 direct/probe를 교차했다.
- 동일한 v6 cache를 공유했다. 조건 순서를 교차했지만 개별 과제의 cache·검색 시점 차이를 제거하지 못했다. 비용은 실패·수정 요청·조회·reader·검색을 포함한다.
- 초기 실행 스크립트의 import 경로 오류로 모델 호출 전 10개 시작 시도가 실패했다. 유료 호출은 없었으며 원본 로그와 계획은 별도 보존했다. 경로를 수정한 live batch의 10개 결과와 구분한다. 초기 계획 10개도 별도 scorer에서 모두 missing/실패로 집계했다.

[실행 계획과 snapshot](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/manifest.json) · [원본 결과](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/batch.jsonl) · [초기 시작 실패](../../outputs/experiments/2026-10-12_gaia-key-traces-live/manifest.json)

## 결과

✓/✗는 기존 GAIA scorer 판정이다. 시간 한도 종료도 실패로 포함했다. `ok`는 실행이 끝났다는 뜻이며 정답을 뜻하지 않는다.

| 과제 | 이전 v10/r12 baseline | 이전 v10/r12 multi probe | 현재 direct | 현재 multi probe |
|---|---|---|---|---|
| Secret Santa | Fred ✓ | Cannot be determined ✗ | Cannot be determined: Fred or Micah ✗ | Cannot be determined uniquely: Fred or Micah ✗ |
| USDA | 86% ✓ | 67% ✗ | 시간 한도 | 시간 한도 |
| Freud | Feuerbach ✗ | Kleinpaul ✓ | Kleinpaul ✓ | Kleinpaul ✓ |
| arXiv | 31 ✓ | Unresolved (0–97) ✗ | 시간 한도 | 시간 한도 |
| OpenCV | Li Peng ✓ | Li Peng ✓ | Li Peng ✓ | Li Peng ✓ |

현재 조건별 비용과 성공 수:

| 조건 | 정답/계획 | 전체 비용 | 유료 검색 credits | 시간 한도 종료 |
|---|---:|---:|---:|---:|
| direct_execution | 2/5 | $0.5081 | 130 | 2 |
| multi_worker_probe | 2/5 | $0.3819 | 72 | 2 |

알려진 총비용은 **$0.8900**다. 유료 검색 202 credits, 과금 불명 검색 0건, 비용 불명 LLM 호출 1건이다.

과거 arXiv baseline은 약 26분에 정답 31을 제출했다. 이번 15분 한도는 그 실제 실행 시간보다 짧다. 비용만 확인하고 시간 상한을 정했으므로 arXiv의 미완료율 자체를 prompt 성능 악화로 해석할 수 없다. 다만 아래의 기준 강화는 시간 한도와 별개의 trace 관측이다. USDA도 이번 시간 한도에 걸렸으며, 접근·재확인·평가 overhead의 기여를 분리하지 않았다.

## Trace에서 확인한 동작과 남은 문제

**Secret Santa:** direct의 첫 worker는 Fred를 보고했다. Evaluator가 표 방향을 미확인으로 다룬 뒤 orchestrator가 Haiku에 재확인을 맡겼고 최종 답은 Fred/Micah 복수 후보가 됐다. Probe 조건도 복수 후보로 끝났다. 문서에 실제 모호한 표제가 있으므로 모든 확인을 불필요하다고 단정할 수는 없지만, 지원되는 추론을 보존하고 추가 확인을 자동 보류 조건으로 만들지 말라는 문구만으로 이 경로를 막지 못했다.

**Freud:** direct는 위임 6회 끝에 Internet Archive OCR에서 해당 문장을 읽고 Kleinpaul을 제출했다. Probe 조건도 같은 이름을 제출했다. 탐색을 계속한 결과 새 근거를 얻은 사례다. Probe가 짧고 저렴했던 관측은 있지만, direct-first cache와 검색 시점 차이·단일 반복 때문에 그 차이를 probe 효과로 해석하지 않는다.

**USDA:** 두 조건 모두 7개 대상과 여러 버전 근거를 수집했고 6/7=86% 후보를 다뤘지만 최종 답 없이 시간 한도로 종료했다. 조건부 집계와 최종 답은 구분했다. 반면 남은 표준의 적용 범위·전후 버전 연결을 반복 확인하면서 시간 내 종료하지 못했다. 원본 partial 보고와 실패한 시도도 보존했다.

**arXiv:** probe 경로에서 refiner를 호출한 수정과 수정 생략 경로가 모두 나타났다. 승인 변경에는 당시 보관본 증명을 필수로 요구하지 말라는 범위 교정이 포함됐다. 완료한 세 실행 보고의 확인 범위는 11개→14개→33개였고, 마지막 보고는 64개를 미확인으로 남겼다. 일부 재확인으로 진척이 느렸으며, 부분 집계를 97개 전체의 답으로 제출하지 않았다. Direct는 58/97개를 확인한 뒤 역사적 보관본 탐색으로 전환했다. 초기 지시는 January 2020을 listing month로 취급하라고 명시했지만, a00003 평가가 시간 범위 결정을 요청했고 이후 a00007 평가와 다섯 번째 지시는 개별 항목의 당시 format 증거를 요구했다. 마지막 보고는 해당 시점 capture를 찾지 못해 0–97 범위를 제시했다. 원 질문의 날짜를 format의 당시 가용성까지 증명하는 조건으로 강화한 경로다. 날짜 검토가 필요한지와 모든 항목에 당시 증거를 필수로 요구하는지는 구분해야 하며, 후자의 정당화는 별도로 검토할 문제다. 따라서 직접 조건의 실패를 시간 부족만으로 설명하지 않는다.

**OpenCV:** 두 조건 모두 Li Peng을 제출했다. Probe 실행 평가에서는 release contributor와 feature author를 구분하고, 기능을 직접 구현한 사람을 증명하도록 범위를 좁히지 말라고 명시했다. 이어서 이름과 전 총리 직책에 대한 출처 확인을 별도 위임했다.

원본 조회 58라운드, state 교체 37회, 위임 시작 30회가 trace에 기록됐다. 시작된 위임과 평가까지 끝난 위임 수는 시간 한도 run에서 다를 수 있다. Title 누락은 1건이었다. 이 1건은 USDA probe 조건에서 시간 한도로 중단된 실행의 실패 기록이며, harness가 기본 제목을 붙이고 오류 본문을 보존했다.

JSON 문법 이외의 참조·행 선택·행동 선택 계약 오류도 실제 호출에서 발생했다. 오류를 지우지 않고 수정 요청과 비용을 포함했다:

| 오류 | 횟수 |
|---|---:|
| ValueError('state refs must be artifact IDs') | 20 |
| ValueError('invalid state row 0') | 2 |
| ValueError('invalid decision action') | 1 |
| ValueError('invalid state row 5') | 1 |

도구 원문 조회용 `artifact/tool/N`과 state 근거용 artifact ID를 혼동한 경우가 대부분이었다. 채택 전 state snapshot과 평가 제안의 행 번호를 혼동한 경우도 있었다. 문구로 명시했더라도 실제 모델 준수는 별도 확인이 필요하다. 이번 결과를 보고 prompt를 즉시 수정하거나 같은 결과를 개선된 버전의 결과로 다시 집계하지 않았다.

## 다시 읽을 자료

- [전체 점수 CSV](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/scores.csv)
- [현재 run별 진단·지시·선택 이유](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/diagnostics.json)
- [과거 v10/r12 대응 실행](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/historical_comparison.json)
- [단계별 비용·오류 집계](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/summary.json)

- [Secret Santa / direct_execution trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/cffe0e32_direct_execution_trace.md)
- [Secret Santa / multi_worker_probe trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/cffe0e32_multi_worker_probe_trace.md)
- [USDA / direct_execution trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/676e5e31_direct_execution_trace.md)
- [USDA / multi_worker_probe trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/676e5e31_multi_worker_probe_trace.md)
- [Freud / direct_execution trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/65638e28_direct_execution_trace.md)
- [Freud / multi_worker_probe trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/65638e28_multi_worker_probe_trace.md)
- [arXiv / direct_execution trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/a7feb290_direct_execution_trace.md)
- [arXiv / multi_worker_probe trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/a7feb290_multi_worker_probe_trace.md)
- [OpenCV / direct_execution trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/56137764_direct_execution_trace.md)
- [OpenCV / multi_worker_probe trace](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/56137764_multi_worker_probe_trace.md)
