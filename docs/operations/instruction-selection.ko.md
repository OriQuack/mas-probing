# 문제별 instruction 합의 선택 실험

`instruction-selection-v3`는 orchestrator 밖 별도 실험이다. 기존 segment-routing의
41개 대상(easy 20, medium 13, hard 8)을 그대로 사용한다. 기존 결과로 후보를 설계한 탐색 실험이다.

## 설계

기본 model 모드는 Sonnet-high가 전체 문제문만 보고 영어 지시 3개를 생성한다.
Session 모드는 현재 작업 세션에서 직접 작성·자기 검토한 후보를 추가 모델 API 호출 없이 가져온다.
축은 개념·유사 문제(`analogical`),
의미 명료화(`clarify`), 국소 검산(`local_check`)이다. 후보별 180단어 이하이고 실제 답·중간값·풀이를
제공하지 않도록 지시한다. 구조·길이·중복은 코드로 검사하지만 내용의 타당성을 보장하는 의미 검사는
없다. 생성한 실제 문구는 dry-run으로 확인할 수 있다. 원문은 그대로이며 `naive`까지 총 4개 후보다.

Worker 3명(`haiku-medium`, `luna-medium`, `flash-lite-high`)이 각 후보로 첫 묶음을 3번씩 푼다.
9개 답 중 최대 동치 답 묶음 비율로 후보를 고른다. 실패·누락 답은 묶음에 넣지 않고 분모 9는 유지한다.
최고 동점은 문제 ID와 seed 0으로 결정되는 균등 무작위 선택이다. 교차 일치율 선택은 보조 분석이다.

각 후보의 **전체 worker 답 9개의 최빈값**에서 haiku가 뒤 node를 3번 이어 푼다. 출발 답 동점은
worker 등록 순서(haiku, luna, flash-lite), 그 안에서 sample 순서로 가장 먼저 나온 답을 따른다.
기록 도착 순서는 영향을 주지 않는다. 모든 node에 같은 후보 지시를 적용하고 최종 답 형식은 공통이다.
Naive에 암묵적 CoT 지시를 추가하지 않는다. 첫 틀린 요청 node에서 종료하고 이후 요청 node는 오답이다.
정답은 종료 판정과 분석에만 사용한다. 여러 worker의 답 결합과 지시 선택의 합친 효과를 측정하는 설계다.
출발 답은 선택에 쓴 바로 그 9개 답의 최빈값이므로, `selected`의 첫 묶음 점수에는 잡음이 좋게 나와 뽑힌 몫
(선택 편향)도 들어 있다. 뒤 node는 새로 풀어 이 편향이 없다.

## 실행

`doh_minpilot` 환경에서 사용한다. 아래 dry-run은 파일 생성·API 호출 없이 계획과 prompt를 보여준다.
생성 전 instruction은 placeholder이고, 생성 후 dry-run은 실제 문구를 보여준다.

```bash
python scripts/run_instruction_selection.py prepare \
  --experiment outputs/experiments/2026-10-13_instruction-selection --dry-run
python scripts/run_instruction_selection.py prepare \
  --experiment outputs/experiments/2026-10-13_instruction-selection
```

기본 source는 `outputs/experiments/2026-10-12_longcot-segment-routing-i`다. 새 실험 디렉터리를 사용한다.

### 현재 세션에서 직접 작성한 후보 사용

```bash
python scripts/run_instruction_selection.py prepare \
  --experiment outputs/experiments/2026-10-13_instruction-selection-session --generation-mode session
python scripts/run_instruction_selection.py import-candidates \
  --experiment outputs/experiments/2026-10-13_instruction-selection-session \
  --candidate-file outputs/analysis/2026-10-13_instruction-candidates/candidates.reviewed.jsonl \
  --author 'Codex session author; author self-review'
python scripts/run_instruction_selection.py probe \
  --experiment outputs/experiments/2026-10-13_instruction-selection-session --batch --dry-run
```

가져오기 파일은 대상별 JSONL이며 `target_id`, `instructions`(naive 제외 세 축),
`review`(`accepted: true`, 비어 있지 않은 `notes`)를 갖는다. 모든 대상과 문구를 검사한 뒤 한 번에 고정한다.
작성자·자기 검토 여부·원본 파일 해시·입력 범위·추가 모델 API 비용 0을 manifest에 기록한다.
현재 후보는 첫 묶음 전문과 뒤 node 발췌문을 보고 작성했으며 정답이나 실행 답으로 수정하지 않았다.
작성자가 검토까지 수행하므로 독립 심사라고 해석하지 않는다.

### 유료 실행

유료 단계는 사용자 지정 비용 상한이 필수다. 아래 변수는 실행 전에 정한 숫자이며 기본 예산은 없다.
`--session-cost-usd`는 **이전 실행까지 포함한 해당 단계의 누적 상한**이다.
`--run-cost-usd`는 생성 시도 / probe 호출 / continuation rollout 하나의 상한이다.
기본 sync이며 `--batch`를 추가하면 기존 batch transport를 사용한다(최대 128개 동시 대기 job).

```bash
python scripts/run_instruction_selection.py generate \
  --experiment outputs/experiments/2026-10-13_instruction-selection \
  --session-cost-usd "$GENERATION_BUDGET_USD" --run-cost-usd "$GENERATION_RUN_BUDGET_USD"
python scripts/run_instruction_selection.py probe \
  --experiment outputs/experiments/2026-10-13_instruction-selection --dry-run
python scripts/run_instruction_selection.py probe \
  --experiment outputs/experiments/2026-10-13_instruction-selection \
  --session-cost-usd "$PROBE_BUDGET_USD" --run-cost-usd "$PROBE_RUN_BUDGET_USD"
python scripts/run_instruction_selection.py select \
  --experiment outputs/experiments/2026-10-13_instruction-selection
python scripts/run_instruction_selection.py continue \
  --experiment outputs/experiments/2026-10-13_instruction-selection \
  --session-cost-usd "$CONTINUATION_BUDGET_USD" --run-cost-usd "$CONTINUATION_RUN_BUDGET_USD"
python scripts/run_instruction_selection.py analyze \
  --experiment outputs/experiments/2026-10-13_instruction-selection
```

생성은 문제당 최대 3시도다. 예산에 막힌 생성은 pending이며 상한 조정 후 재개할 수 있다.
3시도 모두 실패해도 대상을 제거하지 않는다. Naive 외 후보의 probe·continuation은 실패로 집계한다.
Probe·continuation 재실행은 기록된 성공·실패 slot을 모두 건너뛴다. 예산 실패도 slot의 실패이며 기록을
삭제해 재시도하지 않는다. 프로세스 중단으로 기록되지 않은 slot은 새 실행하고 기존 trace 비용을 포함한다.
중단된 rollout의 부분 대화는 재사용하지 않는다. 비용 불명 호출은 청구 비용과 분리하고 예약액을 예산에 남긴다.

## 산출물과 해석

- 준비: manifest, 고정 대상, 질문 전용 입력, dirty source를 포함한 코드 snapshot.
- 생성 완료: `candidates.jsonl`, `generation_attempts.jsonl`, `prompts.jsonl`, `planned.csv`.
  후보·입력·계획의 해시를 고정하며 수정하려면 새 실험을 만든다.
- 실행: `results.jsonl`, `selection.jsonl`, `selection_meta.json`, `continuation.jsonl`.
  단계별 job journal에 선언된 경로에 전체 LLM trace가 있다. Probe가 바뀌면 고정된 선택을 재사용하지 못한다.
- 분석: `analysis/summary.json`, `analysis/node_order_accuracy.png`.

합의 선택, naive 및 축별 고정, 균등 무작위, 사후 최고, 보조 교차 일치율 선택, 최고 동점 후보 평균을
비교한다. **사후 최고는 문제마다 전체 요청 node 정확도의 3회 평균이 가장 높은 후보 하나**를 고른다.
node마다 최대를 고르지 않는다. 첫 묶음·뒤 요청 node·전체 정확도와 전체 성공률, node 순서별 정확도를
보고한다. 뒤 점수에도 앞 실패로 도달하지 못한 node를 포함한다.

문제별 같은 가중치이며 누락 실행은 0점이다. 95% CI는 문제 단위 paired bootstrap이다.
9개 답·27개 교차 쌍·반복 실행을 독립 문제로 취급하지 않는다. 비용은 단계별로 나누고 batch 청구 합계와
호출별 비용 추정치를 별도 표시한다. Probe와 독립적인 새 실행에서 지시 효과를 검증한 결과로 해석하지 않는다.

```bash
python -m pytest tests/test_positive_instruction_selection.py
python -m pytest
```
