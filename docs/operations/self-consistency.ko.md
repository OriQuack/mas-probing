# 첫 segment self-consistency baseline

`self-consistency-v1`은 instruction-selection과 별도 디렉터리에서 실행한다. 기본 source는
`outputs/experiments/2026-10-13_instruction-selection-session-r2`의 고정된 41문제다.
Source 실험에 쓰지 않으며, 후보 생성이나 기존 probe 답의 재사용은 하지 않는다.

`haiku-medium`이 source의 원본 naive prompt로 첫 segment를 새로 20회 푼다.
같은 sample의 앞 K=1·3·5·10·20개를 기존 수학 동치 판정으로 묶어 최빈 답을 선택한다.
동점은 가장 앞 sample의 답이다. 실패 답은 투표에서 제외하며 실패 개수는 별도 기록한다.
이는 naive 원본 반복 baseline이며 별도의 CoT 문구를 추가하지 않는다.

각 K의 답에서 같은 worker가 원본 instruction으로 나머지 chain을 3회 진행한다.
이후 subtask에는 투표하지 않는다. 같은 문제에서 K들이 동치인 답을 고르면 가장 작은 K의
답 표현과 continuation 3회를 공유한다. 출발 답이 없으면 실패이고, 첫 틀린 요청 node에서
종료한다. 미도달 요청 node는 오답이다. Gold는 종료와 평가에만 사용하고 모델에 주지 않는다.
따라서 비용은 gold 종료를 사용하는 기존 실험과 같은 평가용 비용이며 배포 비용 추정은 아니다.

## 실행

`doh_minpilot` 환경을 사용한다. 아래 dry-run은 쓰기와 API 호출을 하지 않는다.

```bash
python scripts/run_self_consistency.py prepare \
  --experiment outputs/experiments/2026-10-13_self-consistency --dry-run
python scripts/run_self_consistency.py prepare \
  --experiment outputs/experiments/2026-10-13_self-consistency
```

유료 단계의 두 비용 상한은 실행 전에 정해야 한다. `--session-cost-usd`는 이전 실행을 포함한
해당 단계의 누적 상한, `--run-cost-usd`는 probe 호출 하나 또는 continuation rollout 하나의
상한이다. 아래 변수에 정한 숫자를 넣는다. Probe는 최대 820호출, continuation은 답 공유 전
최대 615 rollout이며 rollout 하나는 여러 node 호출을 포함할 수 있다.

```bash
python scripts/run_self_consistency.py probe \
  --experiment outputs/experiments/2026-10-13_self-consistency --batch \
  --session-cost-usd "$PROBE_BUDGET_USD" --run-cost-usd "$PROBE_RUN_BUDGET_USD"
python scripts/run_self_consistency.py continue \
  --experiment outputs/experiments/2026-10-13_self-consistency \
  --session-cost-usd "$CONTINUATION_BUDGET_USD" --run-cost-usd "$CONTINUATION_RUN_BUDGET_USD"
python scripts/run_self_consistency.py analyze \
  --experiment outputs/experiments/2026-10-13_self-consistency
```

Probe 완료 전에 continuation을 시작할 수 없다. 선택한 답과 probe 해시는 `votes.json`에
고정한다. 재실행은 이미 기록된 성공·실패 slot을 모두 건너뛴다. Sync continuation도 개별 slot을 먼저 원자적으로 저장하고 JSONL을 복원한다. 예산 실패도 기록된 실패이며
삭제해서 재시도하지 않는다. 중단되어 미기록인 slot은 새로 실행하고 이전 trace 비용을 포함한다.
Continuation 중단 시 부분 대화를 재사용하지 않는다. 불명 비용 예약액은 별도 표시하고 재사용하지 않는다.

준비 시 source artifact 해시·naive prompt·worker 설정·local dataset revision을 검증한다.
대상·질문·prompt, 구현 해시, 실제 코드 snapshot을 저장한다. 이후 코드·모델·입력·revision이
바뀌면 기존 실험을 실행하지 못하며 snapshot 환경이나 새 실험을 사용해야 한다.

## 산출물과 해석

- 실행 결과: `results.jsonl`, `votes.json`, `continuation.jsonl`, 단계별 job journal과 LLM trace.
- 분석: `analysis/summary.json`, `analysis/per_task.csv`, `analysis/accuracy_cost.png`.
- K별 첫 segment·후속 요청 node·전체 요청 node 정확도, 전체 성공률과 K=1 대비 차이.
  문제별 동일 가중치와 paired bootstrap CI를 사용한다. 후속 요청 node가 없는 문제는 후속 지표에서 제외한다.
- `policy_cost_usd_3_reps`: 앞 K개 probe + continuation 3회 비용.
  `policy_cost_usd_mean_1_rep`: 앞 K개 probe + continuation 평균 1회 비용.
  공유 continuation은 각 정책의 독립 실행 비용에 포함하되 실제 실험 지출은 한 번만 센다.
  이 정책 비용은 기록된 완료 slot 비용이고, 중단·미기록 호출과 불명 비용은 실제 단계별 비용에서 확인한다.
- Source 선택 결과가 있으면 instruction 선택·naive·oracle의 정확도와 비용도 함께 기록한다.
  Oracle 비용에는 모든 후보 continuation 평가가 포함된다. Source 결과 해시와 완료 여부도 기록한다.
  Source가 아직 선택 전이면 비교 불가로 표시하며, source 실행 완료 후 분석을 다시 실행할 수 있다.
- 미완료 실행의 점수는 0으로 집계하고 summary와 그래프에 미완료 표시한다. 이는 최종 성능으로 해석하지 않는다.

이번 실험은 **cost-matched 비교가 아니다**. K별 accuracy–cost 곡선으로 반복의 추가 이득을 확인한다.
Instruction 실험의 다중 worker 답 결합과 이 baseline의 단일 worker 반복이라는 차이도 남아 있다.
정확도 비교에는 평균 1회 continuation 비용을 우선 사용하고, 3회 비용과 실제 총지출도 함께 확인한다.
Session에서 작성한 instruction의 추가 API 비용 0은 작성 노력 자체가 없었다는 의미가 아니다.

```bash
python -m pytest tests/test_self_consistency.py tests/test_positive_instruction_selection.py
```

## 단일 durable batch와 모니터

`probe --batch`는 모든 820개 요청을 하나의 batch로 제출한다. 제출 전에
`probe_batch/requests.json`에 custom ID·task·sample·본문·trace 경로를 고정하고 fsync한다.
`probe_batch/submission.json`에는 제출 상태와 batch ID를 저장한다. `--submit-only`를
붙이면 ID 저장 직후 반환하며, 같은 명령에서 이 옵션을 빼면 기존 ID를 수집한다.
POST 결과가 불명확하면 자동 재제출하지 않는다. 저장된 응답에 batch ID가 있으면 복구한다.

원본 terminal 응답과 개별 결과 slot을 저장한 뒤 `results.jsonl`을 복원하므로 결과 순서는
매핑에 영향을 주지 않는다. 실패한 batch의 자동 재구매는 하지 않는다.
`run_self_consistency_workflow.py --experiment DIR --probe-cap 15 --continuation-cap 12`는
수집 → sync continuation 3회 → 분석을 순서대로 실행한다. batch가 completed가 아니면
continuation을 시작하지 않는다. 각 단계는 writer lock, controller는 별도 workflow lock을 사용한다.
`monitor_self_consistency.py --experiment DIR --once`는 local 상태만 읽어
`monitor_status.json`을 갱신하며 API 요청이나 실행·재시작을 하지 않는다.
Controller 상태는 `workflow_status.json`, 단계별 출력은 `probe.log`·`continue.log`·`analyze.log`에 남는다.
