> 과거 실험 보고서입니다. 해석·수치의 정정은 [최신 종합 보고서](2026-10-10-synthesis.ko.md)를 우선하세요.

# 실패 trace 정밀 분석: probe 질문의 역할과 실행 전 instruction 수정의 여지 (2026-10-10)

- **대상:** baseline_v1 50개 task의 모든 결과와 10-10 재실행.
  - v5 fresh, v6 fresh
  - stage 4: 47 task × A_none / c2 / c3, refiner r8
  - 재실행 phase A(r9)와 phase B(v7 + r9)
- **새로 돌린 run은 없음.** 저장된 trace만 분석했음. 이 report의 "막을 수 있었다"는 모두 trace를 근거로 한 판단이고, 실험으로 확인하지 않았음.
- **task별 분석 원문:** `docs/reports/cases/analysis/<task>.md` (§8)

## 0. 요약

### 질문 1. probe의 각 질문은 실제로 어떤 역할을 했나
probe는 worker에게 실행 전에 네 가지를 묻고, c2/c3에서는 tool로 짧게 확인하게 함(§2.1).

| 항목 | 실제로 한 일 | issue의 출처 (r8 / r9) |
|---|---|---|
| understanding | luna는 거의 task를 다시 말함(42/44). haiku는 미리 답을 풀어 적는 칸으로 씀(10/22) | 0 / 0 |
| choices | **issue의 주된 출처.** 맞는 지적과 해로운 지적이 모두 여기서 나옴 | 31/50 / 16/35 |
| risks | 실행 중의 진짜 난관을 자주 맞힘. 다만 instruction으로 고칠 수 없는 것이 대부분이라, issue가 되면 확인 관문이나 보류 조건으로 바뀜 | 9 / 6 |
| plan | 대부분 draft를 그대로 따라감(luna 37/44). 거의 쓰이지 않음 | 3 / 3 |
| tool 확인 | 가장 꾸준히 유용한 사실을 냄. 하지만 rewrite할 때만 worker에게 전달되고, 결론이나 답이 함께 새기도 함 | 보조 근거로 자주 인용 |
| (analysis가 draft와 task를 직접 비교) | probe 답과 관계없이 analysis가 draft와 task를 비교해 찾은 것. r9의 맞는 지적은 여기서 많이 나옴(5/11) | 5 / 8 |

- **probe 답에는 실패 원인의 신호가 자주 있었음.** 실패가 있었던 task 중 10개에서 probe가 실제 실패 원인이나 그 근처를 짚었음(§2.5).
- **그런데 analysis가 그 신호를 쓰지 않거나, 더 엄격한 조건과 보류 조건으로 바꿨음.** 병목은 probe 질문이 아니라 그것을 받는 analysis와 rewrite 단계임.
- **analysis의 패턴**
  - task 문장이 답을 정해 주는 지점에서는 task 쪽으로 바로잡음.
  - task가 말하지 않는 지점(판본, 시점, "added", 표 방향 등)에서는 확인 관문, 보류 조건, 엄격한 기준을 추가함.
  - 해로운 issue는 거의 모두 두 번째 경우에서 나왔음.

### 질문 2. 실행 전에 instruction을 고쳤다면 막을 수 있었던 실패는 얼마나 되나
- **기준:** refiner 없이 처리된 run(A-equivalent)이 한 번이라도 틀린 task는 22개임(§3.1).

| 분류 | task 수 | task |
|---|---|---|
| 막을 수 있었다는 근거가 강함 | **3** | 2dfc4c37, 50f58759, 4b6bb5f7 |
| 방법 지식을 적어 주면 도왔을 수도 있음 (확신 낮음) | 5 | c526d8d6, 16d825ff, a7feb290, 676e5e31, 8131e2c0 |
| instruction으로 막을 수 없음 | 14 | gold·채점 4, 출처 데이터 변화 2, 접근 불가 1, 실행 중 읽기·운 6, 재검증과 시간 예산 1 |

- **stage 4 A의 오답 14개만 보면**
  - 강한 근거가 있는 것은 2개, 가능한 것은 2개임.
  - instruction이 완벽했어도 A 33/47이 **최대 35–37/47** 정도였다는 뜻임.
- **refiner는 이 8개 중 하나도 고치지 못했음.**
  - 2dfc4c37: probe도 draft의 잘못된 읽기를 그대로 따랐고, analysis는 issue를 찾지 못했음.
  - 50f58759: rewrite가 잘못된 읽기를 명시해서 굳혔음.
  - 4b6bb5f7: haiku probe가 맞는 읽기를 말했는데 analysis가 no_issues로 넘겼음.
  - c526d8d6: probe 둘이 원인을 짚었는데 쓰지 않았음.
- **반대 방향: refiner rewrite 때문에 생긴 실패(같은 draft의 A는 정답)**
  - r8에서 7 run.
  - r9에서 4–5 run(9e1fc53b, a7feb290).

### 부수 발견 (§4)
- **tool 버그:** Wayback snapshot에 실제 capture 날짜가 아니라 요청한 날짜가 붙음. 16d825ff와 a7feb290의 결과에 영향을 줬음.
- **오염:** OWL 논문(arXiv 2505.23885)이 GAIA 풀이 단계를 담고 있음.
  - 8131e2c0 s4 A의 정답은 이 논문 snippet에 정답이 노출된 결과였음.
  - 오염 audit는 이것을 잡았지만 "audit only" 휴리스틱으로만 분류했음.
- **gold와 데이터 문제**
  - 72c06643의 gold는 액체인 Freon-12에 이상기체 식을 씀.
  - bec74516, 384d0dd8, 16d825ff는 gold 이후 출처 데이터가 바뀌었음.
- **이전 report의 정정 5건(§4.5).**

## 1. 범위와 방법
### 1.1 대상
| 묶음 | run 수 | 설명 |
|---|---|---|
| v5 fresh, v6 fresh | 50 + 50 | refiner 없음. 검색이 DDG로 저하됨 |
| stage 4 | 141 | v6 d0 checkpoint 47개 × A_none / c2 / c3, Serper, refiner r8 |
| 재실행 phase A | 42 | 같은 v6 checkpoint, refiner r9, 2 rep |
| 재실행 phase B | 34 | v7 fresh 8, restore 24, Serper 재실행 2 |

- **실패가 한 번이라도 있었던 26개 task**의 run 193개는 전부 정밀 분석했음.
- **세 arm이 모두 맞힌 22개 task**는 refiner 기록 44개(c2 22, c3 22)만 분석했음.

### 1.2 방법
- 공통 기준(`RUBRIC.md`)을 정하고, subagent 9개가 task를 나눠 transcript를 읽었음.
  - 모든 worker 보고와 orchestrator action을 읽었고, 결정적인 tool 결과는 원문을 확인했음.
- **실패 run마다 판정한 것**
  - 결정적 실패 지점: 그 뒤로 정답에 다시 닿지 못한 첫 지점.
  - 원인 코드(아래 표).
  - 실행 전 수정 가능성 4단계(아래 정의).
- **refiner 기록마다 판정한 것**
  - probe 항목별로 무엇을 말했는지.
  - 받아들여진 issue의 출처 항목과 품질.
  - A 대비 효과.

| 원인 코드 | 뜻 |
|---|---|
| I-DRAFT | orchestrator의 d0 instruction이 task에서 벗어남(대상, 범위, 시점, 조건, 형식) |
| I-REWRITE | refiner rewrite가 이탈이나 조건을 넣음 |
| I-OMIT | instruction은 충실했지만, task 문장이 정하는 읽기를 적지 않아 worker가 다르게 읽음 |
| X-RETRIEVE / X-READ / X-REASON / X-BUDGET | 출처에 닿지 못함 / 잘못 읽음 / 추론·계산 오류 / tool 상한·시간 |
| O-RECHECK / O-FINISH / O-FORMAT | orchestrator의 재확인이 정답에서 멀어지게 함 / finish 판단 / 요청하지 않은 형식 |
| S-SCORER | 채점이 같은 답을 거부함, 또는 gold 오류 |

- **실행 전 수정 가능성 4단계**
  - **YES-FAITHFUL:** instruction에 task와 다른 점이 있었음. task에 충실한 instruction이었다면 막았을 것.
  - **YES-TASKTEXT:** instruction은 충실했지만, task 문장만으로 끌어낼 수 있는 한 문장(읽기, 정의, 형식)을 더했으면 막았을 것.
  - **MAYBE-KNOWHOW:** 방법이나 출처에 관한 지식을 적어 주면 도왔을 수도 있음. 실행 전에 알 수 있었는지를 따로 판단함.
  - **NO:** d0 instruction으로는 막을 수 없음.
- 실행 중에야 알게 된 사실(이름, 값, 어느 페이지에 답이 있는지)을 쓰는 수정은 인정하지 않았음.

### 1.3 제가 직접 확인한 것
subagent의 판정 중 report의 결론을 받치는 것은 trace나 코드에서 직접 확인했음.
- 2dfc4c37: v5/v6 draft의 문구(별도 Domestic 목록 지시).
- 50f58759: v6 draft 문구.
- 4b6bb5f7: c3 haiku understanding("the setting is called 'The Castle'")과 c3의 no_issues.
- c526d8d6: c2 luna choices와 c3 luna risks의 문구.
- 872bfbb1: c2 worker의 추론("pears, then bananas")과 보고("treated … as oranges")가 다름.
- f3917a3d: haiku가 2,822를 관찰한 것.
- 16d825ff, a7feb290: Wayback 표기 버그(코드 `tools/web.py`의 `doc_header`와 transcript).
- 8131e2c0: OWL snippet의 "Answer: 101.376, 84.348", 그리고 contamination.json의 분류.
- 9b54f9d9 rA c3 r1: d1 보고에 엄격한 읽기가 다시 나옴.
- 56137764: orchestrator의 "The revised criteria require …".
- 72c06643, bec74516: annotator 풀이 단계(이상기체 식, "pre-2022").

### 1.4 한계
- 판정은 LLM subagent가 기준에 따라 내린 것임. 품질 라벨(예: REDUNDANT와 OTHER의 경계)은 subagent마다 조금씩 다를 수 있음.
- 표본이 작음. 같은 draft에서도 결과가 17% 달라지는 noise가 있어서, 판정마다 같은 draft의 다른 run 결과를 함께 적었음.
- 제안된 수정 instruction(§6)은 gold를 아는 상태에서 쓴 것임. 답은 넣지 않았지만, 해석을 고를 때 gold 쪽으로 기울었을 수 있음.

## 2. 질문 1: probe의 각 질문이 한 역할
### 2.1 probe가 묻는 것
probe는 draft instruction을 보여 주고 실행 전에 다음 넷을 답하게 함(r6 이후 같은 문구).
- **understanding:** "One sentence stating the result you would produce and its scope."
- **choices:** "Interpretations or assumptions you would use where the task, context, or instruction leaves room for judgment. … Do not merely repeat given conditions."
- **risks:** "Task-specific risks that could produce an incorrect result or prevent completion. Avoid generic possibilities …"
- **plan:** "The steps you would take for the whole subtask, including how you would handle relevant risks."
- c2/c3에서는 tool을 3번까지 쓸 수 있고, 관찰한 것을 출처와 함께 보고함.

### 2.2 무엇을 담았나
응답 하나당 평균 항목 수(stage 4, 파싱 기준):

| 모델 | 응답 수 | choices | risks | plan |
|---|---|---|---|---|
| luna | 94 | 1.2 | 1.1 | 3.4 |
| haiku | 47 | 3.2 | 3.1 | 5.9 |

세 arm이 모두 정답인 22개 task(44 기록)에서 각 항목 내용을 "의미 있음 / 근거 없음(spurious) / 재진술"로 나눈 결과:

| 항목 | 모델 | 의미 있음 | spurious 포함 | 재진술(nothing) |
|---|---|---|---|---|
| understanding | luna (44) | 2 | 0 | 42 |
| understanding | haiku (22) | 10 (대부분 미리 푼 답) | 2 | 9 |
| choices | luna | 21 | 3 | 20 |
| choices | haiku | 18 | 7 | 1 |
| risks | luna | 29 | 16 | 4 |
| risks | haiku | 15 | 14 | 0 |
| plan | luna | 6 | 2 | 37 |
| plan | haiku | 12 | 6 | 7 |
| tool 확인 | luna (tool 쓴 34) | 28 | 0 | 6 |
| tool 확인 | haiku (tool 쓴 21) | 19 | 1 | 2 |

- **"의미 있음"의 대부분은 사실 발견이었음.** draft가 task에서 벗어난 점을 짚은 것은 22개 task 중 4d51c4bf 하나였음(세 응답자가 모두 짚음). 이 22개 task 중 실제로 draft에 이탈이 있던 것도 그 하나뿐이었음.
- **luna의 choices 43%(19/44)는 draft나 task 조건을 되풀이했음.** probe가 "Do not merely repeat given conditions"라고 했는데도 그랬음.

### 2.3 issue는 어느 항목에서 나왔고, 맞았나
r8은 stage 4(실패 task 기록과 정답 task 기록을 합쳐 50개 issue), r9는 재실행(35개 issue)임. 출처는 issue의 evidence가 주로 근거로 삼은 항목임.

**r8 (50개)**

| 출처 | 맞는 지적 | 불필요 | 해로움: 엄격 | 해로움: 좁힘 | 해로움: 모호·보류 | 잘못된 읽기 | 기타 | 계 |
|---|---|---|---|---|---|---|---|---|
| choices | 3 | 10 | 8 | 1 | 4 | 4 | 1 | 31 |
| risks | 1 | 3 | 1 | 0 | 1 | 3 | 0 | 9 |
| plan | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 3 |
| draft-vs-task | 3 | 2 | 0 | 0 | 0 | 0 | 0 | 5 |
| 기타 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 2 |
| 계 | 9 | 15 | 10 | 1 | 7 | 7 | 1 | 50 |

**r9 (35개)**

| 출처 | 맞는 지적 | 불필요 | 해로움: 엄격 | 잘못된 읽기 | 기타 | 계 |
|---|---|---|---|---|---|---|
| choices | 3 | 3 | 4 | 0 | 6 | 16 |
| draft-vs-task | 5 | 0 | 2 | 1 | 0 | 8 |
| risks | 1 | 1 | 3 | 0 | 1 | 6 |
| plan | 1 | 1 | 0 | 0 | 1 | 3 |
| tool 확인 | 1 | 0 | 0 | 0 | 0 | 1 |
| 기타 | 0 | 0 | 0 | 0 | 1 | 1 |
| 계 | 11 | 5 | 9 | 1 | 9 | 35 |

- **해로운 issue의 비율:** r8 25/50(50%)에서 r9 10/35(29%)로 줄었음. r9에서는 "좁힘"과 "모호·보류"가 사라졌음.
- **r9에도 "엄격" 9개가 남았음.** a7feb290의 "2020년 1월 당시", 9b54f9d9의 "비슷하다는 이유로 짝짓지 마라", 9e1fc53b의 "armor type만으로 판단하지 마라" 등임.
- **decision별 (r8):**
  - defer_to_execution은 22개 중 15개가 해로웠음(68%).
  - clarify는 26개 중 8개가 해로웠음(31%). clarify는 "불필요"가 많았음(12개).
- **r9의 맞는 지적 11개 중 5개는 probe 답이 아니라, analysis가 draft와 task를 비교해서 찾은 것임.** draft가 좁힌 대상을 되돌린 경우(56137764, 676e5e31 rB, 9b54f9d9 rB)가 그 예임.
- **"기타"(r9 9개):** 무해하지만 근거가 약한 확장(예: 56137764의 "중국 총리에 한정하지 마라")과, 해결할 수 있는 표 방향을 열어 둔 채 넘긴 것(cffe0e32) 등임.

### 2.4 항목별 역할과 대표 사례
**understanding: review에서는 거의 역할이 없음**
- luna는 task를 거의 그대로 다시 말했음.
- haiku는 미리 풀어 버리는 칸으로 썼음.
  - 3ff6b7a9: "Wikipedia's 2020 estimate … is 56,081, which rounds to 56,000"
- 맞는 읽기가 여기 담긴 경우도 analysis는 쓰지 않았음.
  - 4b6bb5f7 c3 haiku: "… is `INT. THE CASTLE - DAY`, so the setting is called 'The Castle'"
  - analysis는 no_issues였고, 이 run은 heading 전체로 답해 틀렸음.

**choices: issue의 주된 생성기. 좋은 것과 나쁜 것이 같이 나옴**
- **맞는 예:** 4d51c4bf. 세 응답자가 모두 draft의 "run reference date 기준 90일" filter가 데이터와 맞지 않음을 짚었음. c2는 이를 반영해 filter를 뺐고, c3는 같은 신호를 받고도 draft를 남겼음(조건부라 무해).
- **나쁜 예 1 — 자연스러운 읽기를 이탈로 취급함 (5b2a14e8)**
  - 응답자가 "I would treat the date as the story's publication date"라고 적었음.
  - analysis는 이를 issue로 만들어 "do not assume it means publication date … If the date cannot be matched unambiguously, report the ambiguity"를 넣었음.
  - c3에서는 이 조건이 이후 모든 delegation에 따라붙었고, 유보 보고 때문에 delegation이 하나 더 생겼음.
- **나쁜 예 2 — 맞는 선택을 놔두고 risks를 키움 (cffe0e32 s4 c3)**
  - haiku의 choices는 Fred 쪽 읽기를 골랐음.
  - analysis는 같은 응답의 risks("반대로 읽으면 Micah")를 "각 읽기의 결과를 내라"로 키웠음.
- **나쁜 예 3 — 맞는 probe 선택을 뒤집음 (676e5e31 s4 c2)**
  - probe의 원래 선택은 맞는 읽기였음.
  - analysis가 "preserve other qualifiers"로 뒤집어 frozen Apples가 빠졌고, 6/6 = 100%가 됐음.

**risks: 실행의 난관은 잘 맞히지만 instruction으로 고칠 일이 아님**
- 맞힌 예:
  - 5b2a14e8: 로고 판독 불가
  - d5141ca5: template 전치
  - 114d5fd0: JSTOR 차단
  - 65638e28: 출판사 사본 차단
  - 16d825ff: "현재 시간표는 다를 수 있다, Wayback을 써라"
  - c526d8d6 c3 luna: "labels need to be matched to the paper's equation"
- 이런 위험을 받은 analysis가 한 일은 대개 확인 관문이나 "확인 못 하면 한계를 보고하라"를 추가하는 것이었음.
  - c8b7e059, c3a79cfe, 0b260a57: 결과가 유보, 추가 delegation, 엄격한 증거 기준으로 이어졌음.
  - 384d0dd8: haiku의 "live data" 위험이 r8 rewrite의 "records as of 2026-10-09"(실행 날짜를 기준으로 삼음)가 됐음.

**plan: 대부분 draft를 그대로 따라감**
- luna의 plan은 37/44가 draft를 따라갔음.
- haiku의 plan에는 실용적인 방법(예: Python 교차 확인, 다른 사본 출처)이 있었지만 쓰이지 않았음.
- 틀린 경로가 issue가 된 경우가 한 번 있었음.
  - c3a79cfe: plan의 "7 intervals" 후보 경로 → "8 is conditional" 유보.

**tool 확인: 가장 유용하지만 전달 방식이 문제**
- 응답자들이 entity, 파일 구조, 심지어 답까지 찾았음.
  - 3ff6b7a9: 56,081
  - f3917a3d: 총 편집 수 2,822. 이것만 있었으면 2732가 바로 나왔지만, 그렇다는 것은 결과를 알고 나서야 보임.
- 그런데 이 발견은 rewrite할 때 `context_additions`로만 worker에게 감. no_issues면 아무것도 전달되지 않음.
  - 5b2a14e8 c3: haiku가 "Ruffwear Front Range"를 맞혔는데 버려졌고, 브랜드 식별에 delegation 8개가 들었음.
- 전달될 때는 결론이나 답이 같이 샜음.
  - 3ff6b7a9: 답 56,081
  - cffe0e32 rA c3 r0: "either column reading yields a valid pairing" → hedge로 끝남
- 관찰이 길을 막은 경우도 있었음.
  - a7feb290: "/list/hep-lat/2001은 2001년 목록"이라는 관찰 때문에, [ps] 표시가 남아 있는 옛 URL의 archive 경로가 "틀린 URL"로 취급됐음.

### 2.5 실패 원인의 신호가 probe에 있었나
| task | probe에 있던 신호 | analysis가 한 일 | 결과 |
|---|---|---|---|
| 4b6bb5f7 | haiku understanding이 맞는 읽기("setting = The Castle") | 무시(no_issues) | c3 오답 |
| c526d8d6 | c2 luna choices "rather than assume the familiar modern equation", c3 luna risks "labels need to be matched to the paper's equation" | c2 무시. c3는 "속도를 정할 수 없으면 그렇다고 보고하라" 추가 | c2 오답, c3 비답변 |
| 9e1fc53b | 여러 probe가 "bear는 Druid로 읽히는데 leather Kilt를 쓸 수 있다"는 모순을 짚음. haiku가 정답 roster를 직접 냄(2번) | 날짜 기준이나 문자 그대로의 장착 확인으로 바꿈 | s4 c2/c3, rB c2 오답 |
| a7feb290 | 응답자들이 "현재 format 페이지를 best evidence로", "listing으로 세면 0이 나온다" | 덮어쓰고 "당시 기준, 현재 기록 불인정"으로 정함 | r9 phase B 4/4 비답변 |
| cffe0e32 | haiku choices는 Fred, risks는 Micah 가능성 | r8: 두 답 모두 내라. r9: 방향을 열어 둠 | s4 c3 이중 답, rA c3 r0 hedge |
| 50f58759 | c3 haiku risks "each day of August의 의미가 결정적" | 잘못된 쪽(트윗 게시일)으로 해소 | 비답변 (A도 같음) |
| 16d825ff | c3 luna "현재 시간표는 다를 수 있다, Wayback" | archived 시간표 대체 규칙으로 만들지 않음. Memorial Day 확인만 추가(A는 스스로 했음) | c3 정답(운, §4.1) |
| 384d0dd8 | haiku "live data, 접근 시점" | 실행 날짜 기준으로 고정 | 비답변 (A도 오답) |
| 0b260a57 | "데이터를 아직 못 찾음" | 엄격한 증거 규칙으로 바꿈 | 비답변 (A도 같음) |
| 676e5e31 | haiku가 "amendment는 new version이 아니다"를 제안(이것이 실제로 나중의 실패 기준) | issue로 받지 않음(옳음) | – |

- **신호가 없었던 실패:**
  - 2dfc4c37: 모든 응답자가 draft의 두 목록 읽기를 따랐음.
  - 8131e2c0: 표시 반올림이나 단위를 예상한 항목이 없었음.
  - bec74516, 72c06643, 853c8244, 3da89939, 6b078778, 872bfbb1, 708b99c5, 366e2f2b, ded28325: 실행 중이나 채점에서 생기는 문제라 실행 전 신호가 있을 수 없었음.
- **정리:** probe의 네 질문 자체는 필요한 신호를 꽤 자주 끌어냈음. 문제는 analysis 단계였음.
  - 맞는 신호를 버렸음(4b6bb5f7, c526d8d6 c2, 5b2a14e8).
  - 신호를 "확인하라 / 확인 못 하면 보고하라 / 엄격하게 하라"로 바꿨음(c526d8d6 c3, a7feb290, 384d0dd8, 9e1fc53b).

### 2.6 analysis와 rewrite 단계의 패턴
1. **task 문장이 답을 정해 주면 task 쪽으로 바로잡음.**
   - e2d69698: 시즌 기준
   - bda648d7: "Saint"
   - d5141ca5: template
   - 56137764, 676e5e31, 9b54f9d9의 r9 rB: draft의 좁힘을 원 task 표현으로 되돌림
2. **task가 말하지 않는 지점에서는 관문, 보류, 엄격한 기준을 넣음.**
   - 판본(a56f1527), "added"(5b2a14e8), "as of"(c8b7e059), "compiled"(dd3c7503), 시점(a7feb290), 표 방향(cffe0e32), 장착 가능 여부(9e1fc53b)
   - 해로운 issue는 거의 모두 이 경우임. r9는 보류 조항을 없앴지만, 엄격한 기준을 정하는 일은 그대로 남았음.
3. **rewrite에 issue나 `changes`에 없는 조항이 들어감.**
   - a7feb290 rB c2: "rather than treating a generic 'Other formats' link or format-selector page as proof". 이 조항 때문에 worker가 이미 확인한 약 30개 양성을 버렸음.
   - 384d0dd8 s4 c2, a7feb290 rA c3 r0에도 같은 일이 있었음.
4. **orchestrator는 rewrite를 권위 있는 기준으로 받아들임.**
   - 56137764 s4 c2: "The revised criteria require credit for the addition itself" → "No matching contributor"
   - s4 c3: "Verify the evidence needed for the revised task"
   - A에서는 orchestrator가 finish에서 원래 task 표현으로 돌아와 draft의 좁힘을 스스로 바로잡았음(56137764 A 4/4 정답). rewrite가 이탈을 담으면 이 복구 기회가 없어짐.
5. **c3(haiku 포함)는 issue를 많이 만듦.**
   - 정답 22개 task에서 rewrite율이 c3 12/22, c2 4/22였음. c3 issue 15개 중 12개의 주 출처가 haiku였음.
   - haiku의 spurious 내용이 그대로 채택되기보다, analysis가 "그 지점을 명시하라"고 반응하고 그 명시가 엄격한 쪽으로 기우는 경우가 많았음.
6. **정답 task에서 rewrite의 효과**
   - rewrite 16건 중 정답을 바꾼 것은 없음.
   - 4건은 비용이나 delegation을 늘렸고, 2건은 보고의 유보를 늘렸음.
   - 같은 task끼리 비교하면 c3 rewrite run의 비용은 A보다 39% 많았음.

## 3. 질문 2: 실행 전 instruction 수정으로 막을 수 있었던 실패
### 3.1 셈의 기준
- **A-equivalent:** refiner 없이 처리된 run. fresh run, A restore, issue가 없어 draft가 그대로 나간 c2/c3 run(no_issues)이 해당함. 같은 checkpoint의 run은 d0 draft가 같음.
- 50개 task 중 A-equivalent가 한 번이라도 틀린 task는 **22개**임.
  - 13개는 정답이 한 번도 없었음(8131e2c0은 오염된 1건을 빼면).
  - 9개는 맞기도 하고 틀리기도 했음.
- 이 밖에 refiner run에서만 틀린 task 4개(56137764, 9b54f9d9, 9e1fc53b, cffe0e32)는 §3.6에서 다룸.

### 3.2 22개 task 분류
| task | A-equivalent 정답/run | 실패의 핵심 | 실행 전 수정 |
|---|---|---|---|
| **2dfc4c37** | 0/5 (전부 3, 정답 6) | draft가 task의 "2020 Worldwide 목록에 따르면"을 벗어나 별도의 calendar-year Domestic 목록과 비교하게 함. worker는 지시대로 정확히 수행함 | **YES-FAITHFUL (high)** |
| **50f58759** | 0/3 | draft가 대상("August 1"…"August 31" 문서)을 짚지 않고 "의미를 밝히고 dataset/dump를 찾고 가능한지 판단하라, 추측하지 마라"로 씀 → Wikipedia 전체를 세려다 비답변. 필요한 정보에는 닿을 수 있었음(v5가 해당 문서 revision을 API로 읽음) | **YES-FAITHFUL (high)** |
| **4b6bb5f7** | 2/5 (v6 draft 2/4) | task가 "setting"을 묻는데 heading 전체 "INT. THE CASTLE - DAY"로 답함. orchestrator는 worker 보고의 Result 줄을 그대로 옮김. v5 draft는 "heading exactly as printed"를 지시함(I-DRAFT) | **YES-TASKTEXT (med)** |
| c526d8d6 | 0/4 | 모든 run이 PMC 페이지에서 "Menten constant" 정의 문장(k_m = kcat/Km)을 읽고도 열을 Km으로 대응시켜 0.0429. 마지막 식은 이미지라 text에서 빠짐 | MAYBE-KNOWHOW (med) |
| 16d825ff | 1/4 (v6 draft 1/3) | 2019년 5월 보고서가 비표준 파일명이라 CDX 목록으로만 찾을 수 있음. 2019년 시간표 archive는 없고, 현재 시간표는 바뀜(6:12 PM). 실행 중 IA 장애도 있었음. 맞힌 run은 Wayback 표기 버그 덕분(§4.1) | MAYBE-KNOWHOW (low) |
| a7feb290 | 3/9 (v6 draft 2/6, v7 draft 1/2) | 세는 과정의 불안정: format 페이지 판정, /ps/ endpoint 오판, 위치 batching, 늦은 재확인. v7 draft의 "당시냐 현재냐" 질문도 비답변을 부름 | MAYBE-KNOWHOW (low) |
| 676e5e31 | 5/8 | d0에서 먼 후속 delegation에서 orchestrator가 "amendment는 new version 아님" 기준을 세우거나 날짜를 잘못 읽어 blended 표준이 빠짐 | YES-TASKTEXT (low) |
| 8131e2c0 | 0/4 (+오염된 정답 1) | Google Sheets CSV export가 표시 반올림 값(101.38)을 줌. 저장값은 XLSX에만 있음 | MAYBE-KNOWHOW (low) |
| 708b99c5 | 0/5 | "Citation count"가 gold "Citations"와 문자열로 안 맞음 | NO (채점) |
| 366e2f2b | 0/3 | curly apostrophe | NO (채점) |
| ded28325 | 0/5 | gold 오타 "Ploybius" | NO (gold) |
| 72c06643 | 0/4 | gold가 액체 Freon-12에 PV=nRT를 씀. run들은 상태방정식으로 물리적으로 맞는 193 mL를 냄 | NO (gold) |
| bec74516 | 0/5 | ORCID 기록이 gold 이후 늘어남(지금 맞게 세면 약 35.8). 일부 run은 page reader의 두 응답을 이중으로 더함(59). annotator는 "pre-2022"로 셈 | NO (데이터 변화) |
| 384d0dd8 | 0/7 | 지금의 PubChem 목록으로는 gold(4192)가 나올 수 없음(insulin, NADPH 등이 앞섬) | NO (데이터 변화) |
| 0b260a57 | 0/4 | ScienceDirect가 IP 차단. 2022년 archive에는 필요한 filter 페이지가 없음 | NO (접근 불가) |
| 853c8244 | 0/5 | 그림에서 손이 보이는 동물 수를 잘못 셈(12 또는 10, 정답 11) | NO (읽기) |
| 3da89939 | 1/4 | J-STAGE PDF를 열지 않음. 같은 draft의 c2는 나중에 열어 맞힘 | NO (운) |
| 65638e28 | 3/4 | A만 archive.org 사본을 열지 않고 일찍 끝냄 | NO (운) |
| 6b078778 | 4/5 | worker가 "Visconte" 표기를 앞세우고 orchestrator가 그대로 옮김 | NO (운) |
| 872bfbb1 | 4/5 | worker가 추론에서는 맞혔는데 보고에서 lemon을 orange로 바꿈 | NO (운) |
| f3917a3d | 4/5 | 두 출처를 빼는 방식으로 셈해 1 차이 | NO (운) |
| 851e570a | 0/2 | 두 run 모두 d0에서 BRINIEST를 찾았음. 그 뒤 orchestrator가 전체 재검증을 맡겨 시간 예산이 다 떨어졌고 답 없이 끝남 | NO (orchestrator·예산) |

### 3.3 근거가 강한 3개
**2dfc4c37 (Box Office Mojo)**
- task: "According to Box Office Mojo's 2020 Worldwide Box Office list, how many of the top 10 highest-grossing worldwide movies are also on the top 10 highest-grossing domestic movies?"
- annotator는 Worldwide 목록 한 페이지에서 Domestic 열로 정렬해 6을 얻음.
- draft들은 다른 목록과 비교하게 했음.
  - v5: "2020 yearly domestic box office top 10 … using the lists as available for the run reference date"
  - v6: "2020 Domestic Box Office list (annual, calendar year 2020)"
- 이 별도 목록에는 2019년 개봉작(1917, Jumanji, Star Wars IX, Little Women)이 들어 있어 겹치는 수가 3이 됨.
- worker들은 Worldwide 표의 Domestic 열 값을 화면에 가지고 있었지만, 지시대로 두 목록을 비교했음.
- 단서: task 문장이 완전히 한 가지 읽기만 허락하는 것은 아님. 그래도 "According to … Worldwide list"는 출처를 한 목록으로 한정하는 쪽을 지지하고, draft는 다른 쪽을 골라 못 박았음.

**50f58759 (Wikipedia 8월 날짜 문서)**
- task: "How many times was a Twitter/X post cited as a reference on the english Wikipedia pages for each day of August in the last June 2023 versions of the pages?"
- v6 draft는 task를 인용한 뒤 "Clarify the likely intended meaning … Search for an existing dataset/query/tool if possible; otherwise determine feasibility … Do not guess."라고 썼음.
- 그 결과 A, c2, c3 모두 Wikipedia 전체에서 날짜별로 세려 했고, 불가능하다며 비답변으로 끝났음.
- c2/c3 rewrite는 이 읽기("publication day-of-month … pooled across all years")를 명시해서 굳혔음.
- v5는 맞는 문서를 읽었지만 다른 문제로 틀렸음.
  - "6월에 만들어진 revision"으로 읽어 12개 문서를 건너뜀.
  - 날짜별 목록으로 답함.

**4b6bb5f7 (Doctor Who 대본)**
- task는 "What is this location called … Give the setting exactly as it appears in the first scene heading"임.
- 같은 v6 draft에서 결과가 2/4로 갈렸음. 맞힌 run의 worker는 보고에 "The location is THE CASTLE"이라고 썼음.
- orchestrator는 그때그때 Result 줄을 그대로 옮겼음.
- d0 instruction에서 "setting"을 heading의 장소 부분으로 정의하면, worker 보고뿐 아니라 orchestrator 자신의 대화에도 남아 finish까지 닿음(subagent가 `llm_calls.jsonl`로 확인).

### 3.4 불확실한 5개
- **c526d8d6:** 원인 문장을 모든 run이 읽었음. 그래서 instruction에 다음 세 가지를 쓰면 도왔을 수 있음. 셋 다 task 문장과 일반 지식에서 나오는 것임.
  - 열 이름을 문서의 정의로 대응시켜라.
  - "final equation"을 문자 그대로 문서의 마지막 식으로 읽어라.
  - 식이 이미지일 수 있다.
  - 다만 같은 경로가 4번 같은 방식으로 실패해서 효과를 장담할 수 없음.
- **16d825ff:** 쓸 만한 수정은 일반적인 방법 지식임. 예: 추측한 URL이 404면 CDX로 디렉터리를 나열하라, 2019년 사본이 없으면 가장 이른 archive 시간표를 써라. 하지만 IA 장애와 데이터 변화가 결과를 지배했음.
- **a7feb290:** A-equivalent의 실패는 대부분 세는 과정의 실행 문제임. "현재 기록도 증거로 인정하고 숫자를 내라, 위치를 나눠 세라"는 도울 수 있음. 반대로 "당시 기준"을 요구하는 instruction은 확실히 해로웠음(§3.6).
- **676e5e31:** 실패 지점이 d0에서 3–8 delegation 뒤였음. d0에서 날짜 기준(1959년 이후 효력이 생긴 issue, revision, amendment를 셈)을 정해 두면 후속 기준을 묶어 둘 수 있었을지 모름. 확신은 낮음.
- **8131e2c0:** "단위 없이, 반올림 없이"는 task에서 나오지만 그것만으로는 부족함. 저장값을 보려면 spreadsheet export가 반올림한다는 것을 알아야 하고, 출처가 spreadsheet라는 것은 실행 중에야 알게 됐음.

### 3.5 막을 수 없는 14개
- **채점과 gold 4개(708b99c5, 366e2f2b, ded28325, 72c06643):** 모든 run이 내용상 맞거나 물리적으로 맞는 답을 냈음.
  - 366e2f2b는 scorer가 curly apostrophe를 ASCII로 바꾸면 통과함.
  - 708b99c5는 의미가 같은 답을 인정하지 않는 것임.
- **출처 데이터 변화 2개(bec74516, 384d0dd8):** 지금 데이터로는 gold가 나오지 않음. 16d825ff도 일부 해당함.
- **접근 불가 1개(0b260a57).**
- **실행 6개:** 853c8244(그림 판독)는 체계적인 오류이고, 나머지 5개는 같은 draft가 다른 run에서 맞힌 운의 문제임.
- **orchestrator와 예산 1개(851e570a):** d0에서 찾은 정답을 재검증하다 시간이 끝났음. 효과적인 수정은 d0 밖에 있음.
  - 시간이 다하면 그때까지의 best answer로 끝내기.
  - 남은 시간을 orchestrator에게 알려 주기.
  - 검증이 불가능하면 재검증하지 않기.

### 3.6 refiner가 만든 실패 (instruction을 고치지 않았으면 피했을 실패)
| task | run | 같은 draft의 A | 경로 |
|---|---|---|---|
| cffe0e32 | s4 c3 (r8) | 정답 | "give the result under each possible reading" → 이중 답 |
| 9b54f9d9 | s4 c3 (r8) | 정답 | "only when they denote the same food" + "explain the ambiguity" → "Not uniquely determinable" |
| 56137764 | s4 c2 (r8) | 정답 | draft의 좁힘("credited for that addition")을 유지하고 보류 조항을 더함 → "No matching contributor" |
| 676e5e31 | s4 c2 (r8) | 정답 | "preserve other qualifiers" → 후보 6개 → 100% |
| 9e1fc53b | s4 c2, s4 c3 (r8) | 정답 | 실행 날짜로 "just released"를 판단 + "cannot be derived only if" |
| a7feb290 | s4 c3 (r8) | 정답 | "당시 기준, 현재 페이지 수를 당시 수로 내지 마라" → Unknown |
| 9e1fc53b | rB c2 (r9) | 정답 | 사전 확인과 rewrite가 "no one can use it"을 문자 그대로의 장착 가능 여부로 고정 → Druid |
| a7feb290 | rB c2, rB c3, rBredo c2, rBredo c3 (r9) | A 정답, v7 fresh는 비답변 | "현재 기록에 있다는 이유만으로 세지 마라" → 비답변 4/4 |

- **r9가 한 일:** 보류 조항, 이중 답 요구, 실행 날짜 사용을 없앴음.
- **r9에 남은 것:** 해석을 엄격한 쪽으로 정하는 것이 남았음.
  - 9b54f9d9 rA c3 r1은 엄격한 동일성 기준이 남아, d1 재확인에서 "only unmatched entry … is not [supported]"라는 보고가 나왔음. 정답으로 끝난 것은 orchestrator가 finish에서 그 보고를 넘어갔기 때문임.
- **cffe0e32 r9 run의 실패(rA c3 r0, rB c2, rB c3)는 주로 orchestrator의 재확인과 finish에서 생겼음.** rewrite는 기여 요인이었음.
  - v6 draft에서는 worker가 표 방향 문제를 꺼낸 적이 없음(6 run).
  - v7 draft에서는 4/4가 꺼냈음.
  - draft 문구가 영향을 준 것으로 보임(표본 작음).

### 3.7 상한 추정
- **stage 4 A(33/47)에서 instruction을 고쳐 늘릴 수 있는 정답은 많아야 2–4개임.** 2dfc4c37과 50f58759는 근거가 강하고, c526d8d6과 16d825ff는 불확실함.
- 4b6bb5f7과 8131e2c0은 A가 이번에 맞혔거나 오염으로 맞혔음. 다른 rep에서는 instruction 수정이 안정성을 높일 수 있음.
- **A의 오답 14개 중 나머지 10개의 원인**
  - 4개는 채점·gold 문제.
  - 3개는 데이터 변화와 접근 불가.
  - 3개는 실행 문제.
- **refiner(r8, r9)가 이 여지를 실제로 쓴 사례는 없음.** 같은 checkpoint에서 refiner가 이 실패들을 고친 run이 하나도 없었음.

## 4. 부수 발견
### 4.1 Wayback snapshot 날짜 표기 버그 (tool)
- **증상:** worker가 `https://web.archive.org/web/20190527000000/<url>` 같은 URL을 직접 읽으면 다음 일이 일어남.
  - `_read`가 `…/web/20190527000000id_/<url>`로 요청하고, Wayback은 가장 가까운 capture로 redirect함.
  - 그런데 `doc_header`는 요청 URL의 날짜로 "Archived snapshot … taken on 2019-05-27"이라고 표기함(`src/minpilot/tools/web.py` `_read`의 `final = url if fetch_url != url else page.url`, `doc_header`의 `_snapshot_date(doc["url"])`).
- **16d825ff에 준 영향**
  - v6 fresh와 s4 c3는 2021-11-23 capture를 받았는데 "2019-05-27"로 표기됐음. subagent에 따르면 내용 hash가 2021 capture와 같음.
  - 두 run은 이것을 2019년 시간표로 믿고 6:41 PM을 냈음. 정답과 같았지만 우연이었음.
- **a7feb290에 준 영향:** 2024–26년 capture가 2020년 날짜로 표기돼, 현대 목록의 [ps] 부재가 2020년 상태로 오해됐음.
- **고치지 않았음.** 제안: 실제 redirect된 URL의 timestamp를 header에 쓰고, 요청한 날짜와 다르면 둘 다 표시하기.

### 4.2 OWL 논문 오염
- **노출된 것:** arXiv 2505.23885(OWL)와 OpenReview MBJ46gd1CT가 GAIA 질문과 annotator 풀이 단계를 담고 있어 Serper 결과에 나왔음.
- **정답까지 노출된 run:** 8131e2c0 s4 A 하나임. snippet에 "Answer: 101.376, 84.348. Annotation steps …"가 나왔고, worker는 이 숫자로 검색한 뒤 XLSX를 확인해 맞혔음.
- **풀이 경로 힌트만 노출된 run:** c3a79cfe, c8b7e059, 3da89939, 872bfbb1(IAGENT 논문 포함).
- **audit의 분류:** stage 4 contamination.json은 8131e2c0의 노출을 "quotes_task_question_window (audit only)"로만 분류했음. 이전 report §5에서 저는 이 분류를 대부분 휴리스틱이라고 넘겼음.
- **blocklist v6에는 이 논문들이 없음.** 추가 후보:
  - OWL arXiv 2505.23885와 OpenReview MBJ46gd1CT
  - IAGENT(OpenReview)
  - AOrchestra arXiv 2602.03786(853c8244에서 발견, 접근은 막혔음)
  - 이전 후보 3개

### 4.3 gold와 출처 데이터
| task | 문제 |
|---|---|
| 72c06643 | gold가 약 1072 atm, 4°C의 Freon-12(압축 액체)에 이상기체 식을 씀. run들의 약 193 mL가 물리적으로 맞음 |
| bec74516 | ORCID 작품 수가 gold 이후 늘었음. annotator 풀이는 "pre-2022"로 셌지만 질문은 pre-2020 |
| 384d0dd8 | 지금의 PubChem gene-chemical 목록으로는 4192가 나오지 않음 |
| 16d825ff | Tri-Rail 현재 시간표는 6:12 PM. 2019년 archive가 없음 |
| ded28325 | gold 오타 "Ploybius" |
| 708b99c5, 366e2f2b | 채점 정규화("Citation count", curly apostrophe) |

GAIA validation의 일부 task는 지금 시점에 실행하면 정답에 닿을 수 없음. 이런 task가 arm 간 비교에 noise를 더함.

### 4.4 orchestrator 정책과 tool
- **재확인 뒤 finish (cffe0e32, 676e5e31, 851e570a, a7feb290)**
  - 맞는 중간 결과를 얻은 뒤 재확인을 맡기고, 그 보고의 기울기에 따라 비답변, 반대 해석, hedge로 끝나는 경로가 반복됐음.
  - A에서도 생김(rBfresh a7feb290, 851e570a).
- **page reader의 이중 집계 (bec74516):** 긴 ORCID XML을 reader가 두 부분으로 나눠 답했고, worker가 두 부분을 더해 113이 됐음(실제 103).
- **run_python에 network가 없음 (851e570a):** 사전 전체 검색이 불가능한데 instruction이 "exhaustive" 확인을 요구했음.

### 4.5 이전 report의 정정
| 이전 서술 | 정정 |
|---|---|
| 8131e2c0: "A는 101.376으로 맞혔음", "시키지 않은 반올림을 한 모델 출력 문제" (stage34 §9) | A의 정답은 OWL snippet의 정답 노출에서 시작됐음. 다른 run의 101.38은 모델이 반올림한 것이 아니라 CSV export가 표시 반올림 값을 준 것(X-READ) |
| stage 4 §5: "audit only"는 대부분 휴리스틱 | 그 분류 안에 정답 노출(8131e2c0)이 있었음 |
| cffe0e32 phase B: "확인 보고는 모두 '방향 불명확'" (r9v7 §7.1) | 보고마다 기울기가 달랐음(fresh와 A는 "Fred가 조건부 답", c2 중립, c3 Micah 쪽). 최종 답은 그 기울기를 따랐음 |
| 9b54f9d9: r9로 "고쳐짐" (r9v7 §6) | 보류 조항은 사라졌지만, rA c3 r1에 엄격한 동일성 기준이 남아 r8의 추론이 다시 나왔음. finish에서 구제됨 |
| 56137764 s4 c2: "이름 일치 규칙 강화는 부차적" | 그 rewrite는 이름 일치 규칙을 오히려 완화했음. "Li Peng은 목록에 있지만 PR 작성자는 dkurt"라는 보고는 A run에도 나왔음. 갈린 곳은 rewrite가 좁힘을 유지하고 orchestrator가 이를 "revised criteria"로 따른 것 |
| 9e1fc53b s4 c2: rewrite 때문에 오답 | 직접 원인은 d1 worker가 DK 대신 Warrior를 고르고 Hunter의 Frost Trap을 ice로 친 추론 오류. 날짜 rewrite는 기여 요인 |
| 16d825ff c3 정답: "끈질기게 찾아서" (stage34 §4.3) | 끈질긴 탐색에 더해 Wayback 표기 버그로 2021 capture를 2019 것으로 믿은 덕분 |

## 5. 해석 (결정은 하지 않음)
- **이 50개 task에서 d0 instruction 수정의 여지는 원래 작음.**
  - A의 오답 대부분은 채점·gold, 데이터 변화, 실행 문제였음.
  - instruction이 원인인 것은 2–3개, 가능성 있는 것까지 합쳐 최대 7–8개 task임.
- **그 작은 여지조차 refiner는 잡지 못했음.** 이유는 세 가지임.
  - draft의 잘못된 읽기를 probe 응답자도 같이 따르면, 비교로는 드러나지 않음(2dfc4c37).
  - probe에 맞는 신호가 있어도 analysis가 버림(4b6bb5f7, c526d8d6).
  - analysis가 task가 말하지 않는 지점을 엄격한 쪽으로 정함(50f58759, a7feb290).
- **probe 질문 자체보다 analysis의 판단 기준이 문제임.** 지금의 analysis는 다음과 같이 움직임.
  - draft에 적히지 않은 선택은 issue로 삼음.
  - 위험은 확인 관문으로 바꿈.
  - task가 침묵하는 곳은 엄격하게 정함.
  - 반면 "draft가 task의 출처나 대상을 바꿨는가"(2dfc4c37, 50f58759)는 놓쳤음.
  - r9에서 맞는 지적의 절반이 probe 답이 아니라 draft와 task를 직접 비교해서 나왔다는 점도, 비교 단계가 더 중요하다는 쪽을 가리킴.
- **orchestrator 공통 정책이 결과에 큰 영향을 줌.** 재확인 뒤의 finish, 예산이 다했을 때의 답, rewrite를 권위로 받는 태도가 그것임. 이것들은 refiner와 별개로 A에도 영향을 줌.

## 6. 확인 실험 제안 (실행하지 않음, 결정은 사용자)
§3의 "막을 수 있었다"는 판단은 같은 v6 checkpoint에서 d0 instruction만 바꿔 보내면 확인할 수 있음.
- override restore가 작동하는 것은 확인해 두었음. 시험 run 1개, $0.001. v7 코드는 v6 checkpoint를 거부하므로 v6 코드 사본(`dc893bd`)으로 돌림.

| task | arm (각 3 rep) | 예상 비용 | 예상 Serper credit |
|---|---|---|---|
| 2dfc4c37 | 수정 instruction, task를 그대로 풀라는 instruction | ≈ $0.1 | ≈ 30 |
| 50f58759 | 수정 instruction, task를 그대로 풀라는 instruction | ≈ $0.6 | ≈ 250 |
| 4b6bb5f7 | 수정 instruction, A | ≈ $0.05 | ≈ 15 |
| c526d8d6 | 수정 instruction, task를 그대로 풀라는 instruction | ≈ $0.3 | ≈ 120 |
| (선택) 16d825ff, a7feb290, 676e5e31 | 수정 instruction | ≈ $1.1 | ≈ 630 |

- **arm의 뜻**
  - "task를 그대로 풀라는 instruction"은 draft의 이탈만 없앤 효과를 봄.
  - "수정 instruction"은 task 문장에서 끌어낸 정의와 방법을 더한 효과를 봄.
- **수정 instruction 원문:** 각 analysis 파일의 `task_level.counterfactual_instruction`에 있음.
  - gold를 아는 상태에서 쓴 것이라 해석이 gold 쪽으로 기울어 있음. 예: 2dfc4c37의 한 목록 읽기, 50f58759의 "합계 하나", 676e5e31의 "amendment를 셈".
  - 그래서 이 실험은 "올바른 수정이 있었다면"의 상한을 재는 것이고, "refiner가 찾을 수 있었는가"를 재는 것은 아님.
- **합계:** 핵심 4개만 하면 약 $1.1, 약 420 credit. 선택까지 하면 약 $2.2, 약 1,050 credit. stage 4의 task별 run당 비용과 credit으로 추정했음. cache 적중이 있으면 credit은 더 적음.
  - 지금 남은 것: 약 $28(상한 $50 기준), Serper key 3에 2,380.

## 7. 제가 정한 것
- **"각 질문"을 probe가 묻는 네 항목(understanding, choices, risks, plan)과 tool 확인으로 해석했음.** 각 GAIA 질문에서 무슨 일이 있었는지는 §3.2 표와 task별 분석 파일에 있음.
- **분석 범위:** 실패가 한 번이라도 있었던 26개 task는 run 전체를, 22개 정답 task는 refiner 기록만 봤음. stage 1–2(r5–r7)는 포함하지 않았음.
- **분석 방식:** subagent 9개, 공통 기준(`RUBRIC.md`), 원인 코드와 4단계 수정 가능성 정의를 제가 정했음.
- **확인 실험(override restore)은 준비만 하고 돌리지 않았음.**
  - 사용자 지시("API call은 내가 말하지 않는 한 시작하지 마")에 따름. 시험 run 1개($0.001, 검색 없음)는 지시 전에 돌렸음.
  - 준비물: v6 코드 사본(`scratchpad/v6code`, git archive `dc893bd`)과 launcher(`scratchpad/cf_launch.py`).
- **issue 출처 집계:** subagent가 자유 형식으로 적은 출처에서 처음 나오는 항목을 주 출처로 정했음.
- **A-equivalent 정의:** fresh, A restore, no_issues refiner run을 포함했음. 8131e2c0의 오염된 정답은 성공에서 뺐음.
- **Wayback 버그와 blocklist는 고치지 않았음.** 제안만 함.
- **subagent의 판단을 일부 조정했음.**
  - 2dfc4c37은 high로 두되, task 문장이 한 가지 읽기만 허락하는 것은 아니라는 단서를 붙였음.
  - 676e5e31은 YES-TASKTEXT(low)를 그대로 두었음.
- **이전 report에 정정 표시는 하지 않았음.** 이 report의 §4.5가 정정 기록임.

## 8. 파일
2026-10-11 정리 이후 위치입니다.
- `docs/reports/cases/analysis/<task>.md`: task별 분석. 실행 경로, 실패 지점과 transcript 줄 번호, 원인, 수정 가능성, refiner 기록, JSON 요약.
- `docs/reports/cases/analysis/_allcorrect.md`: 정답 22개 task의 refiner 기록 44개 분석.
- `docs/reports/cases/RUBRIC.md`: 분석 기준.
- `outputs/analysis/2026-10-10-case-analysis/cards/<task>.md`: 질문, gold, annotator 풀이 단계, run 목록.
- `outputs/analysis/2026-10-10-case-analysis/agg_runs.csv`: run별 원인과 수정 가능성.
- `outputs/analysis/2026-10-10-case-analysis/agg_issues.csv`: issue별 출처, decision, 품질.
- `scripts/aggregate_case_analysis.py`: 집계 스크립트(당시 `aggregate.py`).
- transcript는 크기 때문에 넣지 않았음(scratchpad `deep/tr/`, 49 MB). `scripts/render_trace.py RUN_DIR`로 다시 만들 수 있음.
