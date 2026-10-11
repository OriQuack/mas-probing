> 과거 실험 보고서입니다. 해석·수치의 정정은 [최신 종합 보고서](2026-10-10-synthesis.ko.md)를 우선하세요.

# Refiner r8 → r9, prompts v6 → v7: 이전 문제, 수정, 결과 (2026-10-10)

이전 report(`2026-10-09-baseline-and-probe-comparison.ko.md`)의 §4, §9, §10을 하나로 다시 정리한 것임. 새로 돌린 run은 없음.

## 0. 한눈에
- **이전 문제 (refiner r8, prompts v6, stage 4)**
  - 정답 수는 A_none 33, c2 29, c3 28 (/47)이었음.
  - A는 맞혔는데 refiner가 instruction을 고쳐 쓴 뒤 틀린 run이 7개 있었음. 대부분 "판단 불가", "두 답 모두" 같은 비답변이었음.
  - refiner 덕분에 맞힌 run은 0개였음.
- **원인으로 본 경로** (trace에서 확인)
  1. rewrite 규칙이 instruction에 "증거가 없으면 판단 불가라고 보고하라"는 조항으로 복사됨.
  2. probe가 본 다른 해석이 "각 해석에 따른 답을 모두 내라"는 지시로 확대됨.
  3. 해석을 자료로 확인하기 전에 더 엄격하거나 좁은 쪽으로 확정함.
  4. 실행 날짜(2026-10-09)가 질문의 시간 기준으로 쓰임. 이건 refiner가 아니라 공통 prompt(harness)의 문제였음.
- **바꾼 것**
  - **refiner r9:** 규칙을 instruction에 복사하지 않게 함. 결과를 보류하는 조건을 넣지 않게 함. 원 task의 통상적 해석을 지키게 함. probe의 관찰과 결론을 구분하게 함.
  - **prompts v7:** 날짜 줄이 "실행 날짜일 뿐 질문의 시간 기준이 아니다"를 뜻하도록 바꿈.
- **고쳐진 것**
  - 같은 draft에서 refiner만 r9로 바꾸자, r8이 망쳤던 5개 run이 2 rep 모두 정답이었음(10/10).
  - 이 재실행의 refiner arm 28 run에서 비답변은 0개였음.
  - 날짜를 시간 기준으로 쓰는 일이 v7에서 사라졌음.
- **여전히 문제인 것**
  - 불확실성이 비답변으로 바뀌는 일이 다른 단계에서 남아 있음.
    - orchestrator가 확인을 다시 맡긴 뒤 "확실하지 않다"는 보고를 받으면, finish 판단이 정답, 비답변, 반대 해석으로 갈림. refiner가 없는 run에서도 일어남.
    - refiner가 해석을 확정하면서 증거 기준까지 엄격하게 바꿈.
    - 사전 확인이 퍼즐 단서를 문자 그대로 검증함.
  - **refiner가 A의 오답을 정답으로 바꾼 사례는 여전히 없음.**
  - 8개 task, 1–2 rep이라 정답 수 차이는 noise 범위임. 이 report의 주장은 trace에서 본 경로에 대한 것임.
- **비용**: 재실행 $4.92. 어젯밤부터 누적 약 $22.0 (상한 $50). Serper는 key 3에 2,380 credit 남음.
- **코드**: `dc893bd` (r9), `894c99d` (v7), `6d63c35` (E10 재실행 범위). 모두 local commit이고 push 안 함.

## 1. 배경: 무엇을 비교하나
- **구조**
  - orchestrator(luna-high)가 task를 받아 worker에게 subtask를 맡기고(delegation), 보고를 받아 최종 답을 냄.
  - refiner는 첫 delegation(d0) 직전에 끼어들어, orchestrator가 쓴 instruction(draft)을 검토하고 필요하면 고쳐 씀.
- **refiner의 단계**
  1. **probe:** worker에게 "이 subtask를 어떻게 하겠는지" 미리 묻고 답을 받음. 확인을 위한 tool 호출은 3회까지 허용함.
  2. **analysis:** probe의 답과 원 task를 비교해 issue를 찾고, issue마다 결정을 내림. 결정은 clarify / needs_verification / defer_to_execution / not_relevant 중 하나.
  3. **rewrite:** issue를 반영해 instruction을 다시 씀. 필요하면 `context_additions`로 관찰한 사실을 덧붙임.
  - issue가 없으면 draft가 그대로 나감. 이 경우 처리는 A와 같음.
- **arm**
  - **A_none:** refiner 없음.
  - **c2_probe_tools:** probe 1명(luna).
  - **c3_probe_multi:** probe 2명(luna, haiku). 응답은 익명 "respondent k"로 섞어서 보여 줌.
- **비교 방식**
  - fresh run이 d0 직전 상태를 checkpoint로 저장함.
  - 세 arm은 같은 checkpoint에서 restore해서 출발함. 그래서 세 arm의 draft가 같음(짝지은 비교).

## 2. 이전의 문제 (stage 4: prompts v6, refiner r8)
`stage4-serper-20261009T192620Z`, v6 checkpoint 47개 × 3 arm × 1 rep.

### 2.1 숫자
| arm | 정답 | 비답변 | rewrite된 run |
|---|---|---|---|
| A_none | **33/47** | 3 | – |
| c2_probe_tools | **29/47** | 4 | 11 |
| c3_probe_multi | **28/47** | 8 | 25 |

- **정답 수 차이만으로는 결론을 낼 수 없었음.** 짝지은 비교는 A vs c2가 6:2(p = 0.29), A vs c3가 8:3(p = 0.23)이었음.
- **refiner가 draft를 그대로 둔 run도 A와 결과가 다른 비율이 17%(10/58)였음.** 형식, 오타, 반올림 차이 등이고, 이게 run 간 noise임.
- **비답변 비율은 rewrite 여부에 따라 뚜렷하게 갈렸음**

| | 비답변 비율 |
|---|---|
| c3, rewrite됨 | **8/25** |
| c3, draft 그대로 | 0/22 |
| c2, rewrite됨 | 2/11 |
| c2, draft 그대로 | 2/36 |
| A | 3/47 |

### 2.2 A는 맞혔는데 r8 rewrite 뒤 틀린 run 7개
아래 "rewrite가 한 일"은 외부 검토를 받아 고친 규정임(이전 report §9).

| task | arm | A 답 | refiner arm 답 | rewrite가 한 일 |
|---|---|---|---|---|
| cffe0e32 (Secret Santa) | c3 | Fred ✓ | "Ambiguous: Fred if …; Micah if …" | probe가 말한 다른 해석을 채택하고 "각 읽기에 따른 결과를 내라"는 지시로 확대함 |
| 9b54f9d9 (음식 목록) | c3 | ✓ | "Not uniquely determinable" | 느슨한 대응 관계를 "같은 음식일 때만"이라는 엄격한 동일성으로 바꿈 |
| 676e5e31 (USDA 표준) | c2 | 86 ✓ | 100% | 자료로 확인하기 전에 후보 집합을 바꾸는 해석을 확정함(7개 → 6개) |
| 56137764 (OpenCV) | c2 | Li Peng ✓ | "No matching contributor" | draft가 "그 version의 기여자"를 "그 기능을 추가한 사람"으로 좁힌 것을 바로잡지 못함 |
| a7feb290 (arXiv) | c3 | 31 ✓ | "Unknown" | 2020년 1월 당시 기준 확인을 요구한 것 자체는 과하지 않음. archive 확인이 실패하자 이를 "도출 불가"로 바로 연결함 |
| 9e1fc53b (WoW) | c2 | ✓ | Warrior가 들어간 오답 | 실행 날짜로 "새로 나온 dungeon"을 정하게 함 |
| 9e1fc53b (WoW) | c3 | ✓ | "Cannot be determined" | 위와 같고, item version을 엄밀하게 따지게 함 |

### 2.3 공통 경로
1. **rewrite 규칙이 instruction 조항으로 복사됨**
   - r8 규칙: "Report that the result cannot be derived only when a specific missing or conflicting piece of evidence prevents …"
   - 비답변을 줄이려고 넣은 규칙인데, instruction에 거의 그대로 옮겨져 비답변을 허락하는 조항이 됨.
     - 56137764 c2: "If the evidence does not establish a match, explain the specific missing or conflicting evidence."
     - 9e1fc53b c3: "… or state that it cannot be derived only if specific evidence …"
   - rewrite 36개 중 17개에 이런 조건부 조항이 새로 들어갔음(regex 기준).
     - 조항이 들어간 17개 중 7개가 비답변으로 끝남.
     - 조항이 없는 19개 중에서는 3개.
2. **probe의 결론이 그대로 전달됨**
   - cffe0e32 c3에서 haiku probe가 "표 header가 Giftee / Recipient라 Fred 또는 Micah"라고 보고함.
   - rewrite는 "give the result under each possible reading"을 넣었음.
   - `context_additions`도 "두 읽기 모두 가능"이라는 결론을 worker에게 넘겼음.
3. **해석을 엄격하거나 좁은 쪽으로 확정함**
   - 9b54f9d9: "Treat two entries as a duplicate … only when they denote the same food"
   - 676e5e31: 수식어 처리 규칙을 자료 확인 전에 정해서 후보가 1개 줄었음.
4. **실행 날짜가 질문의 시간 기준이 됨 (harness)**
   - v6의 task 끝 날짜 줄은 "Run reference date: 2026-10-09 (today's date for this run …)"였음.
   - 이 줄을 refiner rewrite뿐 아니라 orchestrator의 draft도 시간 기준으로 썼음.
     - 4d51c4bf draft: "run reference date 2026-10-09 기준 최근 90일" filter
     - 9e1fc53b rewrite: run date로 "just released" 판단
     - 384d0dd8 rewrite: "records as of 2026-10-09"
- 이 경로들은 stage 1–2(r5, r7)에서 본 pattern과 같은 유형임. 하나는 엄격한 기준이 비답변으로 이어지는 것, 다른 하나는 orchestrator re-check가 hedge로 이어지는 것.

### 2.4 이전 해석에서 정정한 것
- 제가 처음 쓴 "전부 prompt 때문", "LLM 능력 문제는 아님", "방법과 GAIA가 근본적으로 맞지 않음"은 증거보다 강한 결론이었음. 아래처럼 정정함.
  - **prompt와 LLM:** 둘은 분리할 수 없음. 정확한 서술은 "실행 능력은 있었지만(A는 정답) 검토와 수정 단계의 판단이 나빴고, prompt가 그 경향을 강화했다"임.
  - **GAIA:** 이번 결과가 직접 보여 주는 것은 "현재 수정 정책이 GAIA에 필요한 통상적인 해석을 보존하지 못했다"까지임. 올바른 수정이 GAIA에서 이득이 작은지는 아직 확인되지 않았음.
  - **채점:** 채점상 실패와 근거상 부당한 판단은 다름.
    - 708b99c5 "Citation count" vs gold "Citations"는 의미가 같은데 채점이 인정하지 않은 것임.
    - 8131e2c0 "101.38"은 문제에서 요구하지 않은 반올림을 모델이 한 것임(A는 101.376으로 맞힘).
- **요약 문장**: 이 구현에서는 잠재적 모호함이 추가 제약과 비답변 조건으로 확대되는 실패가 반복됐다. GAIA의 평가 특성이 이를 불리하게 만들 수 있지만, 올바른 instruction 수정의 이득이 작은지는 아직 확인되지 않았다.

## 3. 바꾼 것
| 변경 | 겨냥한 경로 | 내용 |
|---|---|---|
| r9 rewrite 규칙 (`dc893bd`, R24) | 2.3의 1 | r8의 "cannot be derived only when …" 문장을 뺐음. "These rules are for writing the instruction and are not part of it. Do not add conditions under which the worker should withhold the result or report that it cannot be determined"를 추가함. 확인이 실패할 수 있으면 "가장 잘 뒷받침되는 답 + 확인하지 못한 것 명시"를 쓰게 함 |
| r9 rewrite 규칙 | 2.3의 2 | "State the one reading the worker should apply; do not ask for results under several readings." `context_additions`에는 관찰만 넣고 "모호하다" 같은 결론은 넣지 않음 |
| r9 analysis | 2.3의 2 | probe 답에서 관찰(파일이나 출처에 무엇이 있는지)과 결론(모호하다, 여러 답이 필요하다)을 구분함. 결론은 refiner가 직접 판단함 |
| r9 analysis | 2.3의 3, 56137764 | issue는 원 task의 표현과 목적이 뒷받침하는 해석으로 해결함. 대상, 범위, 조건을 원 task보다 좁히지 않음. draft가 좁혔으면 원 task의 표현으로 되돌림 |
| r9 defer_to_execution | 2.3의 1 | resolution에 확인 방법, 확인 결과를 답에 쓰는 방법, 확인이 실패했을 때의 처리(best available evidence로 진행)까지 쓰게 함 |
| prompts v7 (`894c99d`, F23) | 2.3의 4 | 날짜 줄을 "Run date: … (the day this run takes place). The task may have been written earlier: do not take the run date as the task's time reference, and do not filter data or choose sources by it; take the time frame from the task itself."로 바꿈. 날짜는 run마다 고정되고 checkpoint에 저장되는 기존 방식 그대로임 |

- **바꾸지 않은 것**
  - probe 질문의 구성과 probe tool 상한(3).
  - decision 종류와 probe 모델 구성.
  - orchestrator의 나머지 prompt(re-check와 finish 정책 포함).
  - worker prompt.

## 4. 재실행 방법
- **v7로 바꾸면 v6 checkpoint를 restore할 수 없음**(version 불일치는 거부함). 그래서 두 phase로 나눴음.
  - **Phase A — r9만의 효과**
    - 같은 v6 checkpoint(draft가 stage 4와 동일)에서 refiner만 r9로 바꿈.
    - 7 task × 3 arm × 2 rep = 42 run.
    - session: `rerunA-r9-v6ck-20261010T053207Z`
  - **Phase B — 날짜 수정까지 합친 효과**
    - v7로 fresh run 8개를 돌려 새 checkpoint를 만들고, 그것을 3 arm × 1 rep으로 restore함(24 run).
    - a7feb290 c2/c3는 Serper로 다시 돌림(2 run, §7.6).
    - session: `rerunB-v7-r9-20261010T062005Z`
- **task 선정**
  - 2.2의 task 6개, 그리고 refiner가 맞게 고친 4d51c4bf. 384d0dd8은 phase B에만 넣음.
  - 16d825ff와 3da89939는 뺐음. 결과가 검색 운에 달려 있고 credit을 많이 씀.

## 5. 결과
### 5.1 Phase A: 같은 draft, r8 → r9 (2 rep)
| task | stage 4 r8 (A, c2, c3) | r9 (A, c2, c3) |
|---|---|---|
| 56137764 | ✓, **✗**, ✓ | ✓✓, **✓✓**, ✓✓ |
| 676e5e31 | ✓, **✗**, ✓ | ✓✓, **✓✓**, ✗✗ |
| 9b54f9d9 | ✓, ✓, **✗** | ✓✓, ✓✓, **✓✓** |
| 9e1fc53b | ✓, **✗**, **✗** | ✓✓, **✓✓**, **✓✓** |
| cffe0e32 | ✓, ✓, **✗** | ✓✓, ✓✓, **✗✓** |
| a7feb290 | ✓, ✗, **✗** | ✗✗, ✗✗, ✗✗ |
| 4d51c4bf | ✓, ✓, ✓ | ✓✓, ✓✓, ✓✓ |
| 합계 | – | A 12/14, c2 12/14, c3 9/14 |

- 굵게 표시한 칸은 2.2의 7개 run임.
- **r8 rewrite가 망쳤던 5개**(56137764 c2, 676e5e31 c2, 9b54f9d9 c3, 9e1fc53b c2, 9e1fc53b c3)는 r9에서 10/10 정답이었음.
  - 10개 중 6개는 r9도 instruction을 고쳐 썼는데 정답이었음. 4개는 r9가 issue를 찾지 않아 draft가 그대로 나갔음.
- **refiner arm 28 run 중 비답변 0개.** hedge("Fred or Micah")가 1개 있었음.
- **decision 분포가 바뀜:** r8 c3는 defer 19 / clarify 17이었고, r9 phase A 전체는 clarify 15 / defer 5 / needs_verification 1임.
- **a7feb290**은 A도 0/2(30, 26)였음. 세는 과정 자체가 불안정해서 판단에서 뺌.

### 5.2 Phase B: v7 fresh + r9 restore (1 rep)
| task | fresh v7 (refiner 없음) | A | c2 | c3 |
|---|---|---|---|---|
| 4d51c4bf | ✓ | ✓ | ✓ | ✓ |
| 56137764 | ✓ | ✓ | ✓ | ✓ |
| 676e5e31 | ✗ 71 | ✓ | ✓ | ✓ |
| 9b54f9d9 | ✓ | ✓ | ✓ | ✓ |
| 9e1fc53b | ✓ | ✓ | ✗ Druid 포함 | ✓ |
| cffe0e32 | ✓ | ✓ | ✗ "Cannot be determined" | ✗ "Micah" |
| a7feb290 | ✗ "Unable to determine" | ✓ 31 | ✗ "Unknown" (재실행도 ✗) | ✗ "Cannot be determined" (재실행도 ✗) |
| 384d0dd8 | ✗ | ✗ | ✗ | ✗ |
| 합계 | 5/8 | 7/8 | 4/8 | 5/8 |

### 5.3 같은 draft에서 r8과 r9의 문구 비교
| task, arm | r8 rewrite (stage 4) | r9 rewrite (phase A) | 결과 r8 → r9 |
|---|---|---|---|
| 56137764 c2 | "identify the contributor credited for that addition … If the evidence does not establish a match, explain the specific missing or conflicting evidence." | "Examine the contributors credited to that version … do not limit candidates to the feature's implementer." (r0) | ✗ → ✓✓ |
| 9b54f9d9 c3 | "only when they denote the same food … If the evidence does not support identifying exactly one unmatched food, explain the specific ambiguity" | r1: "only when they name the same food under different names, including supported synonyms or spelling/regional variants". 보류 조항 없음. r0은 수정 없음 | ✗ → ✓✓ |
| cffe0e32 c3 | "If the document itself leaves the column direction unresolved, … give the result under each possible reading." | "If the document does not resolve the column direction, state that ambiguity and give the best-supported answer." | ✗ → ✗✓ |
| 9e1fc53b c3 | "Use the original task's run reference date … or state that it cannot be derived only if specific …" | r0: "Use the abilities and class rules available when the identified dungeon was originally released" | ✗ → ✓✓ |

- 9e1fc53b c3 r1은 phase A에서도 "Use the run reference date, 2026-10-09"를 썼지만 정답이었음. phase A는 아직 v6 날짜 줄을 쓰기 때문에 이 경로가 남아 있었음.

## 6. 고쳐진 것
1. **규칙이 instruction의 보류 조항으로 복사되는 경로 — 고쳐짐 (근거가 강함)**
   - 같은 draft에서 refiner 문구만 바꿨고, 5개 run 모두 2 rep 정답이었음.
   - r9 rewrite의 조건문은 "확인하지 못하면 best-supported 답 + 확인하지 못한 것 명시" 형태임. "판단 불가라고 보고하라", "각 해석의 답을 내라"는 형태는 나오지 않았음.
   - 한계: r8 코드는 보관하지 않아서 r8 실패의 재현율은 재지 않았음. stage 4는 1 rep이었음.
2. **draft가 좁힌 대상을 원 task 표현으로 되돌림 — 작동함**
   - 56137764의 c2 r0과 c3 r1이 "credited for that addition"을 원 task의 "그 version의 기여자"로 되돌렸고, 정답이었음.
3. **실행 날짜가 질문의 시간 기준이 되는 경로 — 고쳐짐 (v7)**
   - 4d51c4bf: v7 draft가 "do not use the run date 2026-10-10"이라고 썼음. 날짜 filter를 여전히 고려했지만, c2/c3 rewrite가 "do not … apply an additional date filter"로 그것도 뺐음.
   - 9e1fc53b: c3 rewrite가 "do not choose a version based on the run date"라고 썼음.
   - 이 수정은 공통 prompt라 A와 fresh에도 적용됨.
4. **probe의 결론을 넘기는 경로 — 줄었지만 남음**
   - 대부분의 `context_additions`는 "header가 'Giftee | Recipient'라고 보고됨(미검증)"처럼 관찰만 넘겼음.
   - cffe0e32 c3 r0은 "either column reading yields a valid pairing"이라는 결론을 넘겼음(규칙 위반 1/2). 그 run이 hedge로 끝났음.

## 7. 여전히 문제인 것
### 7.1 orchestrator가 확인을 다시 맡긴 뒤 비답변으로 끝냄 (공통 prompt)
- **cffe0e32 phase B: 네 run이 같은 흐름을 거쳤고, 마지막 판단만 달랐음**
  - 흐름은 네 run(fresh, A, c2, c3) 모두 같았음.
    1. 첫 보고가 Fred를 냄.
    2. orchestrator가 표 방향("Giftee | Recipient")을 다시 확인하게 함.
    3. 확인 보고는 모두 "문서가 방향을 분명히 정하지 않는다"였음.
  - 마지막 판단이 run마다 갈렸음.

    | run | 최종 답 | orchestrator의 finish 근거 |
    |---|---|---|
    | fresh | Fred ✓ | "This is the intended inference for the requested giver" |
    | A | Fred ✓ | "the task's intended giver-to-recipient interpretation supports Fred" |
    | c2 | "Cannot be determined" | "it cannot identify the missing giver" |
    | c3 | "Micah" | "'Giftee' best supports reading the first column as the recipient" |

  - c2의 rewrite는 목표를 "선물하지 않은 사람"으로 분명히 했을 뿐 표 방향은 말하지 않았음. c3의 rewrite는 "방향은 문서와 task 표현으로 정하고, 불분명하면 best-supported 답을 내라"였음.
  - refiner arm에서 마지막 판단이 왜 다르게 나왔는지는 1 rep으로는 정할 수 없음.
  - 이전 report §10.2의 "A와 fresh는 Fred로 바로 끝났음"은 틀렸음. phase B에서는 둘 다 re-check를 했음. phase A의 A는 2 rep 모두 delegation 1번이었음.
- **cffe0e32 phase A c3 r0:** 첫 보고가 "Best-supported answer: Fred"였음. re-check 보고가 "문서가 방향을 정하지 않는다"고 하자 "Fred or Micah"로 끝났음.
- **a7feb290 fresh v7** (refiner 없음)
  - draft가 "당시 기준인가, 현재 기록인가"를 물었음. orchestrator가 확인 끝에 "Unable to determine"으로 끝냈음.
- **refiner만 고쳐서는 막을 수 없는 경로임.** 같은 확인 보고를 받고도 finish 판단이 정답, 비답변, 반대 해석으로 갈렸음. "증거가 불완전하면 무엇을 답할지"는 orchestrator의 finish 정책 문제임.

### 7.2 refiner가 해석을 확정하면서 증거 기준을 엄격하게 바꿈 (a7feb290, 4/4)
- phase B c2/c3(재실행 포함 4 run)의 resolution이 모두 "2020년 1월 **당시** 있었던 ps"로 정했음. 그리고 "do not count a ps version solely because it appears on a current record"를 붙였음.
- r9 규칙대로 "best available evidence로 답하라"도 들어갔음. 하지만 현재 기록을 증거로 쓰는 길이 막혀 있어서, archive 확인이 실패하자 비답변이 됐음.
- 같은 draft에서 A restore는 현재 format page를 세어 31로 맞혔음.
- 다만 이 해석은 draft가 먼저 물었고, refiner 없는 fresh도 같은 이유로 비답변이었음. refiner가 만든 문제라기보다 이미 있던 경향을 굳힌 것임.

### 7.3 사전 확인이 퍼즐 단서를 문자 그대로 검증함 (9e1fc53b c2, 1건)
- stage 1–4에서 0번이던 사전 확인(`needs_verification`)이 이번 재실행에서 2번 실행됐음.
  - a7feb290 c3 (phase A r0): listing URL이 맞는지 확인했음. 무해했음(A도 틀린 task).
  - 9e1fc53b c2 (phase B): 아래처럼 답을 바꿨음.
- "Kilt는 leather이고 'Allowable Classes: All Classes'라서 Hunter도 착용 가능"을 확인했고, 이 결과가 "아무도 쓸 수 없다"는 단서와 충돌해 답이 Hunter에서 Druid로 바뀌었음.
- 퍼즐의 의도된 읽기보다 문자 그대로의 사실을 우선한 것임. 1건뿐이라 정책을 바꿀 근거로는 부족함.

### 7.4 refiner가 도움이 된다는 증거는 아직 없음
- stage 4와 이번 재실행 모두에서 refiner arm만 맞힌 run이 refiner 덕분인 경우는 없었음.
  - 4d51c4bf(날짜 filter 제거)와 56137764(좁힘 복원)의 수정은 내용상 맞았음. 하지만 A도 맞히는 task였음.
- r9는 손해를 줄였지만, "올바른 수정이 GAIA에서 정답을 늘리는가"는 아직 답하지 못했음.

### 7.5 task 해석과 실행 자체의 불안정
- **676e5e31:** "개정(amendment)도 new version인가"에 따라 갈림. phase A c3 ✗✗ 중 r1은 refiner가 draft를 바꾸지 않은 run이었음. fresh v7도 71로 틀림.
- **a7feb290:** phase A에서 A가 30, 26을 냈음. 같은 draft에서도 세는 결과가 흔들림.
- **384d0dd8:** 모든 arm이 틀림. 날짜와 무관한 다른 원인.

### 7.6 측정과 운영의 한계
- **표본:** 8 task × 1–2 rep. draft가 같아도 결과가 17% 다르게 나오므로, 이번 정답 수 차이(phase B A 7 vs c2 4 등)는 noise와 구별되지 않음.
- **Serper 사고**
  - phase B에서 06:53–06:57에 시작한 restore 7개가 key 2 reserve에 걸려 검색 일부(restore 검색의 25%)가 DDG로 갔음.
  - guard의 key 전환 기준 150이 parallel 10의 무거운 run에는 너무 낮았음. 제가 정한 값임.
  - 결론에 영향이 있는 a7feb290 c2/c3는 key 3로 다시 돌렸고, 결과가 같았음.

## 8. 다음 후보 (결정은 사용자)
1. **orchestrator finish 정책 (공통 prompt, A에도 적용)**
   - 증거가 불완전하면 "Unknown" 대신 best-supported 답을 내게 함.
   - re-check는 답을 바꿀 구체적 관찰을 찾을 때만 쓰게 함.
   - 대상: 7.1(cffe0e32, a7feb290 fresh).
2. **refiner의 해석 확정이 증거 기준을 바꾸지 못하게 하기**
   - 예: "현재 기록은 세지 마라"를 금지.
   - 7.2 대상. 단 a7feb290 하나에 맞춘 수정이 될 위험이 있음.
3. **needs_verification:** 1건뿐이라 판단 보류.
4. **47개 전체 재실행으로 r9 + v7의 순효과 측정**
   - 약 $8–9, Serper 약 3,300 credit 필요. 남은 credit은 2,380이라 충전이 필요함.
   - 7.4의 질문(올바른 수정이 이득인가)에 답하려면 결국 필요함.

## 9. 제가 정한 것
- **수정 문구**
  - r9와 v7의 문구 전체.
  - v7은 날짜 줄을 없애지 않고 의미만 바꿈. 없애면 모델마다 자기 "오늘"을 가정하게 되고, run마다 날짜를 고정하는 기능(F19)도 잃기 때문임.
- **재실행 설계**
  - 재실행을 phase A(같은 draft)와 phase B(v7 fresh + restore)로 나눔.
  - 대상 task 선정(§4). A도 phase A에서 2 rep을 돌림.
- **r8은 보관하지 않음**(r6, r7 관례). 그래서 r8 실패의 재현율은 재지 않았음.
- **Serper 재실행 범위:** a7feb290 c2/c3만 다시 돌림. DDG가 섞인 나머지 run(384d0dd8 ×3, a7feb290 A, 9e1fc53b c3)은 결론에 영향이 없다고 보고 그대로 둠.
- **분류 기준**
  - "r8이 망친 run"은 "A는 정답, refiner arm은 rewrite 뒤 오답"으로 정의함.
  - 비답변과 "새 조건문"은 regex로 셈(scratchpad `rerun_analyze.py`, `s34_analyze.py`).
- **이 report:** 이전 report §4, §9, §10을 재구성한 것이고, 새 run은 돌리지 않았음. 위치는 `docs/reports/2026-10-10-refiner-diagnostics.ko.md`.

## 10. 파일
- **이전 report:** `docs/reports/2026-10-09-baseline-and-probe-comparison.ko.md` (§9 해석 정정, §10 재실행 원 기록)
- **상태:** 당시 `outputs/sessions/STATUS_20261009.md`(2026-10-10 절). 2026-10-11 정리에서 삭제했고 내용은 최신 종합 보고서로 대체함(`docs/reports/retention.json`).
- **trace** (ZIP 묶음은 2026-10-11 정리에서 삭제)
  - stage 4: `outputs/experiments/2026-10-09_probe-condition-comparison/analysis/selected-traces/`. 현재 색인은 `index.csv`, 당시 표는 `historical-cases.csv`.
  - 재실행: `outputs/analysis/2026-10-10-followup-traces/`. README에 task × phase 결과표, `historical-runs.csv`(당시 `runs.csv`)에 run별 답, gold, refine 결과가 있음. 현재 색인은 `index.csv`.
- **결정 기록:** `docs/history/decisions-before-cleanup.md`의 R24(r9), F23(v7), E10(재실행 범위)
