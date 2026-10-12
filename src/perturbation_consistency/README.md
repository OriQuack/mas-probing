# perturbation_consistency

Worker routing by perturbation consistency on LongCoT math chains. A separate experiment harness, not part of the
`minpilot` orchestrator framework: it reuses only `minpilot`'s LLM client, trace/budget accounting and the LongCoT
loader (`minpilot.data.longcot`).

| 단계 | 내용 |
|---|---|
| 일관성 probe | 각 worker가 첫 노드를 풀이 방식 지시만 다른 n개 variant(단계별 CoT, Plan-and-Solve, 풀고 검산, Step-back, 풀이 지시 없음)로 풀고, 동치 답 최대 묶음 비율을 일관성으로 계산. `--probe-depth K`이면 최고 일관성이 동점인 worker만 다음 노드를 같은 방식으로 풂(최대 K개 노드, variant마다 자기 앞 답을 이어받는 chain) |
| `consistency_routed` | 일관성이 가장 높은 worker(K개 노드 뒤에도 동점이면 문제별 seed 무작위)가 마지막 probe 노드의 최빈 묶음에 든 가장 앞 variant chain의 답을 이어받아 나머지 노드를 풂 |
| `fixed_<worker>` | 각 worker가 전체 노드를 반복 수행하는 비교용 실행. 선택에 쓰지 않음 |

모든 arm은 노드를 하나씩 풀고 의존 노드의 값을 다음 노드 prompt에 넣는다. 문제 본문은 바꾸지 않는다. 답이 없거나
token 한도로 끊긴 노드에서 그 실행은 멈추고 오답으로 센다. 답의 동치는 LongCoT 공식 math 비교를 쓰며 LLM fallback
judge는 쓰지 않는다. 정답은 분석 단계에서만 읽는다.

```bash
python scripts/run_perturbation_consistency.py --experiment outputs/experiments/<date>_longcot-perturbation-consistency \
    --template linear --limit 3 --dry-run          # 호출 없이 노드 분해와 prompt 확인
python scripts/run_perturbation_consistency.py --experiment ... --template linear --limit 3 --session-cost-usd 8
python scripts/run_perturbation_consistency.py --experiment ... --difficulty medium --sample 20 --seed 0 \
    --workers luna-high haiku-high flash-high --probe-depth 3 --batch   # OpenRouter Batch API (batch.py)
python scripts/analyze_perturbation_consistency.py outputs/experiments/<date>_longcot-perturbation-consistency
```

결과는 문제 단위로 비교한다(노드를 독립 표본으로 세지 않음). 우리 multi-agent 노드 단위 실행 결과는 단일 호출·도구
없는 공식 LongCoT 점수와 구분해 보고한다.

`--batch`는 모든 호출을 OpenRouter Batch API로 보낸다(`batch.py`, token 가격 절반). 호출 thread는 결과가 올 때까지
기다리고, 새 호출이 잠시 없으면 모인 호출을 model별 batch 하나로 제출한다. 노드 하나가 batch 왕복 하나라서 chain
길이만큼 왕복이 필요하다(왕복당 수 분~최대 24시간). 제출과 실제 청구액은 `openrouter_batches.jsonl`에 남는다.
