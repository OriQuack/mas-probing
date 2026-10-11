# perturbation_consistency

Worker routing by perturbation consistency on LongCoT math chains. A separate experiment harness, not part of the
`minpilot` orchestrator framework: it reuses only `minpilot`'s LLM client, trace/budget accounting and the LongCoT
loader (`minpilot.data.longcot`).

| 단계 | 내용 |
|---|---|
| 일관성 probe | 각 worker가 첫 노드를 풀이 방식 지시만 다른 n개 variant(단계별 CoT, Plan-and-Solve, 풀고 검산, Step-back, 풀이 지시 없음)로 풀고, 동치 답 최대 묶음 비율을 일관성으로 계산 |
| `consistency_routed` | 일관성이 가장 높은 worker(동점은 문제별 seed 무작위)가 자기 최빈 첫 답을 이어받아 나머지 노드를 풂 |
| `fixed_<worker>` | 각 worker가 전체 노드를 반복 수행하는 비교용 실행. 선택에 쓰지 않음 |

모든 arm은 노드를 하나씩 풀고 의존 노드의 값을 다음 노드 prompt에 넣는다. 문제 본문은 바꾸지 않는다. 답이 없거나
token 한도로 끊긴 노드에서 그 실행은 멈추고 오답으로 센다. 답의 동치는 LongCoT 공식 math 비교를 쓰며 LLM fallback
judge는 쓰지 않는다. 정답은 분석 단계에서만 읽는다.

```bash
python scripts/run_perturbation_consistency.py --experiment outputs/experiments/<date>_longcot-perturbation-consistency \
    --template linear --limit 3 --dry-run          # 호출 없이 노드 분해와 prompt 확인
python scripts/run_perturbation_consistency.py --experiment ... --template linear --limit 3 --session-cost-usd 8
python scripts/analyze_perturbation_consistency.py outputs/experiments/<date>_longcot-perturbation-consistency
```

결과는 문제 단위로 비교한다(노드를 독립 표본으로 세지 않음). 우리 multi-agent 노드 단위 실행 결과는 단일 호출·도구
없는 공식 LongCoT 점수와 구분해 보고한다.
