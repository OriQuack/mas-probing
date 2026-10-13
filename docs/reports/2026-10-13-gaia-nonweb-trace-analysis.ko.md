# GAIA non-web 두 반복: 주요 trace와 takeaway

분석일: 2026-10-13 KST. 기존 실험만 분석했으며 추가 유료 호출이나 prompt 수정은 하지 않았다.

## 범위와 결과

36개 task × 2조건 × 2반복 = 144 runs. 공식 metadata에서 web 관련 도구가 표시된 문제 및 기존 audio/video 제외 문제를 뺀 집합이다. 전체 GAIA 대표 표본으로 일반화하면 안 된다. 모든 run을 집계하고, 조건 간 성적 차이가 있는 15개 task 및 고비용 실패 cf106601/cca530fc 중심으로 원문 trace를 대조했다. 상세 trace 발췌는 16개 task에 저장했다.

| 조건 | 공식 정답 | 비용 | 실행 횟수 | probe 라운드 |
|---|---:|---:|---:|---:|
| direct_execution | 46/72 (63.9%) | $0.5987 | 91 | 0 |
| adaptive_probe | 34/72 (47.2%) | $1.3482 | 67 | 84 |

Adaptive의 공식 정확도는 16.7%p 낮고 비용은 2.25배였다. 짝 비교에서는 direct만 정답 15건, adaptive만 정답 3건이다. Task별 두 반복 평균은 direct 우세 12개, adaptive 우세 3개, 동률 21개다. 독립적인 72문제 실험이 아니라 동일 36문제의 반복이다.

## 1. 가장 큰 손실은 최종 답 계약에서 발생한다

Direct만 맞은 15건을 원문으로 대조하면 13건은 adaptive 답에도 direct의 정답과 같은 핵심 답이 들어 있다. 설명·조건·추가 값이 붙어 공식 채점에서 탈락했다. 나머지 2건은 cffe0e32의 Fred/Micah 양자택일 거부, ec09fa32의 종료 규칙 조건부 처리로 따로 분류했다. 이 13건은 수동 진단이며 공식 점수를 재채점하거나 변경하지 않았다. 단서를 제거하면 논리적 문제가 모두 해소된다는 의미도 아니다.

대표 사례:

- **42576abe, 두 반복:** direct는 `Maktay Mato Apple`. Adaptive도 evaluator가 같은 답을 supported로 확정했지만 finish에 문법 설명을 추가했다. 첫 반복 refiner는 instruction을 그대로 반환했다. 실행 없이 finish했으므로 이 실패를 rewrite의 추론 오류로 설명할 수 없다.
- **50ad0280, 두 반복:** 정답 문장은 `The seagull glided peacefully to my chair.` 첫 반복은 띄어쓰기 추정 caveat, 두 번째는 원시 문자열과 문장을 함께 제출했다. 특히 두 번째에는 evaluator가 worker의 잘못된 분절을 올바른 문장으로 교정했는데도 최종 출력이 실패했다.
- **a3fbeb63:** 답 `4` 대신 해당 슬라이드 번호와 literal-word count `0`까지 추가했다.
- **67e8878b:** `Hotels` 대신 `Hotels (3.8/5)`.
- **7cc4acfa:** `Wharvton` 대신 두 지점의 합계를 덧붙였다.
- **076c8171:** adaptive가 이긴 첫 반복도 추론 차이보다 출력 범위 차이가 컸다. 두 조건 모두 Finance를 찾았지만 direct는 업체명까지 제출했고 adaptive는 `Finance`만 제출했다. 두 번째 adaptive도 업체명을 붙여 실패했다.

**Takeaway:** 현재 비교는 추론 품질과 answer serialization의 영향을 강하게 섞어 측정한다. 먼저 finish.answer에 요청된 최종 값만 넣고 설명과 caveat를 rationale/state로 보내는 계약을 안정화해야 한다. 이 결과만으로 probe가 핵심 추론을 16.7%p 악화시킨다고 결론 내릴 수 없다. Direct에도 같은 출력 문제가 있다.

## 2. 불확실성 검토가 문제의 주어진 전제를 다시 심판하는 방향으로 번진다

**7bd855d8, 두 번째 반복**이 가장 명확하다. 원 질문은 Excel의 food sales를 USD로 합산하라고 한다. 실제 실행은 정확한 합계 89,706을 계산했고, 포함된 45개 셀 모두 dollar accounting format인 것도 확인했다. 그러나 evaluator는 명시적 USD 코드와 revenue 표기가 없다는 이유로 문제의 sales/USD 프레이밍까지 unverified로 유지했다. Refiner는 그 판단을 instruction에 넣었고 마지막 실행 평가도 caveat를 요구했다. 결과는 `89706.00 (food-column aggregate; workbook does not establish USD sales revenue)`였다. Direct는 동일 합계를 `89706.00`으로 제출해 정답이었다.

**6359a0b1**에서는 그림의 직교 모양과 치수 해석을 조건부로 남겨 두 반복 모두 `39` 뒤에 단서를 붙였다. **cffe0e32**에서는 선물 배정표 방향을 결론 내리지 못하고 추가 probe 후에도 Fred/Micah 조건부 답을 유지했다. **ec09fa32**는 공이 끝나는 규칙을 문제 삼아 조건부 답을 제출했다.

이 사례의 모든 불확실성이 부당하다고 단정할 수는 없다. 다만 반복되는 경로는 관측된다: worker의 risk → evaluator의 unverified state → refiner의 추가 검증/단서 요구 → orchestrator의 조건부 finish.

**Takeaway:** 질문에서 주어진 전제, 도구에서 관측한 사실, 실제로 미해결인 가정을 구분해야 한다. 가정은 후보 답을 바꾸는지에 따라 다루는 것이 낫다. Evaluator의 과잉 요구를 refiner가 충실히 전파하는 사례라서 refiner만 수정하면 원인이 남는다.

## 3. 효과가 있었던 probe는 구체적인 검산이나 누락 확인이었다

- **6f37996b:** 연산표에서 모든 10개 unordered pair를 Python으로 비교해 유일한 비가환 쌍 `(b,e)`를 확인했다. Direct 첫 반복은 `b,d,e`로 잘못 답했고 adaptive는 두 반복 모두 `b,e`였다. 여기서는 명시적인 반례 검사와 도구 근거가 실제 오류를 줄였다. Refiner는 평가상 수정이 필요 없어 원문을 유지했다.
- **3cef3a44:** 채소 목록 첫 반복에서 probe의 항목별 분류가 `fresh basil` 포함을 드러냈고 adaptive는 정답이었다. Direct는 두 반복 모두 basil을 누락했다. 다만 adaptive 두 번째도 basil을 누락해 효과가 안정적이지 않았다.
- **50ad0280:** 평가자가 잘못된 문장 분절을 고친 것은 유용했다. 제출 형식 실패와 내부 교정 성공을 따로 봐야 한다.

**Takeaway:** 역할 수를 늘리는 것보다 후보를 구별하는 계산·누락 검사·반례 검사가 중요하다. “어떤 추가 관측이 답을 바꾸는가?”에 답할 수 있는 probe에 가치가 있었다. 이번 실험은 probe와 evaluator, refiner를 묶어서 비교했으므로 개선을 refiner 단독 효과로 귀속할 수 없다.

## 4. 비용은 refiner보다 probe와 반복 탐색에서 늘었다

Adaptive 비용을 LLM 로그 stage별로 다시 합산했다:

| 단계 | 비용 |
|---|---:|
| execution | $0.4790 |
| execution evaluator | $0.1950 |
| probe | $0.2843 |
| probe evaluator | $0.1646 |
| refiner | $0.0623 |
| orchestrator | $0.1629 |

Probe+probe 평가+refiner는 $0.5112로 adaptive 비용의 37.9%다. Refiner 자체는 4.6%다. Adaptive는 실행을 91회에서 67회로 줄였지만 실행 단계 비용은 direct의 $0.3384보다 컸다. 실행 감소가 비용 절감으로 이어지지 않았다. Run별 wall time 합계는 direct 약 140분, adaptive 약 244분으로 1.74배다. 병렬 배치의 실제 경과 시간과는 다르다.

**cca530fc 체스:** adaptive 두 반복 모두 run 예산 초과로 답이 없었다. 기록 비용은 $0.1438/$0.1767이며 다음 호출의 예약 비용까지 고려한 budget gate 때문에 $0.20 실제 사용 전에도 중단될 수 있다. Direct도 두 반복 모두 틀렸지만 finish는 했다. **cf106601 올림픽:** 두 반복 모두 4 probe + 4 execution을 쓰고도 PAN/HAI로 답이 흔들렸으며 모두 오답이다. 두 task의 adaptive 합계 비용은 $0.4652, 전체 adaptive의 34.5%다.

**Takeaway:** 해결되지 않은 state 자체를 추가 호출의 충분조건으로 삼으면 비싸진다. 새 도구·자료·검증 방법이 없어 이전의 불확실성을 다시 표현하는 상황에는 중단 판단이 필요하다. Refiner 호출을 줄이는 것만으로 비용 문제를 해결하기 어렵다.

## 5. metadata상 non-web과 실제 로컬 해결 가능성은 다르다

cf106601은 web 도구가 metadata에 표시되지 않아 집합에 남았지만, 실제 trace에서는 1928 올림픽 국가별 선수 수 자료를 찾지 못했다. 로컬 파일 검색과 차단된 네트워크 요청 뒤에 기억 기반 후보를 반복했다. 이것은 무료 web 도구의 실패와 다른 문제다. 이번 run에는 web 도구가 없으며, web 제외 기준이 실질적인 외부지식 의존성까지 보장하지 않는다.

**Takeaway:** 현재 집합의 결과는 그대로 보존하고, 분석에서 첨부파일/문제 본문으로 닫힌 과제와 외부 사실에 의존하는 과제를 따로 표시하는 편이 낫다. 이번 점수를 보고 나서 어려운 task를 제거하면 비교 해석이 왜곡된다.

## 6. 구현 관측과 권장 순서

84 probe 라운드 중 refinement 상태는 rewritten 79, refiner_failed 5였다. 그러나 rewritten 중 20건은 instruction 본문이 draft와 정확히 같았다. 상태 이름만으로 rewrite 효과를 계산하면 안 된다. ID로 execute한 64개 action의 선택 ID와 기록된 selected_instruction_id는 일치했다. 이 확인만으로 모든 worker/evaluator 메시지의 byte-level 일치를 보증하지는 않는다. Adaptive 72 runs 중 25건은 execute 없이 끝났으며, probe가 실질 계산을 이미 수행하는 경우도 있었다.

권장 우선순위:

1. **최종 답 계약:** answer에는 요구된 값만, 설명은 rationale/state에 보존. Direct에도 동일하게 적용한다. 공식 scorer는 유지한다.
2. **평가 기준:** 원 질문의 전제와 외부 검증이 필요한 가정을 분리하고, 답에 영향을 주는 미해결점에 집중한다.
3. **다음 행동의 가치:** 새 근거를 얻을 수 없는 반복은 중단하고, 예산 소진 전 finish 여유를 확보한다.
4. **효과 분리:** 이후 비교는 최종 답 계약을 고정한 뒤 probe/evaluator 효과와 refiner의 추가 효과를 구분한다. 현 trace로 refiner의 독립적인 득실은 확정할 수 없다.

재현 자료:

- `outputs/experiments/2026-10-12_gaia-nonweb-comparison/analysis/scores.csv`
- `outputs/experiments/2026-10-12_gaia-nonweb-comparison-rep1/analysis/scores.csv`
- `outputs/experiments/2026-10-12_gaia-nonweb-comparison/analysis/two_repetitions_summary.json`
- `outputs/experiments/2026-10-12_gaia-nonweb-comparison/analysis/trace-review/`의 task별 원문 발췌
- 각 실험의 `runs/<task_id>/<run>/run.json`, `artifacts/`, `llm_calls.jsonl`
