### **동기**

여러 worker 중 하나에게 긴 작업을 맡길 때, 앞쪽 subtask를 푼 결과만 보고 맡길 worker를 고를 수 있는가?

1. Worker가 앞쪽 subtask를 여러 변형으로 풀었을 때 답이 얼마나 일치하는지(consistency)가, 그 subtask와 뒤 subtask들을 맞힐지 예측하는가?
2. 그 예측으로 worker를 고르면 무작위로 고르거나 가장 강한 worker를 고정해 쓰는 것보다 나은가?

### **설정**

**Benchmark**

- LongCoT math의 linear 문제
- 한 문제는 작은 수학 문제(node)가 줄지어 있는 사슬이고, 각 node는 앞 node의 답을 입력으로 쓴다.
- 요청 node: 문제 끝에서 node 3-4개의 중간 정답을 묻고, GT를 제공한다.

**“앞쪽 subtask”**

- node_0부터 첫 요청 node까지를 한 번의 호출로 풀게 한다.
- 묶음의 마지막 node가 요청 node이므로 정답으로 채점할 수 있다.

**일관성**

- worker가 같은 묶음을 n번 풀었을 때, 마지막 node 답 중 같은 값 수 / n
- **최빈 답**을 그 worker의 답으로 본다.

### **Pre-pilot: 변형 고르기**

- 문제: medium 12·hard 8문제. Subtask 끝은 node_1–4 중 첫 요청 node
- worker: haiku5.5-medium, luna6.1-medium, flash3.8-medium
- 조건 5개 × 3 sample:
    - `repeat`: 같은 prompt 3번.
    - `instruction`: 문제 앞에 지시문 하나. 단계별로 풀기 / chain 전체 계획 먼저 / 다음 문제로 넘기기 전 다른 방법으로 검산.
    - `surface`: paraphrase / Given·Dependencies·Find 형식으로 재구성 / 주제와 관련된 참인 문장 하나 추가.
    - `methods`: Sonnet이 문제마다 쓴 서로 다른 풀이 전략 3개를 sample마다 하나씩.
    - `avoid_first`: 같은 지시문 3번. "가장 자연스러운 풀이 방식을 한 줄로 적고, 그 방식 없이 풀어라."
- 조건 비교는 모든 조건에서 3 sample이 다 남은 11문제로 진행한다.

!image.png

- Subtask consistency vs. accuracy AUROC가 가장 낮은 `methods`·`avoid_first`를 빼고 `repeat` , `instruction` , `surface` 를 남긴다.

### **Pilot**

- 문제: linear 41문제(easy 20, medium 14, hard 8). Subtask 끝은 node_1–k 중 첫 요청 node(k = easy 8, medium 6, hard 4).
- probe: 조건 3개 × 5 sample, worker당 subtask 15번.
    - `repeat` (대조군): 원래 subtask 그대로 5번.
    - `instruction`: 원래 묶음 뒤에 풀이 지시문 하나를 붙인다. 문제 문장은 그대로이다. sample마다 다른 지시문(실제 prompt는 영어, 아래는 요약 번역):
        - zero-shot CoT: "Let's think step by step."
        - Plan-and-Solve: "먼저 문제를 이해하고 변수와 수치를 뽑아 계획을 세운 뒤, 계획대로 중간값을 계산하며 단계별로 풀어라."
        - step-back: "먼저 한발 물러서서 이 문제들에 쓰이는 개념과 원리를 적고, 그 원리로 풀어라."
        - analogical prompting: "관련 있으면서 서로 다른 문제 3개를 떠올려 각각 설명하고 풀이를 쓴 뒤, 위 문제들을 풀어라."
        - chain-of-verification: "문제를 풀고, 답을 확인하는 검증 질문을 써서 답한 뒤, 그에 따라 고친 최종 답을 내라."
    - `surface`: 지시문은 붙이지 않고 문제 표현을 바꾼다. 숫자·수식·node 이름·의존 관계는 그대로다. sample마다 다른 방식:
        - paraphrase: Sonnet이 문장을 바꿔 쓴다. 예: "What is the integer formed by the rightmost two digits of …?" → "Find the two-digit number made up of the last two digits of …".
        - 다시 읽기: 묶음 전체를 "Read the question again: " 뒤에 한 번 더 붙인다.
        - 형식 변경: "Problem node_0: …" 줄 대신 `PROBLEM [node_0]` 머리와 `--` 구분선으로 감싼다.
        - 순서 변경: node를 다른 순서로 나열한다(예: node_1, node_0). node 이름과 "[node_0의 답 − 49]" 참조는 그대로다.
        - 무관한 문장: 한 node에 풀이와 상관없는 문장 하나를 넣는다. 예: node_1에 "Mia filled 9 pages of her notebook while thinking about these sequences."
- worker: haiku5.5-medium, luna6.1-medium, flash3.5-lite-high.
- 이어 풀기: worker마다 자기 15개 답의 최빈 답에서 시작해 나머지 node를 한 node씩 풀고, 이를 3번 반복한다. 처음 틀린 요청 node에서 멈추고 그 뒤 요청 node는 오답으로 센다.
- **점수**: 요청 node(묶음 끝 포함) 중 맞힌 비율. 3번 반복의 평균을 내고 문제마다 같은 가중치를 준다.
- 고르는 규칙:
    - **일관성 선택**: 조건별로 일관성이 가장 높은 worker. 동점이면 동점 worker들의 평균.
    - **무작위**: 세 worker의 평균.
    - **늘 haiku**: 평균적으로 가장 강한 worker를 고정.
    - **사후 최고**: 문제마다 실제로 가장 잘한 worker.
- 비용(합계 약 $42):
    - probe worker 호출
        - `repeat` $7.05, `instruction` $7.10, `surface` $6.78
    - `surface` 재작성: 약 $1.2
    - 이어 풀기: $19.63

### **관측**

Subtask 정오답에 대한 일관성 ROC

- 일관성은 묶음 끝 답이 맞았는지를 잘 가린다. AUROC는 pre-pilot 0.84–0.93(11문제 × worker 3), pilot 0.86–0.91(41문제 × worker 3)이다.
- 변형 조건(`instruction`, `surface`)은 `repeat`보다 낫지 않다. 15개를 모두 합친 `all_15`가 가장 높다(0.91).
    
    !image.png
    

Subtask 일관성으로 trajectory 전체를 맞혔는지를 예측한

- 단위는 이어 풀기 실행 369개이다. 모든 조건에서 곡선이 대각선에 가깝고 AUROC는 0.55–0.60이다.
    
    !image.png
    

요청 node 순서별 정확도

- Subtask 이후의 요청 node에서는 정확도가 빠르게 떨어지고, 일관성의 예측력도 약해진다. 2번째 요청 node의 AUROC는 0.62–0.69이다.
- 일관성 선택은 무작위보다 낫지만 늘 haiku를 쓰는 것과 같다.
    
    !image.png
    

| **조건** | **Subtask 정답 AUROC** | 전체 trajectory AUROC | **무작위 대비 [95% CI]** | **늘 haiku 대비 [95% CI]** | **probe 비용** |
| --- | --- | --- | --- | --- | --- |
| `repeat` | 0.90 | 0.60 | +0.09 [0.04, 0.15] | −0.01 [−0.06, 0.04] | $7.05 |
| `instruction` | 0.88 | 0.55 | +0.04 [0.01, 0.08] | −0.06 [−0.13, 0.01] | $7.10 |
| `surface` | 0.86 | 0.60 | +0.08 [0.04, 0.13] | −0.02 [−0.07, 0.02] | $6.78 |
| `all_15` | 0.91 | 0.58 | +0.10 [0.05, 0.15] | −0.01 [−0.06, 0.05] | $20.93 |
- Subtask 정답 AUROC: Subtask 일관성으로 그 worker의 묶음 끝 최빈 답이 맞았는지 예측. (문제, worker) 쌍 123개.
- 전체 trajectory 정답 AUROC: Subtask 일관성으로 이어 풀기 실행이 요청 node를 모두 맞혔는지 예측. 세 worker의 실행 369개 (41문제 × worker 3 × 3번 반복) 전체로, 고르는 규칙과 무관하게 계산했다.

### **결론**

Subtask 일관성은 그 묶음의 답이 맞았는지는 잘 예측하지만(AUROC 약 0.9), 사슬 전체를 맞힐지는 약하게만 예측한다(약 0.6). 그래서 일관성으로 고른 worker는 무작위보다 낫지만 가장 강한 worker를 고정해 쓰는 것보다 낫지 않았고, 변형 조건도 단순 반복보다 나은 점이 없었다.