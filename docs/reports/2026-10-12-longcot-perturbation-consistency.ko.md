# LongCoT linear: 첫 노드 perturbation 일관성으로 worker 고르기 (2026-10-12)

## 요약
- **질문:** 첫 subtask(node_0)를 풀이 방식만 바꿔 5번 풀게 했을 때 가장 일관된 worker에게 나머지를 맡기면, worker를 무작위로 고를 때보다 나은가.
- **결과 한 줄:** 일관성으로 고른 worker는 무작위 worker보다 나았지만, 그 이득은 대부분 **가장 약한 worker(gemini)를 피한 효과**였고 **평균적으로 가장 강한 worker(haiku)를 늘 쓰는 것과 비슷한 수준**이었다. 첫 노드가 쉬워 easy 23문제 중 20, hard 26문제 중 19가 동점이었다.
- **정답률(사슬 전체 정답):** easy에서 선택 13% vs 무작위 worker 6.3%(차이 +6.8%p, 95% CI [−3.4, +18.8]). hard는 모든 조건이 0–3%라 비교 불가.
- **보조 지표(요청 노드 중 맞힌 비율, 결과를 본 뒤 추가):** easy 0.54 vs 0.41(+0.13, CI [+0.01, +0.25]); hard 0.26 vs 0.21(+0.05, CI [−0.02, +0.13]). haiku 고정은 easy 0.56, hard 0.27.
- **비용:** 유효 실험 $21.96, 버그로 무효 처리한 실행 포함 총 $27.36.

## 설정
- 데이터: LongCoT math, `linear` 템플릿. easy 23문제(노드 15개), hard 26문제(노드 50개). 모델에는 문제 문장만, 정답은 분석 단계에서만.
- worker: luna-high(GPT-6 Luna, effort high), haiku-high(Claude Haiku 5.5, high), gemini(Gemini 3.1 Flash-Lite, minimal).
- **일관성 probe:** worker마다 node_0을 5가지 풀이 지시(단계별 CoT, Plan-and-Solve, 풀고 검산, Step-back, 지시 없음)로 1번씩. 문제 문장은 같음. 동치 답 최대 묶음 비율 = 일관성. 최고 worker 선택, 동점은 문제별 seed 무작위.
- **`consistency_routed`:** 고른 worker가 자기 최빈 node_0 답을 이어받아 node_1부터 끝까지 노드별로 푼다(1회).
- **`fixed_<worker>` × 3:** 각 worker가 전체를 노드별로 푼다. 선택에 쓰지 않는 비교용.
- 노드에 답이 없거나 출력 한도(32,768 token)로 끊기면 그 실행은 멈추고 오답. 답 동치는 LongCoT 공식 math 비교(LLM fallback 없음) + 표기 정리.
- 코드: branch `perturbation-consistency`(`src/perturbation_consistency/`, `scripts/*perturbation*`), 결정 C29.

## 결과

### easy (23문제)
| 조건 | 사슬 전체 정답 | 요청 노드 정답 비율(보조) |
|---|---|---|
| `consistency_routed` | 0.130 | 0.540 |
| 무작위 worker(고정 실행 평균) | 0.063 | 0.407 |
| 사후 최고 worker | 0.188 | 0.614 |
| 고정 실행 9개 다수결 | 0.174 | — |
| haiku-high 고정 | 0.130 | 0.559 |
| luna-high 고정 | 0.058 | 0.432 |
| gemini 고정 | 0.000 | 0.228 |

- 선택 신호를 독립 실행으로 본 값: 고른 worker의 고정 실행 정답률 − 평균 = +0.097(CI [+0.01, +0.19]), 보조 지표로 +0.12(CI [+0.05, +0.21]).
- 동점 20/23. 세 모델 모두 동점 14, luna·haiku 동점 5. 평균 일관성 luna 0.95, haiku 0.98, gemini 0.78. gemini는 23문제 중 2번만 선택됐다.

### hard (26문제, 13+13 두 묶음 합산)
| 조건 | 사슬 전체 정답 | 요청 노드 정답 비율(보조) |
|---|---|---|
| `consistency_routed` | 0.000 | 0.263 |
| 무작위 worker | 0.009 | 0.210 |
| 사후 최고 worker | 0.026 | 0.347 |
| haiku-high 고정 | 0.026 | 0.274 |
| luna-high 고정 | 0.000 | 0.231 |
| gemini 고정 | 0.000 | 0.125 |

- 고른 worker − 평균(보조 지표) = +0.048(CI [0.00, +0.10]). worker 성적이 서로 다른 24문제에서 고른 worker가 사후 최고였던 비율 0.50.
- 동점 19/26. 두 번째 묶음에서는 gemini가 6번 선택됐다(단독 최고 1, 동점 무작위 5).
- routed 실행 26개 중 13개가 출력 한도로 중간에 멈췄다. 고정 실행도 자주 멈춘다(hard 고정 실행 234개 중 72개).

## 해석
1. **첫 노드는 worker를 가르기에 너무 쉽다.** 대부분 5번 모두 같은 답이라 일관성이 1.0으로 몰리고, 선택은 동점 무작위로 정해진다.
2. **효과는 "약한 worker 배제"로 보인다.** gemini의 일관성이 자주 낮아 동점 집합에서 빠지고, 나머지 둘 중 무작위로 골라도 평균보다 낫다. 그래서 선택 결과는 늘 haiku를 쓰는 것과 비슷하다(easy 0.54 vs 0.56, hard 0.26 vs 0.27).
3. **routed 수치에는 첫 답 개선이 섞여 있다.** routed는 15개 node_0 답 중 고른 worker의 최빈 답에서 시작한다. 고른 worker의 고정 실행으로 본 신호(+0.10/+0.12 easy, +0.05 hard)가 worker 선택만의 값에 가깝다.
4. **hard는 사슬 전체 정답이 거의 0이라** 주 지표로는 아무것도 말할 수 없다. 보조 지표는 결과를 본 뒤 추가한 것이므로 탐색적 결과로만 읽는다.

## 실행 중 발견·수정한 문제 (모두 커밋 기록)
- **답 표기:** `\(52\)`, `**52**`, `\dfrac{8}{9}`, `4\,056\,195` 등이 같은 값으로 인정되지 않았다. 표기 정리 후 비교(7a18e70).
- **답 추출:** luna-high가 `\boxed{\text{answer}=…}`로 답을 써서 17개 응답을 "답 없음"으로 처리했다(2994eda). hard에서 줄 중간의 `answer = …` 3건도 같은 문제(3cc731c 이후).
- **비교 crash:** 긴 자유 형식 답에서 sympy가 IndexError를 내 routed 작업 하나가 죽었다. 예외는 "판정 불가"로 처리(2994eda).
- 처리: 답 추출 버그가 있던 pilot과 첫 easy 실험은 `SUPERSEDED.md`를 남기고 easy 23문제를 새로 돌렸다(`linear-easy-v2`). hard-b의 고정 실행 3개는 `scripts/rerun_perturbation_runs.py`로 다시 돌렸고 옛 실행은 `runs/<qid>/superseded/`에 남겼다(`RERUNS.md`).
- 남은 것: easy-15 luna probe 응답 1개가 `\begin{aligned}` 안에 답을 써서 이상한 식으로 읽힌다(5개 샘플 중 1개).

## 한계
- 조건마다 문제당 1회(routed)·3회(고정)라 문제 수가 작고 CI가 넓다. 보조 지표는 사후 추가.
- 노드별로 끊어 실행하는 형식이라 공식 LongCoT(한 번에 전체 풀이, 도구 없음) 점수와 비교할 수 없다.
- 출력 한도로 멈춘 실행이 많다. 한도(32,768)는 spec 고정값이다.
- worker 3개, linear 템플릿, math 영역만.

## 다음에 해볼 만한 것
- 선택 구간을 node_0 하나가 아니라 앞 2–3개 노드로 넓히기. 고정 실행 기록만으로 사후 분석이 가능하다(추가 비용 없음).
- 비교 기준에 "평균 최고 worker 고정"을 명시적으로 넣기. 현재 결과는 이 기준을 넘지 못했다.
- 동점 처리를 무작위 대신 비용이 싼 worker 우선 등으로 바꿀지 검토.

## 산출물
- 유효: `outputs/experiments/2026-10-11_longcot-perturbation-consistency-linear-easy-v2/`, `…-linear-hard-a/`, `…-linear-hard-b/`
- hard 합산 분석: `outputs/analysis/2026-10-12_longcot-perturbation-consistency-linear-hard/`
- 무효(근거로 보존): `…-pilot/`, `…-linear-easy/` (`SUPERSEDED.md`)
