# LongCoT instruction 합의 선택: 41문제 실행과 실패 분석

### 목적

LongCoT math linear 사슬에서 문제마다 후보 instruction 4개 중 하나를 첫 묶음 probe 답의 합의로 고르면,
뒤 node까지 이어 푼 정확도가 naive(지시 없음)보다 나아지는지 본다. 탐색 실험이다.

### 설정

- `instruction-selection-v3`, 후보 revision r2. 설계는 [운영 문서](../operations/instruction-selection.ko.md).
- 문제: [segment routing](2026-10-13-longcot-segment-routing.ko.md)과 같은 linear 41문제(easy 20, medium 13, hard 8).
- 후보: naive와 `analogical`(유사 문제)·`clarify`(의미 명료화)·`local_check`(국소 검산). 세 축은 작업 세션이
  문제마다 직접 작성했고(약 100단어), 외부 LLM 검토를 반영해 r2로 고쳤다. 자기 검토이며 추가 모델 비용은 0이다.
- 선택: haiku-medium·luna-medium·flash-lite-high가 후보마다 첫 묶음(node_0부터 첫 요청 node까지)을 3회 풀고,
  9개 답 중 최빈 답 비율이 가장 높은 후보를 고른다. 동점은 seed 0 균등 무작위. 실패 답은 분모 9에 남긴다.
- 실행: 후보마다 9개 답의 최빈값에서 출발해 haiku-medium이 뒤 node를 node마다 새 단일 호출로 3회 이어 푼다
  (492 rollout). 같은 후보 instruction을 모든 node에 붙인다. 첫 틀린 요청 node에서 멈추고 이후 요청 node는 오답이다.
- 점수: 문제 동일 가중, rep 평균. 95% CI는 문제 단위 paired bootstrap.
- 디렉터리: probe `outputs/experiments/2026-10-13_instruction-selection-session-r2`,
  선택·실행·분석 `outputs/experiments/2026-10-15_instruction-selection-session-r2-continuation`
  (자동 분석 `analysis/brief.ko.md`, `summary.json`, `additional_diagnostics.json`).

### 비용과 상태

| 단계 | 계획 | 상태 | 기록 비용 |
|---|---:|---|---:|
| probe | 1476 | ok 1436, 길이 초과 40(실패 답으로 집계) | batch $18.02 + sync $6.98 (청구액 미제공 batch 1개 제외) |
| continuation | 492 rollout | 누락·중복 0, LLM 시도 6785 중 ok 6781, API 오류 0 | $12.26 (비용 미확정 예약 $0.07) |

### 결과

| 정책 | 첫 묶음 정답률 | 뒤 요청 node 정확도 | 전체 요청 node 정확도 | 전체 성공률 |
|---|---:|---:|---:|---:|
| selected (합의) | 82.9% | 26.2% | 41.1% | 8.1% |
| naive | 85.4% | 38.5% | 50.8% | 20.3% |
| analogical | 82.9% | 27.4% | 42.1% | 10.6% |
| clarify | 82.9% | 29.0% | 43.2% | 11.4% |
| local_check | 85.4% | 29.9% | 44.7% | 10.6% |
| random | 84.1% | 31.2% | 45.2% | 13.2% |
| best_in_hindsight | 92.7% | 46.5% | 58.5% | 26.8% |

- 뒤 요청 node에서 selected − naive = **−12.3%p** (CI −21.7–−3.4).
- 선택 분포: local_check 16, analogical 11, clarify 8, naive 6. 최고 동점 후보 수 1·2·3·4개가 20·10·7·4문제.
- 난이도별 뒤 node 정확도(selected / naive): easy 27.8% / 34.2%, medium 20.9% / 46.6%, hard 30.6% / 36.1%.

### 왜 selected가 낮은가

뒤 요청 node 차이를 두 몫으로 나눈다.

| 몫 | 정의 | 평균 | 95% CI |
|---|---|---:|---:|
| instruction 효과 | 비-naive 세 후보 평균 − naive | −9.7%p | −17.9–−1.9 |
| 선택 효과 | selected − 비-naive 세 후보 평균 | −2.6%p | −5.7–+0.5 |
| 합 | selected − naive | −12.3%p | −22.0–−3.4 |

분해 CI는 진단 스크립트의 재표본이라 위 결과 절의 공식 분석 CI(−21.7–−3.4)와 끝자리가 다르다.

1. **손해의 대부분(약 80%)은 instruction 자체다.** 출발 답이 네 후보 모두 같고 정답인 28문제에서도 뒤 node 정확도가
   naive보다 analogical −8.3%p(5승 11패), clarify −8.5%p(7승 13패), local_check −6.9%p(5승 12패) 낮다.
   뒤 요청 node에 도달했을 때 오답률이 naive 34.9%에서 41–43%로 오르고, node 8–50개 사슬에서 누적된다.
2. **선택 효과는 0과 구분되지 않는다.** 같은 문제 안에서 (후보 − naive) 합의 차이와 (후보 − naive) 뒤 node 점수 차이의
   상관은 r = 0.10(123쌍)이다. 합의는 첫 묶음 정답 여부는 가리키지만(최빈 답 6/9 이상이면 정답률 약 100%,
   3/9 이하면 약 30%), 첫 묶음 정답률은 네 후보가 83–85%로 비슷하고 손해는 뒤 node에서 생긴다.
3. **규칙이 naive를 덜 고른다.** 후보 4개 중 3개가 비-naive이고 동점은 무작위라 naive는 최고 동점에 든 17문제 중
   6문제에서만 뽑혔다. selected는 사실상 무작위 비-naive 후보가 되어 1의 손해를 거의 그대로 받는다.

요약: 합의는 첫 묶음의 답 수렴을 재지만 instruction의 손해는 뒤 node에서 생긴다. 신호와 손해의 위치가 다르다.

### 후보별 진단

| | 뒤 요청 node 도달 시 오답률 | 길이 초과·무응답 / 호출 | 출력 토큰 (같은 node, naive 대비 중앙값) | "undefined"류 답 / 호출 | 그런 답이 섞인 rollout (성공/실패) |
|---|---:|---:|---:|---:|---:|
| naive | 34.9% | 0.6% | 1.00× | 2.8% | 9 / 17 |
| analogical | 42.8% | 1.3% | 1.35× | 4.8% | 3 / 21 |
| clarify | 42.3% | 1.1% | 1.09× | 7.0% | 4 / 24 |
| local_check | 41.1% | 1.3% | 1.26× | 5.6% | 0 / 32 |

"undefined"류는 최종 답이 undefined, no such, does not exist 등으로 문제가 성립하지 않는다고 답한 경우다.
요청 node가 아닌 중간 node의 이런 답은 rollout을 멈추지 않고 다음 node의 의존값으로 전달된다.

### 대표 실패 유형

사례는 설명용으로 고른 것이며 각 3회 반복이다.

1. **clarify: 다시 쓰는 단계에서 조건이 빠진다.** `linear_medium_27:node_3`의 node_7(2 ≤ n ≤ 50에서
   n | φ!(n)+1인 n의 개수). naive는 n = 2, 4, p^k, 2p^k(p 홀수 소수)로 30을 3/3 맞혔다. clarify는 Given/Find로
   다시 쓰며 "the prime powers p^k"로 바꿔 8·16·32를 더 세어 3/3 모두 33을 냈다. 이 instruction에는
   "bijective simultaneous occupancy", "the toss that loses the coin" 같은 다른 node용 단서도 붙어 있다.
2. **local_check: 문자 그대로 읽기가 의존값 보정을 막는다.** `linear_easy_15:node_1`의 node_6에서 앞 node 값 97/3에
   "subtract 96"을 적용하면 하한이 −191/3이다. naive는 97을 의도한 값으로 가정해 294를 내고 다음 요청 node_10까지 맞혔다.
   local_check는 "changing it would mean altering the problem"이라며 `undefined`를 내거나(rep 0) 비정수 N을 대입해
   3889/3을 냈다(rep 1). instruction의 "do not change the problem or force a value"와 같은 방향이다. 97/3이 node_5의
   정답인지는 확인하지 않았다(요청 node가 아니어서 gold가 없다).
3. **analogical: 틀린 유사 문제가 풀이 공식이 된다.** `linear_easy_20:node_1`의 node_5(빛이 정사각형을 2021개 영역으로
   나누는 최소 반사 횟수). naive는 R = n + 2 + K로 129를 냈다. analogical은 유사 문제에서 "영역 = 2 + 교차 수"를 세우고
   (경계 반사로 늘어나는 영역 누락) 작은 예 검산도 틀린 채 679를 냈다. 출력은 3.4k에서 5.3k 토큰이다.
4. **선택: instruction이 오답으로 합의를 모은다.** `linear_easy_15:node_1` 첫 묶음에서 naive는 정답 3^{n+1}−1에 3/9,
   analogical은 오답 3^{2n}−1에 5/9였다. local_check(정답, 5/9)와 동점 무작위로 analogical이 뽑혀 이 문제는 0점이다.
   `linear_medium_4:node_4`도 local_check가 오답 1/357에 5/9, naive가 정답 1/501에 3/9여서 local_check가 뽑혔다.
   다만 첫 묶음 정답률 차이는 −2.5%p라 전체 손해에서 작은 몫이다.

### 한계

- 같은 41문제로 후보를 설계·실행한 탐색 실험이다. 후보는 첫 묶음 전문과 뒤 node 발췌를 보고 작성했다.
- selected의 첫 묶음 점수는 선택에 쓴 probe 답 그대로라 선택 편향이 있다. 뒤 node 비교에는 9개 답 결합과
  instruction 선택이 함께 들어 있다.
- 중간 node는 gold가 없어 오류가 시작된 node를 체계적으로 집계하지 않았다. naive 중간 답끼리도 다르면서 뒤 요청
  node를 맞히는 경우가 있어 naive 답과의 불일치를 오류로 볼 수 없다.
- "undefined"류 분류는 정규식 기준이다.

### 시사점

문제별 instruction을 모든 node에 똑같이 붙이는 방식이 haiku의 사슬 풀이에 해롭고, 첫 묶음 합의로는 그 손해를
볼 수 없다. 선택을 계속하려면 instruction을 첫 묶음에만 쓰거나 node별로 관련 단서만 남기는 설계, 그리고 뒤 node
일부를 포함한 probe가 필요하다. MoNaCo에서도 합의 선택은 naive와 차이가 없었다
([50문제 합산](2026-10-14-monaco-instruction-selection-extra30.ko.md)).

### 재현

```bash
python scripts/analyze_instruction_failures.py \
  outputs/experiments/2026-10-15_instruction-selection-session-r2-continuation
```

모델 호출 없이 위 분해·진단 수치를 출력한다. 결과 표는 `analysis/summary.json`, 사례 원문은 실행 디렉터리의
`continuation/<key>/attempt_<n>/llm_calls.jsonl`에 있다.
