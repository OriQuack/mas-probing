# GAIA 주요 trace live 재실행 — 2026-10-12 KST

현재 `v13/r15/e3`, tools `v6`를 실제 모델·웹 도구로 실행했다. 같은 5개 탐색 과제를 두 조건에서 각 1회 fresh로 실행했다. 실행 중 prompt와 package 코드는 수정하지 않았다.

두 조건 모두 2/5 정답이었다. 기록·평가·executor 선택은 실제 실행됐지만, 답 보류와 평가 중 기준 강화가 다시 나타났다. 아래의 수정 방향은 trace에서 도출한 제안이다. 이후 4번의 참조 계약을 `v14/r16/e4`에서 수정했으며, 나머지 제안은 미구현이다. 참조 계약 수정의 실제 모델 효과도 아직 검증하지 않았다.

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

## 수정 후보 메모

여기서 담당은 해당 동작을 결정하거나 구현하는 역할을 뜻한다. 실패의 모든 원인이 그 역할 하나에 있다는 뜻은 아니다. 실행 결과, trace에서 확인한 판단, 그 판단에 대한 해석을 구분한다. `direct`는 `direct_execution`, `probe`는 `multi_worker_probe`를 줄여 쓴다.

| 수정 후보 | 주로 담당하는 역할 | 대표 trace | 확인된 결과 |
|---|---|---|---|
| 평가 중 요구 조건 강화 | evaluator 제안 → orchestrator 채택 | arXiv / direct | 58/97개 확인 후 역사적 증거 탐색으로 전환 |
| 미해결 확인을 답 보류 조건으로 사용 | evaluator 평가 → orchestrator 재위임·최종 판단 | Secret Santa / direct | 첫 보고 Fred → 최종 Fred/Micah 결정 불가 |
| 재확인 범위와 종료 판단 | orchestrator 작업 선택, evaluator 확인 요구 | USDA / direct·probe | 86% 후보를 다뤘지만 최종 답 없이 시간 초과 |
| 참조·행 선택 계약 혼동 | harness 인터페이스·prompt 출력 계약, controller 응답 | OpenCV·Secret Santa·arXiv 등 | 참조 오류 20회, 행 선택 오류 3회 |
| 기존 소요 시간보다 짧은 실행 상한 | 실험 설계·실행 설정 | arXiv 두 조건 등 | 시간 부족과 성능 차이를 분리하기 어려움 |

### 1. 평가 중 원 질문의 요구 조건이 강화됨

- **담당:** evaluator가 시간 범위 변경을 제안하고 orchestrator가 실행 지시로 채택했다. Refiner만의 문제로 볼 수 없다.
- **Trace:** [arXiv / direct](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/a7feb290_direct_execution_trace.md).
- **관측·예시:** 최초 지시는 January 2020을 논문 목록의 월로 취급하고 각 논문의 PS 제공 여부를 확인하라고 했다. `a00003` 평가는 시간 범위 결정을 요청했다. 이후 `a00007` 평가와 다섯 번째 지시는 개별 논문의 2020년 1월 capture 또는 당시 PS 가용성을 입증하는 자료를 요구했다. 현재 format 페이지나 나중의 capture는 당시 가용성의 증거로 인정하지 않았다.
- **결과:** 58/97개를 확인하던 작업이 역사적 보관본 탐색으로 전환됐다. 마지막 보고는 당시 증거를 찾지 못해 0–97 범위를 제시했고, run은 최종 답 없이 시간 초과했다. 작업 전환과 시간 초과의 인과적 기여는 분리하지 않았다.
- **진단:** 날짜의 의미를 검토하는 것과 모든 논문에 당시 format 증거를 필수로 요구하는 것은 다른 판단이다. 추가 증명 조건이 원 질문에 필요한지 충분히 정당화하지 않은 채 작업 기준이 강화됐다.
- **수정 방향:** evaluator는 원 질문의 요구 조건과 자신이 제안하는 추가 증명 조건을 구분하고, 후자가 답 범위를 어떻게 바꾸는지 설명한다. Orchestrator는 필요성을 판단한 뒤 채택 여부와 이유를 기록한다. 더 엄격하다는 이유만으로 기준을 변경하지 않는다.

### 2. 미해결 확인 사항이 답 보류 조건이 됨

- **담당:** evaluator의 불확실성 평가와 orchestrator의 재위임·최종 답 판단.
- **Trace:** [Secret Santa / direct](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/cffe0e32_direct_execution_trace.md). Probe도 최종적으로 복수 후보를 제출했다.
- **관측·예시:** 첫 worker는 선물·취향·배정 관계를 연결해 Fred를 보고했다. 보고에는 첫 열을 giver, 둘째 열을 recipient로 읽었다는 해석과 `Giftee` 표제의 모호함도 적었다. Evaluator가 표 방향을 미확인으로 다룬 뒤 orchestrator는 Haiku에 재확인을 맡겼다. 다음 지시는 통상적인 형식으로 방향을 추론하지 말고, 방향이 미해결이면 결론을 조건부로만 취급하라고 요구했다.
- **결과:** 최종 답은 `Cannot be determined: Fred or Micah`였고 scorer에서 오답이었다.
- **진단:** 실제로 모호한 표제가 있어 재확인 자체를 불필요하다고 단정할 수 없다. 다만 미해결 모호함의 존재가 답 보류로 이어졌다. 원 질문 설명과 문서 전체 관계에 비춰 대안 해석이 얼마나 지지되는지 비교할 필요가 있다.
- **수정 방향:** evaluator는 불확실성이 결론을 뒤집는 구체적인 대안 해석과 그 근거를 제시한다. Orchestrator는 기존 해석과 대안의 일관성을 비교해 최종 답을 정한다. 추가 확인이 끝나지 않았다는 사실만으로 답을 보류하지 않는다.

### 3. 재확인의 범위와 종료 판단이 불명확함

- **담당:** orchestrator의 다음 작업 선택이 중심이다. Evaluator의 확인 요구와 worker의 미완료 보고도 다음 지시에 영향을 준다.
- **Trace:** [USDA / direct](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/676e5e31_direct_execution_trace.md), [USDA / probe](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/676e5e31_multi_worker_probe_trace.md).
- **관측·예시:** 두 조건 모두 7개 대상과 `6/7=86%` 후보를 다뤘다. Direct에서는 첫 보고 이후 successor 관계, 1983년 통합 표준의 적용 범위, frozen apples의 후속 버전을 확인하는 위임이 이어졌다. 일부 지시는 전체 항목의 표와 근거를 다시 요구했고, 후속 지시는 미해결 orange-juice 항목과 frozen apples에 집중했다.
- **결과:** 조건부 집계와 미완료 항목은 보존됐지만 두 run 모두 최종 답 없이 15분 한도로 종료됐다. 86%는 검증 완료된 최종 답으로 제출되지 않았다.
- **진단:** 실제로 필요한 적용 범위 확인이 남아 있었다. 따라서 모든 재확인을 낭비라고 단정할 수 없다. 다만 이미 확보한 근거의 재수집, 접근 지연, 평가 overhead가 종료 지연에 각각 얼마나 기여했는지는 아직 분리하지 못했다.
- **수정 방향:** 다음 위임은 답을 바꿀 수 있는 미해결 항목과 기존 시도에서 달라진 자료·방법을 명시한다. 이미 확인한 내용은 context로 전달한다. 같은 접근이 막혔을 때 새 경로를 시도할지, 조건부 결과를 정리하고 종료할지 orchestrator가 판단한다. 재시도 횟수만으로 일괄 차단하지 않는다.
- **반례:** Freud / direct는 위임 6회 끝에 Internet Archive OCR에서 해당 문장을 읽고 Kleinpaul 정답을 냈다. 탐색을 계속해 새 근거를 얻은 경우이므로 반복 탐색 자체를 금지하는 수정은 부적절하다.

### 4. 참조·행 선택 계약이 혼동을 줌

- **담당:** harness의 인터페이스와 역할별 출력 계약을 함께 검토해야 한다. 잘못된 값은 evaluator 등 controller 응답에서 발생했다. Harness는 해당 응답을 거부하고 수정 요청을 보냈다.
- **Trace:** [OpenCV / direct](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/56137764_direct_execution_trace.md), [Secret Santa / direct](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/cffe0e32_direct_execution_trace.md), [arXiv / direct](../../outputs/experiments/2026-10-12_gaia-key-traces-live-retry/analysis/a7feb290_direct_execution_trace.md) 등.
- **관측·예시:** state의 `refs`에 artifact ID 대신 도구 원문 조회 주소인 `artifact/tool/N`을 입력했다. State 선택에서도 해당 snapshot에 유효하지 않은 행 번호를 입력했다. 채택 전 state snapshot과 평가 제안의 행 번호를 혼동한 경우가 있었다.
- **결과:** 아래 오류와 수정 요청을 모두 원본 trace와 비용에 포함했다. 참조 오류 20회는 잘못된 필드 값의 총수가 아니라 오류 응답 횟수다.

| 오류 | 횟수 |
|---|---:|
| `ValueError('state refs must be artifact IDs')` | 20 |
| `ValueError('invalid state row 0')` | 2 |
| `ValueError('invalid state row 5')` | 1 |
| `ValueError('invalid decision action')` | 1 |

- **수정 방향:** 조회 주소와 state 근거 ID를 별도 필드·명칭으로 구분한다. State 행 선택에는 어느 입력 snapshot인지와 선택 가능한 행 번호를 명시한다. 수정 요청은 잘못된 값과 허용되는 값의 예시를 함께 반환한다. 행동 선택 오류 1건은 별도로 기록하며, 참조 혼동과 같은 원인이라고 단정하지 않는다.

**후속 구현:** `v14/r16/e4`에서 보고와 도구 결과 모두 저장된 ID를 `read_memory.refs`, state `refs`, context `artifact_ids`에 사용하도록 통일했다. 보고의 `tool_ids`로 도구 결과를 찾고, 도구 결과의 `parent_id`로 원 보고를 확인한다. State의 네 필드와 행 선택 방식은 유지했다. 행 선택·행동 선택 오류는 이번 수정의 해결 범위에 포함하지 않는다. 이 보고서의 점수와 trace는 수정 전 `v13/r15/e3` 기록 그대로다.

### 5. 비교 실험의 시간 상한이 기존 실행 특성을 반영하지 못함

- **담당:** 실험 설계·실행 설정을 정한 구현 agent의 문제다. 모델 역할에 책임을 돌릴 수 없다.
- **Trace:** arXiv 두 조건과 USDA 두 조건이 시간 한도로 종료됐다.
- **관측·예시:** 과거 arXiv baseline은 정답 31을 제출하는 데 약 26분 걸렸다. 이번에는 기존 소요 시간을 확인하지 않고 비용을 기준으로 run당 15분 상한을 정했다.
- **결과:** 현재 2/5 정답이라는 수치만으로 이전보다 prompt·runtime 성능이 나빠졌다고 판단할 수 없다. USDA의 시간 부족도 접근 지연·재확인·평가 비용과 분리하지 못했다.
- **수정 방향:** 다음 비교 전에 기존 정상 완료 시간과 새 평가·조회 overhead를 검토해 실행 상한을 정한다. 반복 수·총 지출·조건 순서·cache 사용 정책을 실행 전에 고정한다. 시간 초과와 기준 강화 같은 판단 오류를 별도로 보고한다.

## 유지할 동작과 검증 범위

수정은 위 실패 경로에 한정해야 한다. 다음 관측은 재시도·평가·수정 단계를 일괄 제거할 근거가 없음을 보여준다.

- **Freud:** 두 조건 모두 Kleinpaul 정답. Direct는 새 OCR 근거를 얻어 해결했다. Probe가 더 짧고 저렴했지만 direct-first cache, 검색 시점 차이, 단일 반복 때문에 probe 효과라고 해석하지 않는다.
- **OpenCV:** 두 조건 모두 Li Peng 정답. Probe 실행 평가에서는 release contributor와 feature author를 구분하고, 기능을 직접 구현한 사람의 증명으로 범위를 좁히지 말라고 명시했다. 이후 이름과 전 총리 직책의 출처를 확인했다.
- **arXiv / probe:** 당시 보관본 증명을 필수로 요구하지 말라는 교정이 채택됐다. Refiner를 호출한 수정과 수정 생략이 모두 나타났다. 완료한 세 실행 보고의 확인 범위는 11개→14개→33개였고, 마지막 보고는 64개를 미확인으로 남겼다. 부분 집계를 97개 전체의 답으로 제출하지 않았다.

원본 조회 58라운드, state 교체 37회, 위임 시작 30회가 기록됐다. 시간 한도로 종료된 run에서는 시작된 위임과 평가까지 끝난 위임 수가 다를 수 있다. Title 누락 1건은 USDA probe 조건에서 중단된 실행의 실패 기록이며, harness가 기본 제목을 붙이고 오류 본문을 보존했다.

이 기록은 전체 실행 경로가 실제 호출에서 사용됐다는 근거다. State의 모든 판단이나 executor 선택의 적절성이 검증됐다는 뜻은 아니다. 진단 batch 실행 중 production prompt는 고정했다. 이후의 참조 계약 수정은 위 후속 구현에 별도로 기록했으며, 같은 실행 결과를 새 버전의 성적으로 다시 집계하지 않았다.

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
