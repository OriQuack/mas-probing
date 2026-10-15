### **동기**

[2026-10-13 비교](2026-10-13-gaia-nonweb-direct-vs-adaptive.ko.md)에서 `adaptive`는 보정 채점으로 `direct`와 같았다(27 vs 27). 그런데 공식 채점은 16 vs 24였다. 차이는 답에 붙은 단서에서 나왔다.
사용자 진단은 다음과 같다. probe가 worker에게 assumptions·risks를 억지로 묻는다. 그 답이 evaluator의 미검증 state와 refiner의 단서 요구를 거쳐 `answer`까지 간다.
그래서 C41(v21/r23/e7)로 다음을 한 번에 바꿨다.

- probe는 이해·plan만 묻는다.
- 가정·오독·실패 위험은 evaluator와 orchestrator가 판단한다.
- 교정은 refiner의 rewrite 대신 worker 대화의 다음 메시지로 전한다.
- worker는 두 조건 모두 run 동안 대화 하나와 workspace 하나를 유지한다.

이 문서는 그 구성으로 같은 36문제를 다시 돌린 결과다. 기능별 기여는 나누지 않았다.

### **설정**

- 문제·pool·한도·runner는 2026-10-12 비교와 같다.
  - GAIA validation non-web 36문제
  - worker `gen_luna`, `gen_haiku`, 도구 `read_file`·`view_image`·`run_python`
  - run당 $0.20, execute 12회
  - 문제마다 두 조건을 연속 실행하고 짝수 문제는 `direct`를 먼저 돌린다.
- 실행 묶음: `outputs/experiments/2026-10-15_gaia-nonweb-conversation-comparison-rerun`, 72 run.
- 사전 sanity: `2026-10-15_gaia-nonweb-conversation-sanity`. 3문제 × 2조건이다(65afbc8a, cffe0e32, 7bd855d8).
  - orchestrator가 probe 초안에 "예상되는 모호함을 설명하라"를 직접 넣는 것을 보고 v20→v21로 한 문장을 더했다.
  - 이 3문제는 본 실행 36문제에 포함돼 있다.
- 중단된 첫 배치: `2026-10-15_gaia-nonweb-conversation-comparison`.
  - 35 run 뒤 cf106601 `direct`가 `error_infra`로 끝났다.
  - 원인은 haiku 요청이 116,816 입력 토큰에 도달한 것이다. 이 크기에서는 입출력 단가가 5배였고, 비용이 예약 상한을 넘었다.
  - runner 안전 규칙이 남은 run을 건너뛰었다.
  - 장문 단가를 예약에 반영한 뒤(decisions C41 보완) 72 run 전체를 새로 돌렸다. 중단 배치는 합산하지 않는다.
- 채점
  - 공식 채점: GAIA scorer.
  - 보정 채점: 2026-10-13 보고서와 같은 규칙이다.
    - 정답 값을 답으로 내세우면 덧붙은 설명은 무시한다.
    - `’`는 `'`로 본다.
    - 후보를 고르지 않은 답과 답 없음은 오답이다.
  - 판정 파일: `analysis/adjudicated_scores.csv`.
- 비교 대상: v19/r22/e6의 두 반복(`2026-10-12_gaia-nonweb-comparison`, `-rep1`). 보정 채점은 rep1에만 있다.

### **관측**

**1. 공식 점수 차이는 거의 사라졌고, 보정 점수는 이전과 비슷하다**

| 실행 | 조건 | 공식 | 보정 | 비용 | probe | execute |
| --- | --- | --- | --- | --- | --- | --- |
| v21 (이번) | `direct` | 23/36 | 26/36 | $0.346 | 0 | 51 |
| v21 (이번) | `adaptive` | 22/36 | 25/36 | $0.594 | 47 | 36 |
| v19 r0 | `direct` | 22/36 | – | $0.334 | 0 | 47 |
| v19 r0 | `adaptive` | 18/36 | – | $0.664 | 45 | 33 |
| v19 rep1 | `direct` | 24/36 | 27/36 | $0.264 | 0 | 44 |
| v19 rep1 | `adaptive` | 16/36 | 27/36 | $0.684 | 39 | 34 |

- 이번 보정 채점의 문제별 짝 비교: 둘 다 정답 25, 둘 다 오답 10, `direct`만 정답 1(cffe0e32). `adaptive`만 정답인 문제는 없다.
- `adaptive`의 단서 붙은 정답은 3개다(42576abe, 366e2f2b, 67e8878b). rep1은 11개였다.
- `adaptive` 비용은 `direct`의 1.7배다(rep1은 2.6배). probe와 probe 평가가 $0.245로 `adaptive` 비용의 41%다.
- 반복이 한 번뿐이라 보정 점수 25–27의 차이는 잡음 범위로 본다.

**Takeaway:** refiner를 없애고 probe를 이해·plan으로 줄이자 답에 단서를 붙이는 경로가 크게 줄었다. 공식 점수가 16–18에서 22로 올랐다. 하지만 맞힌 문제 수(보정)는 늘지 않았다.

**2. 대화 연결은 설계대로 동작했다**

- `adaptive` execute 36회가 모두 이전 대화를 이어받았다. 그중 probe 직후 execute는 probe했던 worker의 대화를 이었다.
- 8 run은 probe만으로 끝났다.
- sanity의 65afbc8a에서는 orchestrator 초안이 원 질문에 없는 "파란 칸을 지나가지도 말라"를 넣었다.
  - evaluator가 이를 원 질문에 없는 추가 조건으로 지적했다.
  - 다음 메시지가 "probe의 추가 금지 조건을 적용하지 말라"고 교정했다.
  - controller가 plan을 보고 오독을 바로잡는 경로가 실제로 쓰였다.
- haiku 대화 하나가 116k 토큰까지 커졌다(장문 단가 구간). 대화 유지가 비용 구조에 새 변수를 만든다.

**3. 답을 정하지 않는 쪽으로 가는 경로는 여전히 evaluator에서 나온다**

- `adaptive`가 답을 정하지 않은 문제: 305ac316 `Not established`, 5a0c1adf `Unverified`, 0bb3b44a `Not established (536 only conditionally)`, cffe0e32 `Fred or Micah`, ec09fa32 `No unique answer`.
  - 같은 문제에서 `direct`는 값을 하나 골랐다(Michał, Petr, 890, Fred, 100).
  - 그중 정답은 cffe0e32 하나다.
- evaluator `changes`가 조건부 답·한계 공개·대안 병기를 요구한 평가의 비율은 조건과 버전에 걸쳐 비슷하다.

  | 실행 | `direct` | `adaptive` |
  | --- | --- | --- |
  | v21 | 13/51 | 18/82 |
  | v19 rep1 | 11/44 | 11/73 |

  probe 없이 실행 보고만 평가할 때도 같은 요구가 나온다.
- ec09fa32 `adaptive`
  - haiku probe는 ball 3을 후보로 계산했다.
  - evaluator가 "균등 발사 확률과 종료 규칙을 사실처럼 쓰지 말라", "한 숫자를 무조건적으로 내지 말라"고 썼다.
  - 실행 worker는 종료 규칙 세 가지를 비교한 표를 냈다.
  - orchestrator는 `No unique answer`로 끝냈다. v19 rep1의 `adaptive`는 `3 (under the stated baseline convention…)`로 보정 정답이었다.
- probe 초안에 가정·모호함·유일성·위험 질문을 넣은 비율
  - v21 문장 추가 뒤 47개 중 11개다(rep1 39개 중 23개).
  - 줄었지만 남아 있다. ec09fa32 초안도 "clarify any assumptions needed"를 포함했다.

**Takeaway:** worker에게 가정을 묻지 않아도 evaluator가 스스로 미정 조건을 찾아 조건부 답을 요구한다. `direct`에서도 같은 비율로 요구한다. 사용자 진단의 앞부분(worker가 억지 가정을 만든다)은 단서 감소로 확인된다. 뒷부분(evaluator 문제는 worker 입력 때문이다)은 이번 자료로는 일부만 맞다.

**4. 두 조건이 같이 틀리는 문제는 그대로다**

- 외부 사실 필요: 305ac316, 5a0c1adf, cf106601
- 같은 오답 추론: e142056d `12000`, 0bb3b44a
- 이미지 판독: 9318445f, cca530fc
- 해석 고정: 65afbc8a. orchestrator가 "한 turn은 한 방향 두 칸"으로 해석을 고정했다.
- 분류 기준: 3cef3a44. basil이 빠졌다.
- v19 rep1의 `adaptive`가 refiner로 해석을 넓혀 맞힌 65afbc8a는 이번에 맞히지 못했다.
- cca530fc(체스)는 두 번째 probe 뒤 haiku 요청 예약이 run 한도를 넘어 `adaptive`에서 `budget_exceeded`로 끝났다. 이전 두 반복에서도 `adaptive`가 예산 초과였다.

### **결론**

C41 구성은 `adaptive`의 단서 문제를 대부분 없앴다(공식 16–18 → 22, 단서 붙은 정답 11 → 3). 비용도 줄였다(`direct` 대비 2.6배 → 1.7배). 보정 채점의 정답 수는 `direct`와 같은 수준이다(26 vs 25). probe가 맞힌 문제를 늘린 증거는 아직 없다.

남은 손실 경로는 evaluator가 미정 조건을 찾아 조건부 답을 요구하고, orchestrator가 답을 정하지 않는 경로다. 이 요구는 probe가 없는 `direct` 평가에서도 같은 비율로 나온다.

다음에 확인할 것:

- evaluator와 orchestrator finish의 답 정책: 근거로 해석을 정할 수 없을 때 가장 그럴듯한 해석으로 값 하나를 고를지. 사용자 결정이 필요하다.
- orchestrator probe 초안에 남은 가정 질문(11/47).
- 대화 유지로 커지는 haiku 입력(장문 단가, 예산 한도).

자료
- 실행 묶음: `outputs/experiments/2026-10-15_gaia-nonweb-conversation-comparison-rerun/`
- 채점: `analysis/scores.csv`(공식), `analysis/adjudicated_scores.csv`(보정)
- 각 run: `runs/<task_id>/<run>/run.json`, `artifacts/`, `llm_calls.jsonl`
