### **동기**

실행 worker에게 일을 맡기기 전에 두 worker에게 같은 지시문을 probe하고, 그 보고를 평가해 지시문을 고치면 GAIA 문제를 더 잘 푸는가?

1. probe를 거치는 `adaptive`가 바로 실행하는 `direct`보다 더 많이 맞히는가?
2. 비용은 얼마나 늘고, 어느 단계에서 늘어나는가?
3. 두 조건의 결과가 갈린 문제에서 probe·evaluator·refiner는 각각 무엇을 바꿨는가?

### **설정**

**문제**

- GAIA validation 36문제. `exploration_v1` split과 기존 audio/video scope가 겹치는 문제에서, metadata의 Tools에 web·search·Wikipedia·Maps·YouTube가 하나라도 있는 문제와 Tools가 비어 있는 문제를 뺐다.
- Level 1 23, Level 2 12, Level 3 1. 첨부 있음 19(xlsx 8, png 5, pdf 2, txt·pptx·docx·py 각 1), 첨부 없음 17.

**실행 묶음**

- `outputs/experiments/2026-10-12_gaia-nonweb-comparison-rep1`: 36문제 × 2조건 = 72 run. 이 문서는 이 72 run만 다룬다.
- 같은 36문제의 첫 실행(`2026-10-12_gaia-nonweb-comparison`)과 설정이 같다. 문제 순서도 같고, 문제마다 두 조건의 실행 순서만 뒤집었다.

**두 조건의 공통 구성**

- 역할과 모델
    - orchestrator·evaluator·refiner: `luna-high`(gpt-6-luna, reasoning high). 역할마다 따로 호출한다.
    - worker 2명: `gen_luna`(luna-high), `gen_haiku`(haiku-high, claude-haiku-5.5). system prompt와 도구가 같다.
    - worker 도구: `read_file`, `view_image`, `run_python`. 웹 도구는 없다.
- 한도: run당 $0.20, LLM 호출 400회, execute 12회, 3시간. execute 한 번에 도구 20회.
- prompt `v19`/`r22`/`e6`, tools `v7`.
- state: evaluator만 고쳐 쓰는 항목 목록. 항목마다 종류(observation·assumption·result·progress)와 상태(supported·unverified·rejected, 진행은 complete·incomplete·blocked)가 있다.
- 최종 답: orchestrator가 `finish`의 `answer`에 쓰고 근거는 `rationale`에 쓴다. 이때 GAIA 답 형식 규칙(숫자 하나, 가능한 적은 단어, 쉼표 목록)을 함께 받는다.

**`direct` (`direct_execution`)**

고를 수 있는 행동: execute, finish, read_memory.

1. orchestrator가 원 질문·state·보고 목록을 보고 지시문을 쓰고, worker 1명과 넘길 이전 보고를 고른다.
2. worker가 독립 대화에서 도구를 써서 과제를 풀고 Result / Evidence / Interpretation / Unfinished 형식으로 보고한다.
3. evaluator가 보고를 평가하고 state 전체를 다시 쓴다.
4. orchestrator가 다시 execute하거나 finish한다.

execute 없이 바로 finish할 수도 있다(이번에 4 run).

**`adaptive` (`adaptive_probe`)**

고를 수 있는 행동: probe, execute, finish, read_memory. 첫 행동은 probe로 하라고 prompt가 지시한다. Runtime이 강제하지는 않는다.

1. orchestrator가 지시문 초안(draft)과 context를 쓰고 probe를 고른다.
2. probe: 두 worker가 같은 draft와 context를 각자 받는다.
    - 과제 전체를 풀지 말고 이해·계획·가정·위험을 보고하라는 지시를 받는다.
    - 가정 확인에 도구를 최대 3회 쓸 수 있다. 확인 중 답이 나오면 근거와 함께 보고한다.
    - 각자 별도 workspace를 쓴다.
3. evaluator가 두 probe 보고를 평가하고 state를 다시 쓴다.
4. refiner가 원 질문·draft·state·평가를 보고 지시문을 고치거나 그대로 둔다. 사실 판단과 state 갱신은 하지 않는다.
5. orchestrator가 다시 probe, execute, finish 중 하나를 고른다.
    - execute: 저장된 지시문 ID(고친 지시문 또는 draft), worker 1명, context를 고른다. Harness는 저장된 지시문을 그대로 전달한다. probe 대화와 파일은 넘어가지 않고, orchestrator가 고른 probe 보고만 context로 간다.
    - finish: probe 보고만으로 근거가 충분하면 execute 없이 끝낸다.
6. execute 뒤 흐름은 `direct`의 2–4와 같다.

**채점**

- 공식 채점: GAIA scorer. 공백·구두점·대소문자를 정규화한 뒤 정답과 일치해야 한다.
- 보정 채점(이 문서의 주 지표). pilot이므로 답 형식보다 내용을 본다.
    - 정답 값 하나를 답으로 내세우면 뒤에 붙은 설명·가정·추가 값은 무시하고 정답으로 본다. 이 문서는 이런 덧붙임을 **단서**라 부른다. 예: `F478A7 (assuming two one-cell steps per turn, with bends allowed)`, `Hotels (3.8/5)`.
    - 곡선 따옴표 `’`는 `'`로 본다. 공식 scorer는 `’`를 지우지 않아서 `Shelley’s Place`를 오답으로 채점한다.
    - 후보를 둘 이상 나열하고 고르지 않은 답(`Not uniquely determinable: Micah or Fred`)과 답을 내지 않은 run(`Unable to verify`, 예산 초과 종료)은 오답이다.
    - run별 판정: `outputs/experiments/2026-10-12_gaia-nonweb-comparison-rep1/analysis/adjudicated_scores.csv`.
- 비용: run마다 `llm_calls.jsonl`의 호출별 비용을 더했다. 도구 비용은 없다.

### **관측**

**1. 보정 채점에서 두 조건의 정확도는 같고, `adaptive` 비용은 2.6배다**

| 조건 | 보정 정답 | 공식 정답 | 비용 | run당 비용 중앙값 | execute | probe | run 시간 합 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `direct` | 27/36 | 24/36 | $0.264 | $0.0033 | 44 | 0 | 63분 |
| `adaptive` | 27/36 | 16/36 | $0.684 | $0.0109 | 34 | 39 | 122분 |

- 문제별 짝 비교(보정 채점): 둘 다 정답 26, 둘 다 오답 8, `adaptive`만 정답 1(65afbc8a), `direct`만 정답 1(cffe0e32).
- run 시간 합은 run별 wall time을 더한 값이다. run을 병렬로 돌렸으므로 실제 경과 시간과는 다르다.

**Takeaway:** 이번 36문제에서 probe와 refiner는 맞힌 문제 수를 바꾸지 않았고 비용만 늘렸다.

**2. 공식 채점의 8문제 차이는 `adaptive` 답에 붙은 단서에서 나온다**

- 보정 정답 27개 중 단서가 붙은 답은 `adaptive` 11개, `direct` 2개(076c8171, cffe0e32)다. `direct`는 곡선 따옴표로 떨어진 1개(366e2f2b)가 더 있다.
- 공식 채점에서 `direct`만 맞힌 8문제는 모두 `adaptive`가 같은 값에 단서를 붙인 경우다. 공식 채점에서 `adaptive`만 맞힌 문제는 없다.

| 문제 | `adaptive` 답 | `direct` 답 |
| --- | --- | --- |
| 42576abe | `Maktay Mato Apple — present “is pleasing to”; Mato (“I”) is the object …` | `Maktay Mato Apple` |
| 50ad0280 | `THESEAGULLGLIDEDPEACEFULLYTOMYCHAIR — The seagull glided peacefully to my chair.` | `The seagull glided peacefully to my chair.` |
| 5cfb274c | `No. The 49 green plots split 25–24 by checkerboard parity; …` | `No` |
| 67e8878b | `Hotels (3.8/5)` | `Hotels` |
| 7bd855d8 | `89706.00 (food-column aggregate; workbook does not establish USD sales revenue)` | `89706.00` |
| 6359a0b1 | `39 (assuming right-angle corners; 20 + 4 + 6 + 5 + 4). Side lengths alone do not determine a unique area.` | `39` |
| 50ec8903 | `green, white (conditionally)` | `green, white` |
| ec09fa32 | `3 (under the stated baseline convention; the rules as written do not determine a unique answer)` | `3` |

**Takeaway:** 공식 점수 차이(24 vs 16)는 추론 결과의 차이가 아니라 `answer`에 무엇을 쓰느냐의 차이다.

**3. 같은 미검증 가정이 있어도 `direct`는 값만 내고 `adaptive`는 조건부 답을 낸다**

- 5문제에서 두 조건의 최종 state에 같은 미검증 가정이 있었다.

| 문제 | 두 조건 state의 미검증 가정 | `direct` 답 | `adaptive` 답 |
| --- | --- | --- | --- |
| 7bd855d8 | 값이 USD 매출이라는 표시가 workbook에 없다 | `89706.00` | 단서 붙음 |
| 6359a0b1 | 그림의 직각 여부와 치수 표시 해석 | `39` | 단서 붙음 |
| 50ec8903 | 큐브의 색 배치와 orange 단서 해석 | `green, white` | `green, white (conditionally)` |
| ec09fa32 | 공이 두 개보다 적게 남았을 때 채우는 규칙 | `3` | 단서 붙음 |
| cffe0e32 | 배정표 머리글 `Giftee \| Recipient`의 방향 | `Likely Fred, if …` | `Not uniquely determinable: Micah or Fred` |

- `direct`는 4문제에서 가정을 `rationale`에만 쓰고 `answer`에는 값만 넣었다.
- `adaptive`에서는 refiner가 고친 지시문이 답 자체에 조건을 달라고 요구했다.
    - 7bd855d8: "If the workbook does not establish the values as USD revenue, clearly disclose that limitation and avoid presenting the numeric aggregate as a verified USD sales total."
    - 50ec8903: "Give the answer conditionally under the stated assumptions"
    - 6359a0b1: "State that this result depends on treating the outline as horizontal and vertical segments with right-angle corners …"
    - ec09fa32: "if the answer depends on the unspecified boundary behavior, make that dependence clear."
    - cffe0e32: "do not claim the document uniquely establishes who did not give a gift."
- `direct`의 지시문도 "state … assumptions", "flag any ambiguity"를 요구했다. 다만 worker 보고에 쓰라는 요구였고 답의 형식을 정하지는 않았다.
- finish 판단 입력에는 두 조건 모두 실행 지시문 전문이 들어간다. 차이는 지시문의 내용에 있다.
- evaluator도 답 형식을 지시한다.
    - 50ad0280 `adaptive`의 progress 항목: "State the concatenated stream and the corrected sentence in the final response".
    - 6359a0b1 `adaptive`의 progress 항목: "For the user-facing answer, state the conditional nature of 39".
    - `direct`의 ec09fa32에서도 evaluator가 "A final answer should state ball 3 … and disclose …"라고 썼지만, orchestrator는 `3`만 냈다.

**Takeaway:** refiner는 evaluator가 남긴 미검증 가정을 "답에 조건을 달라"는 지시로 바꾼다. 그 지시가 worker 보고를 거쳐 `answer`까지 간다. 5문제 모두 `direct`가 고른 값이 정답이었으므로, 단서는 답을 바꾸지 않고 채점만 떨어뜨렸다.

**4. 한 조건만 맞힌 2문제: probe 뒤 refiner가 해석을 넓힌 경우와 답을 막은 경우**

65afbc8a (`adaptive`만 정답)

- 질문: Excel 지도에서 START부터 "한 turn에 두 칸" 움직이되 뒤로 가지 않고 파란 칸을 피할 때, 11번째 turn에 도착한 칸의 색.
- `direct`
    - orchestrator 지시문이 "treating each turn as an exact move of two cells in one cardinal direction"으로 해석을 고정했다.
    - worker는 두 번째 turn에 갈 곳이 없다고 보고했다. evaluator는 parity 논증을 근거로 "backward를 어떻게 해석해도 결론이 같다"고 판단했다.
    - 답: `No valid route; no turn-11 cell.`
- `adaptive`
    - refiner가 "Compare the plausible interpretations of 'may not move backward' where they affect which turn-11 landings are legally reachable"를 넣었다.
    - 실행 worker(gen_luna)는 해석을 비교하다가 "한 칸씩 두 번 움직이고 그 사이에 방향을 바꿀 수 있다"는 해석을 찾았다. 파란 칸이 아닌 64칸이 START와 END를 잇는 외길이라는 것도 확인했다. 이 해석에서 11번째 turn은 E3, 색은 `F478A7`이다.
    - 답: `F478A7 (assuming two one-cell steps per turn, with bends allowed)`.
- refiner가 넓힌 것은 "backward"의 해석이다. "두 칸"의 해석은 worker가 스스로 넓혔다.

cffe0e32 (`direct`만 정답)

- 질문: Secret Santa에서 선물하지 않은 사람. 문서의 배정표 머리글 `Giftee | Recipient`는 어느 열이 주는 사람인지 정하지 않는다.
- `direct`: evaluator가 "첫 열이 주는 사람"을 미검증 가정으로 두고 "the answer should state the likely Fred interpretation conditionally"라고 썼다. 답: `Likely Fred, if the first column identifies the giver; …`.
- `adaptive`: refiner가 두 방향 각각의 답(Micah, Fred)을 지시문에 쓰고 "do not claim the document uniquely establishes who did not give a gift"라고 지시했다. 답: `Not uniquely determinable: Micah or Fred`.

**Takeaway:** probe 뒤 refiner가 해석의 범위를 정한다. 범위를 넓히면 원래 지시문이 배제한 정답에 닿을 수 있다(65afbc8a). 답을 하나로 고르지 못하게 하면 맞힐 수 있던 문제를 놓친다(cffe0e32).

**5. probe나 실행에서 정답 후보가 나와도 evaluator가 tentative로 남기면 최종 답에 들어가지 않는다**

3cef3a44 (두 조건 모두 오답)

- 질문: 식물학 교수가 볼 장보기 목록에서 botanical fruit를 빼고 vegetable만 고르기. 정답 `broccoli, celery, fresh basil, lettuce, sweet potatoes`.
- `adaptive`
    - haiku probe가 정답과 같은 목록을 제안했다.
    - evaluator는 "basil’s status as an herb rather than a vegetable remains a consequential inclusion question"이라며 이 목록을 tentative로 남겼다.
    - refiner는 "paying particular attention to whether fresh basil belongs in the vegetables category rather than the herb category"를 넣었고, 실행 worker는 basil을 뺐다.
- `direct`
    - orchestrator 지시문이 "include non-fruit edible plant parts"로 기준을 정했다.
    - worker는 이 기준을 글자 그대로 적용해 peanuts와 whole bean coffee를 씨앗으로 넣었다. 답: `basil, broccoli, celery, lettuce, peanuts, sweet potatoes, whole bean coffee`.
- 두 조건 모두 지시문이 분류 기준을 어떻게 썼느냐에 따라 답이 정해졌다.

0bb3b44a (두 조건 모두 오답, 정답 536)

- 쐐기문자 숫자 `𒐜  𒐐𒐚`를 10진수로 바꾸는 문제. 두 조건 모두 `890`을 냈다.
- `adaptive`의 두 번째 execute에서 haiku가 "공백이 자릿수 구분이면 8 | 56 → 536"을 대안으로 적었다. 하지만 스스로 채택하지 않았고, evaluator는 이를 "not a supported competing value"로 처리했다.
- `direct`의 보고에는 536이 나오지 않았다.

**Takeaway:** probe와 실행 모두 정답 후보를 만들 수 있다. 그러나 출처 근거가 없는 후보는 evaluator가 tentative로 남기거나 채택하지 않는다. 3cef3a44에서는 refiner가 그 의심을 지시문에 옮겼고, 실행 단계에서 정답 항목이 빠졌다.

**6. 쉬운 문제에서 probe는 haiku의 풀이가 되고, 비용만 늘린다**

- `adaptive` 36 run 중 12 run이 execute 없이 끝났다. 12 run 모두 보정 채점 정답이고, 그중 3 run(42576abe, 50ad0280, 67e8878b)은 단서 때문에 공식 채점 오답이다.
- 같은 12문제에서 `direct`도 모두 정답이었다. 비용은 `adaptive` $0.056, `direct` $0.021로 2.7배다.
- 답이 어디서 나왔는가 (probe가 있었던 11 run)
    - 9 run: luna probe는 도구 없이 계획만 냈고, haiku probe가 도구 1–2회로 답을 계산해 보고했다. evaluator가 그 계산을 근거로 결과를 supported로 올렸고 orchestrator가 바로 finish했다. 예: 6f37996b에서 haiku가 Python으로 10쌍을 모두 비교해 `b, e`를 얻었다.
    - 42576abe: 두 probe 모두 도구 없이 같은 번역을 제안했다.
    - 67e8878b: evaluator가 저장된 표 원문으로 평균을 직접 검산했다.
    - 나머지 1 run(4b650a35)은 probe 없이 첫 행동에서 바로 finish했다.
- probe 보고 78개 중 도구를 쓴 보고는 haiku 36/39, luna 10/39다. probe prompt는 "Do not undertake the full assignment to obtain its answer"라고 지시하지만, haiku는 대부분 답까지 계산했다.
- refiner: probe 39회 중 지시문 수정 37회, refiner 실패 2회. 수정 37회 중 10회는 draft와 글자까지 같았다.

**Takeaway:** 이번 `adaptive`의 probe는 두 worker의 접근을 비교하는 단계라기보다 "luna의 계획 + haiku의 풀이"로 작동했다. 쉬운 문제에서는 `direct`의 execute 한 번과 결과가 같고 비용이 더 든다.

**7. 비용은 probe 단계, 실행 단계, 두 문제의 반복에서 늘었다**

| 단계 | `direct` | `adaptive` |
| --- | --- | --- |
| orchestrator | $0.044 | $0.080 |
| probe | – | $0.131 (haiku $0.095, luna $0.035) |
| probe 평가 | – | $0.075 |
| refiner | – | $0.028 |
| execute | $0.133 (haiku $0.039, luna $0.095) | $0.266 (haiku $0.148, luna $0.118) |
| execute 평가 | $0.087 | $0.104 |
| 합계 | $0.264 | $0.684 |

- probe, probe 평가, refiner를 더하면 $0.234로 `adaptive` 비용의 34%다.
- `adaptive`는 execute 횟수가 더 적은데(34 vs 44) execute 비용은 2배다.
    - 쉬운 문제가 probe에서 끝나서 execute가 어려운 문제에 몰렸다.
    - haiku에게 맡긴 execute가 13/34로 `direct`의 7/44보다 많다.
- 고비용 2문제(cca530fc, cf106601)가 `adaptive` 비용의 38%($0.258)를 차지한다. `direct`는 같은 두 문제에 $0.078을 썼다. 두 문제를 빼면 두 조건의 비용 비는 2.3배다.
- cf106601 (1928 올림픽에서 선수가 가장 적은 나라, 정답 CUB)
    - `adaptive`가 probe 4회와 execute 4회에 $0.081을 썼다. worker에게 웹 도구가 없어서 같은 자료 접근 실패가 매번 되풀이됐다.
    - 3·4번째 probe를 고를 때 orchestrator의 rationale: "The adaptive-probe condition calls for a fresh probe", "A fresh probe is required under the adaptive-probe condition". prompt는 첫 행동만 probe로 하라고 한다("For adaptive_probe, start a fresh run with probe").
    - 두 조건 모두 `HAI`를 냈다.
- cca530fc (체스 그림에서 흑의 필승 수, 정답 Rd5)
    - `adaptive`는 probe 1회와 execute 4회 뒤 $0.177에서 run 예산 초과로 답 없이 끝났다.
    - `direct`는 execute 3회, $0.061로 `No guaranteed win established; 1...Qxc3 is only a material-winning candidate.`를 냈다.
    - 두 조건 모두 chess engine이 없어 worker가 직접 짠 탐색 코드로 분석했다.

**Takeaway:** 비용은 (1) 모든 문제에 probe를 한 번씩 돈 것, (2) 새 정보원이 없는데 probe와 execute를 되풀이한 것에서 늘었다. orchestrator가 "adaptive 조건이면 probe를 다시 해야 한다"고 prompt를 잘못 읽은 경우도 있었다.

**8. 두 조건 모두 틀린 8문제에서는 probe가 새 정보를 주지 못한다**

| 원인 | 문제 | 두 조건의 답 |
| --- | --- | --- |
| 외부 사실 필요(웹 도구 없음) | 305ac316: 폴란드판 Everybody Loves Raymond의 Ray 배우가 Magda M.에서 맡은 배역 | `direct` `Jacek`(기억에 의존), `adaptive` `Cannot verify` |
| | 5a0c1adf: Malko Competition 수상자 | 둘 다 답 없음 |
| | cf106601: 1928 올림픽 | 둘 다 `HAI` |
| 두 조건이 같은 오답 추론 | e142056d: 동전 게임의 최소 보장 상금(정답 16000) | 둘 다 `12000`. evaluator가 상한 논증을 supported로 받음 |
| | 0bb3b44a: 쐐기문자 숫자(정답 536) | 둘 다 `890` |
| 이미지 판독 | 9318445f: 그림 속 분수 목록 | 둘 다 정답에 없는 `1/4` 항목을 더 넣음 |
| | cca530fc: 체스 그림 | 둘 다 답 없음 |
| 분류 기준 | 3cef3a44: vegetable 목록 | 관측 5 |

**Takeaway:** probe worker는 실행 worker와 같은 두 모델, 같은 도구다. 두 모델이 같이 틀리거나 도구로 닿지 않는 사실이 필요한 문제는 probe로 고칠 수 없다. metadata상 web 도구가 없는 이번 집합에도 외부 사실이 필요한 문제가 3개 있다.

### **결론**

보정 채점에서 `adaptive`와 `direct`는 똑같이 27/36을 맞혔고, `adaptive`의 비용이 2.6배였다. 공식 점수 차이(16 vs 24)는 refiner와 evaluator가 미검증 가정을 답 형식에 대한 요구로 바꾸고, orchestrator가 그 단서를 `answer`에 쓴 결과다. probe 때문에 결과가 바뀐 문제는 2개였다. 하나는 refiner가 해석을 넓혀서 맞혔고(65afbc8a), 다른 하나는 답을 하나로 고르지 못하게 해서 놓쳤다(cffe0e32). probe 단계의 실제 계산은 대부분 haiku가 했고, 쉬운 문제에서는 `direct`와 같은 답을 더 비싸게 냈다.

다음에 확인할 것:

- refiner와 evaluator가 답 형식(조건부 답, 한계 공개)을 지시하지 않고, `answer`에는 값만 쓰도록 두 조건에 같이 고친 뒤 다시 비교한다.
- probe의 효과를 둘로 나눈다. 하나는 haiku가 probe에서 직접 푼 효과이고, 다른 하나는 refiner가 지시문의 해석을 바꾼 효과다. 예: `direct`에서 haiku 실행을 함께 돌리는 대조 조건.
- 새 정보원이 없을 때 재시도를 멈추는 기준을 넣고, "adaptive면 probe를 다시 한다"로 읽힌 prompt 문장을 고친다.

자료: 각 run의 `runs/<task_id>/<run>/run.json`, `artifacts/`, `llm_calls.jsonl`; 공식 채점 `analysis/scores.csv`; 보정 채점 `analysis/adjudicated_scores.csv`.
