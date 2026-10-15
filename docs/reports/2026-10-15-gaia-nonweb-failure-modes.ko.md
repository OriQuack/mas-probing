### **동기**

[worker 대화 유지·plan probe 비교](2026-10-15-gaia-nonweb-conversation-probe.ko.md)에서 보정 채점은 `direct` 26/36, `adaptive` 25/36이었다. 두 조건이 갈린 문제는 하나뿐이었다.
이 문서는 같은 실행의 오답 run 21개(`direct` 10, `adaptive` 11)를 trace로 읽고 실패 유형을 나눈다.
두 조건이 어디서 다르게 실패하고 어디서 같이 실패하는지 보는 것이 목적이다.

### **설정**

- 실행 묶음: `outputs/experiments/2026-10-15_gaia-nonweb-conversation-comparison-rerun` (v21/r23/e7, 36문제 × 2조건, 반복 1회).
- 오답 기준: `analysis/adjudicated_scores.csv`의 보정 채점 오답. 공식 채점에서만 틀린 단서 붙은 정답은 제외한다.
- 각 run의 orchestrator 지시, probe 보고, 실행 보고, evaluator `changes`, 최종 state와 finish 근거를 읽었다.
- 유형은 run마다 하나로 정했다. 기준은 최종 답을 결정한 지점이다.
- 정답은 분석에만 사용했다. 정답 값을 이 문서에 적은 것은 실패 경로를 설명하기 위해서다.

### **관측**

**1. 유형별 분포**

| 유형 | `direct` | `adaptive` |
| --- | --- | --- |
| A. 외부 지식 필요 | 3 (기억으로 답했으나 오답) | 3 (2 답 거부, 1 오답) |
| B. 정답 후보가 있었으나 내지 않음 | 1 | 3 |
| C. 해석 오류를 확정 | 3 | 2 |
| D. "답이 존재하지 않음"으로 결론 | 2 | 2 |
| E. 이미지 판독·범위 | 1 | 1 |
| 합계 | 10 | 11 |

문제별 답과 유형:

| 문제 | 정답 | `direct` 답 | 유형 | `adaptive` 답 | 유형 |
| --- | --- | --- | --- | --- | --- |
| 305ac316 | Wojciech | Michał | A | Not established | A |
| 5a0c1adf | Claus | Petr | A | Unverified | A |
| cf106601 | CUB | PAN | A | HAI | A |
| 0bb3b44a | 536 | 890 | C | Not established (536 only conditionally) | B |
| ec09fa32 | 3 | 100 | C | No unique answer | B |
| cffe0e32 | Fred | Fred (정답) | – | Fred or Micah | B |
| cca530fc | Rd5 | No guaranteed winning move established | B | 답 없음 (`budget_exceeded`) | D |
| e142056d | 16000 | 12000 | C | 12000 | C |
| 3cef3a44 | basil 포함 5개 | basil 누락 4개 | C | basil 누락 4개 | C |
| 65afbc8a | F478A7 | No valid eleventh-turn landing | D | No valid color | D |
| 9318445f | 17개 분수 | 그림 label·예제 입력 포함 | E | 그림 label·중복 포함 | E |

`direct` 표의 ec09fa32와 0bb3b44a는 evaluator가 틀린 해석을 받아들인 경우라 C로 분류했다.

**2. A. 외부 지식 필요 (305ac316, 5a0c1adf, cf106601)**

- 세 문제는 사실상 웹 조회가 필요하다. 이번 pool의 도구는 `read_file`, `view_image`, `run_python`뿐이다. worker가 Python으로 Wikipedia를 받으려 한 시도는 sandbox가 막았다.
- `direct`는 기억에 의존한 답을 확정했고 셋 다 틀렸다.
- `adaptive`는 둘을 `Not established`·`Unverified`로 끝냈다. cf106601은 HAI로 틀렸다.
- evaluator는 두 조건 모두 "source-capable worker로 보내라"를 반복했다. pool에 그런 worker는 없다.
- 이 유형은 두 조건의 점수 차이에 영향이 없다. 비용은 `direct` $0.082, `adaptive` $0.124였다.
  - `adaptive`의 probe는 2–5회였다. 매번 "출처 없음"을 다시 확인하는 데 쓰였다.

**3. B. 정답 후보가 있었으나 내지 않음**

`adaptive`가 `direct`보다 잃은 경로다. 네 건 모두 evaluator가 검증 기준을 세웠고, 지금 도구로는 그 기준을 채울 수 없었다.

- 0bb3b44a `adaptive`
  - 첫 probe에서 haiku가 536(8·60 + 56)을 계산했다.
  - evaluator는 "536은 계수와 묶음의 전제가 지지될 때만 내라"고 썼다.
  - 그 전제를 확인할 참고자료가 없어 실행 두 번 모두 값을 보류했다.
- ec09fa32 `adaptive`
  - 실행 worker가 종료 규칙 세 가지에서 확률을 계산했다. ball 3은 그중 둘에서 최대였다.
  - evaluator는 "한 숫자를 무조건적으로 내지 말라"고 썼고, orchestrator는 `No unique answer`로 끝냈다.
- cffe0e32 `adaptive`
  - 실행 worker는 선물 대응을 유일하게 정했다. 표의 열 방향만 남았고, worker는 "Recipient" 열 제목을 근거로 Fred 쪽으로 기울었다.
  - evaluator는 "열 제목만으로 Fred를 고르지 말고 두 조건부 결과를 유지하라"고 썼다.
  - 같은 문제에서 `direct`는 Fred로 맞혔다. 두 조건이 갈린 유일한 문제다.
- cca530fc `direct`
  - 두 번째 실행 worker가 직접 만든 탐색(깊이 4)에서 `Rd5`가 1위 후보였다.
  - evaluator는 "Rd5를 증명된 승리 수로 내지 말라"고 썼다.
  - 체스 엔진이 없어 증명할 수 없었고, 답은 `No guaranteed winning move established`였다.

**4. C. 해석 오류를 확정**

- e142056d (두 조건 모두 12000)
  - 원 질문의 조건은 "한 상자에는 적어도 2개가 있어야 한다"이다.
  - 두 조건 모두 이를 "어느 한 상자만 2개 이상"으로 읽었다. 동전 30개를 세 상자에 나누면 이 조건은 항상 성립한다. 그래서 (0,6,24)처럼 빈 상자가 있는 배치가 허용되고 보장 금액은 12개다.
  - "모든 상자에 2개 이상"으로 읽으면 (8,8,8)로 16개, 즉 정답 16000이 나온다. 분석 중 직접 계산해 확인했다.
  - `adaptive`의 haiku probe는 이 조건이 "never binds"라고 적었다. 원 질문의 조건이 결과에 쓰이지 않는다는 것은 읽기가 틀렸다는 신호일 수 있다.
  - 그런데 probe 평가는 "Haiku’s suggested alternative-interpretation checks are unnecessary"라고 썼다.
- 3cef3a44 (두 조건 모두 basil 누락)
  - 원 질문의 기준은 "식물학적 과일이 채소 목록에 들어가지 않게 하라" 하나다. 생 basil은 잎이므로 이 기준에서 채소다.
  - orchestrator가 첫 지시에 원 질문에 없는 조건을 넣었다.
    - `direct`: "Also exclude items that are herbs rather than vegetables."
    - `adaptive`: "Distinguish herbs from vegetables as appropriate."
  - worker는 지시대로 basil을 뺐다.
  - evaluator는 두 조건 모두 이 조건을 원 질문 밖의 조건으로 지적하지 않았다. `adaptive` 최종 state는 오히려 "execution instruction에 따라 허브를 별도 범주로 둔다"를 근거로 남겼다.
  - sanity의 65afbc8a에서는 같은 유형(orchestrator가 넣은 "파란 칸을 지나가지도 말라")을 probe 평가가 잡았다. 이번에는 잡지 못했다.
- 0bb3b44a `direct`
  - worker가 자리값을 무시하고 세 부호를 모두 더해 890을 냈다.
  - evaluator는 "관례적 덧셈 판독"을 `assumption supported`로 기록했다.
- ec09fa32 `direct`
  - worker는 ball 100과 ball 3을 모두 계산했다.
  - evaluator는 ball 3 쪽 해석을 `assumption rejected`로 처리하고 100을 "natural finite-supply reading"으로 확정했다.
  - 100의 승리 확률은 1이었다. 퀴즈의 답으로는 퇴화한 값인데, 이를 해석을 다시 볼 신호로 쓰지 않았다.
  - 같은 문제에서 `adaptive` evaluator는 반대로 조건부 답을 요구했다(B). 해석을 판단하는 방향이 run마다 달랐다.

**5. D. "답이 존재하지 않음"으로 결론**

- 65afbc8a (두 조건)
  - 둘 다 첫 turn(A1→A3) 뒤 합법적인 이동이 없다고 결론지었다.
  - `adaptive`는 "backward"의 해석 세 가지와 한 칸씩 두 번 움직이는 해석까지 비교했지만 결론은 같았다.
  - 원 질문은 11번째 turn의 칸이 있다고 전제한다. 이 모순을 판독이나 해석을 다시 볼 이유로 쓰지 않았다.
  - 이동 규칙을 잘못 읽었는지 지도 판독이 틀렸는지는 확인하지 않았다.
- cca530fc `adaptive`
  - haiku가 d3의 비숍을 나이트로 잘못 읽었다.
  - 판독 충돌을 해소하는 데 probe 3회와 실행 2회를 썼다.
  - 세 번째 probe 라운드의 haiku 요청이 run 비용 한도 검사에 걸려 `budget_exceeded`로 끝났다. 수 분석은 하지 못했다.

**6. E. 이미지 판독·범위 (9318445f)**

- 정답은 본문의 `/` 분수 10개와 예제 답 7개다.
- 두 조건 모두 evaluator가 그림 label까지 넣으라고 범위를 넓혔고, 케이크 그림의 `1/4` 세 개가 들어갔다.
  - `direct`: "include every slash-form fraction in the image"
  - `adaptive`: "check diagram labels"
- `direct`는 가로선으로 쓴 예제 입력 7개도 넣었다.
- `adaptive`는 예제 입력은 뺐지만 본문 분수 일부를 중복해 넣었다.

**Takeaway:** 두 조건의 손실은 방향이 반대다.
- `direct`는 무엇이든 확정하므로 틀린 확정(A, C)으로 진다.
- `adaptive`는 정답 후보를 갖고도 확정하지 않아서 진다(B).
- 두 조건이 같이 틀린 문제(A, C의 e142056d·3cef3a44, D의 65afbc8a, E)에는 probe가 영향을 주지 못했다.

### **결론**

21개 오답 run의 대부분은 evaluator의 `changes`나 state 판단이 최종 답을 정했다.
- **B:** evaluator가 지금 도구로는 채울 수 없는 출처나 증명을 요구했다.
- **C:** evaluator가 틀린 해석을 `supported`로 받거나, 맞는 해석을 `rejected`로 처리했다.
- **E:** evaluator가 원 질문보다 넓게 범위를 지시했다.

여러 유형에 걸친 공통점이 하나 있다. 시스템이 "원 질문에는 답이 하나 있다"는 전제를 쓰지 않는다.
- "답이 없다"(65afbc8a, cca530fc `direct`), "해석을 정할 수 없다"(ec09fa32, cffe0e32 `adaptive`)는 결론이 그대로 최종 답이 됐다.
- 결과에 쓰이지 않는 조건(e142056d)이나 확률 1 같은 퇴화한 답(ec09fa32 `direct`)도 읽기를 다시 볼 이유로 쓰이지 않았다.

orchestrator가 지시문에 원 질문에 없는 조건을 넣는 경로(3cef3a44)도 남아 있다. probe 평가가 이를 잡는 경우도 있고 놓치는 경우도 있다.

다음에 확인할 것(사용자 결정 필요):

- 답 정책: 근거로 해석을 정할 수 없을 때 가장 그럴듯한 해석으로 값 하나를 고를지. B 유형을 직접 겨냥한다.
- 위 전제를 evaluator 판단에 쓸지. 해석을 다시 보는 신호로 쓰면 C·D에도 닿지만, 바꾸는 범위가 더 크다.
- 외부 지식이 필요한 3문제를 non-web 비교에 계속 포함할지. 지금은 두 조건 모두 맞힐 수 없고 `adaptive` 비용만 늘린다.

자료
- 실행 묶음: `outputs/experiments/2026-10-15_gaia-nonweb-conversation-comparison-rerun/`
- 보정 채점: `analysis/adjudicated_scores.csv`
- 각 run: `runs/<task_id>/<run>/run.json`, `artifacts/`, `events.jsonl`
