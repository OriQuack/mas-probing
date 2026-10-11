> 과거 실험 보고서입니다. 해석·수치의 정정은 [최신 종합 보고서](2026-10-10-synthesis.ko.md)를 우선하세요.

# Stage 3–4 report (2026-10-09)

코드: commit `438339a` (prompts v6, refiner r8), `a254fcd` (Serper credit을 key별로 세기, K18). 둘 다 local commit이고 push 안 함.
이 report와 STATUS는 gitignored (`outputs/sessions/`).

## 요약
- **3단계 (v5 → v6, 50 tasks × 1, 검색은 DDG로 degraded)**
  - 정답 32 → 35. 바뀐 task는 3:0으로 v6 쪽이고 p = 0.25라 **v6가 낫다고는 말할 수 없음.** 나빠지지 않았다는 데까지만 말할 수 있음.
  - check성 후속 delegation은 66 → 45, "Unknown"류 답은 4 → 2로 줄었음.
- **4단계 (v6 d0 checkpoint 47개, Serper, 1 rep)**: A_none **33**, c2_probe_tools **29**, c3_probe_multi **28** /47.
  - 짝지은 비교: A vs c2는 6:2 (p = 0.29), A vs c3는 8:3 (p = 0.23). 통계적으로는 noise 범위.
  - 그런데 trace를 보면 **refiner가 답을 바꾼 방향이 일관됨.** A가 맞힌 task 5개에서 refiner의 rewrite가 답을 "Cannot be determined", "Ambiguous: Fred if …", "No matching contributor" 같은 비답변으로 바꿨음. 기준을 좁혀서 틀린 경우도 2개 더 있음.
  - **refiner 덕분에 맞았다고 볼 수 있는 case는 하나도 없었음.**
- **Noise**: refiner가 draft를 그대로 둔 run(즉 A와 같은 처리)도 A와 10/58 task에서 결과가 다름(17%). 1 rep으로 4–8 task 차이는 구별할 수 없음.
- **비교의 기준점**:
  - Serper로 restore한 A(33/47)와 DDG로 돌린 v6 baseline(33/47)의 정답 수가 같음. 다른 task는 2:2.
  - 검색 backend 차이가 결과 합계에는 영향이 없었음.
- **비용**
  - 오늘 밤 합계 **$17.1** (상한 $50). 내역: v5 $4.52, v6 $3.91, 중단한 DDG stage 4 $0.23, smoke $0.05, Serper stage 4 $8.41.
  - Serper는 stage 4에서 약 3,280 credit을 썼음.
  - **남은 Serper credit**: key 2 1,671, key 3 2,500 (key 1은 reserve 50만 남음).

## 1. Serper 사건 경과
1. stage1-rep1 후반에 Serper credit이 바닥났음(잔액 50 = reserve).
   - 그 뒤 v5와 v6 baseline은 둘 다 DDG fallback으로만 돌았음.
   - web_search 약 46%가 실패했음(startpage "connection refused", "No results").
   - tools는 바꾸지 않고 두 version을 같은 조건으로 비교했음.
2. 19:10 UTC에 DDG 조건으로 stage 4(`stage4-20261009T191048Z`)를 시작했음.
3. 19:20에 사용자가 Serper를 충전했음(새 key).
   - DDG stage 4는 13 run에서 멈췄고 쓰지 않음(`ABORTED.txt`).
   - 이전 cache는 `outputs/cache/tools_v4_ddg-period_until20261009T1925Z.sqlite`로 옮겼고 새 cache로 시작했음.
4. 19:26에 Serper stage 4를 1 rep으로 다시 시작했음(`stage4-serper-20261009T192620Z`).
5. 19:3x에 사용자가 상한을 정했음: 비용 $50, Serper credit이 100 남으면 새 run을 시작하지 않음.
   - background guard가 매분 잔액을 확인했음.
6. 19:39에 K18을 넣었음: credit을 key별로 셈. 이게 없으면 key를 바꿔도 이전 key의 소진 기록이 남아서 DDG로 fallback함.
   - 사용자가 `SERPER_API_KEY2`와 `SERPER_API_KEY3`를 추가했음.
7. 20:08에 key 1 잔액이 105가 되어 guard가 `SERPER_API_KEY` 값을 key 2로 바꿨음.
   - 원래 key 1 값은 `SERPER_API_KEY1`로 남겨 두었음.
   - **지금 `.env`의 `SERPER_API_KEY`에는 key 2 값이 들어 있음.**
8. 20:58에 141 run이 모두 끝났음(전부 status ok). 100 credit 규칙으로 멈춘 일은 없음.

## 2. 3단계: 공통 prompt v5 → v6
세션:
- v5: `stage3-v5-base-20261009T160339Z` (commit a25fcf9 코드)
- v6: `stage3-v6-base-20261009T173855Z` (commit 438339a)

둘 다 `baseline_v1` 50 tasks, pool `multi`, `A_none`, 1 rep, checkpoint 저장, run 예산 $5 / 3600 s, 검색은 DDG로 degraded.

| | v5 | v6 |
|---|---|---|
| 정답 | **32/50** | **35/50** |
| L1 / L2 / L3 | 7/8, 17/25, 8/17 | 7/8, 19/25, 9/17 |
| 총 비용 | $4.52 (851e570a 혼자 $2.55) | $3.91 (851e570a가 다시 runaway, $1.99) |
| run당 비용 (851e570a 제외, 평균 / 중앙값) | $0.040 / $0.012 | $0.039 / $0.015 |
| delegation 평균 (중앙값) | 2.60 (1) | 2.34 (1) |
| delegation ≥ 5인 run | 9 | 8 |
| 후속 delegation / 그중 check 단어 포함 (regex) | 81 / 66 | 69 / 45 |
| 비답변 ("Unknown", "Unable to determine" 등) | 4 | 2 |
| 보고서에 정답이 나왔는데 최종 답이 틀림 (fofw) | 3 | 3 (같은 task들) |

- **짝지은 비교**: 둘 다 정답 32, v6만 정답 3 (16d825ff, 676e5e31, a7feb290), v5만 정답 0, 둘 다 오답 15.
- **v6 보고서 형식**: 117개 보고서 중 `Interpretation` 섹션이 있는 것이 87개(74%), `Assumptions`는 0개. 형식은 대체로 지켜졌음.
- **v6를 만든 계기였던 두 case** (cffe0e32 "Fred or Micah", 9b54f9d9 "Not uniquely determinable; likely …"): 이번에는 v5와 v6 모두 정답. A는 원래 이 둘을 대부분 맞힘.
- **둘 다 틀린 15개**
  - 채점이나 형식 문제(4): 366e2f2b (curly apostrophe 하나 때문), 708b99c5 (gold "Citations"), ded28325 (gold 오타 "Ploybius"), 4b6bb5f7. v6의 8131e2c0도 반올림과 단위 문제.
  - runaway(1): 851e570a. 479k단어 사전을 read_url로 읽음.
  - 열거나 검색 실패(5): 0b260a57, 50f58759, 3da89939, 72c06643, 384d0dd8.
  - 계산이나 해석 오류(4): 2dfc4c37, 853c8244, c526d8d6, bec74516.
- **v5의 긴 실패 run들** (bec74516, 0b260a57, 676e5e31, a7feb290, 16d825ff)
  - worker가 열거나 검색에서 tool 20회 상한에 걸림.
  - orchestrator는 task를 나누지 않고 같은 넓은 task를 "one final attempt"로 6–12번 다시 맡김.

## 3. 4단계 결과 (Serper, 1 rep)
`stage4-serper-20261009T192620Z`
- **구성**: v6 baseline의 d0 checkpoint 47개 × {A_none, c2_probe_tools, c3_probe_multi}. condition 순서는 checkpoint마다 돌아가며 바꿈.
- **제외한 task 3개**: 42576abe와 6f37996b는 delegation이 없어서 checkpoint가 없음. 851e570a는 v6 baseline 비용이 $1.99여서 뺐음(제가 정한 것 참고).

| arm | 정답 | L1 / L2 / L3 | 비답변 | usd/run (평균 / 중앙값) | issue (run 수) | rewrite된 run | context_additions |
|---|---|---|---|---|---|---|---|
| A_none | **33/47** | 6/6, 17/25, 10/16 | 3 | 0.058 / 0.024 | – | – | – |
| c2_probe_tools | **29/47** | 6/6, 16/25, 7/16 | 4 | 0.054 / 0.031 | 12 (11) | 11 | 3 |
| c3_probe_multi | **28/47** | 4/6, 16/25, 8/16 | 8 | 0.067 / 0.039 | 36 (25) | 25 | 9 |

### task별 결과 pattern
(A, c2, c3 순서. 1 = 정답)

| pattern | task 수 | 해당 task |
|---|---|---|
| 111 | 22 | |
| 000 | 11 | |
| 110 (c3만 틀림) | 5 | 4b6bb5f7, 6b078778, 9b54f9d9, cffe0e32, f3917a3d |
| 101 (c2만 틀림) | 3 | 56137764, 676e5e31, 872bfbb1 |
| 100 (A만 맞음) | 3 | 8131e2c0, 9e1fc53b, a7feb290 |
| 011 | 2 | 3da89939, 65638e28 |
| 001 | 1 | 16d825ff |

### Noise와 실제 효과 구분하기
refine 결과가 `no_issues`면 draft가 그대로 나가고 orchestrator의 대화도 그대로임(R22). 그래서 그런 run은 A와 같은 처리로 봄.

| | run 수 | A만 정답 | arm만 정답 |
|---|---|---|---|
| c2, draft 그대로 | 36 | 3 | 2 |
| c3, draft 그대로 | 22 | 4 | 1 |
| c2, rewrite됨 | 11 | **3** | 0 |
| c3, rewrite됨 | 25 | **4** | 2 |

- draft가 그대로인데도 A와 결과가 다른 경우는 10/58이었음.
  - 원인은 형식("INT. THE CASTLE - DAY"), 오타("Visconte"), 반올림("101.38"), 값 하나 차이(2731), 목록 차이였음.
  - 이게 바로 run 간 noise.
- rewrite된 run에서 결과가 다른 경우만 보면 7:2로 A가 많음(p = 0.18). 이것만으로는 결론을 낼 수 없음.
- 다만 **비답변 비율**은 차이가 뚜렷함.

| | 비답변 비율 |
|---|---|
| c3, rewrite됨 | **8/25** |
| c3, draft 그대로 | 0/22 |
| c2, rewrite됨 | 2/11 |
| c2, draft 그대로 | 2/36 |
| A | 3/47 |

## 4. trace 직접 비교
### 4.1 probe가 본 모호함이 답으로 번짐 (c3, 3건 모두 A는 정답)
- **cffe0e32**: A와 c2는 "Fred"(delegation 1번, $0.0015). c3는 "Ambiguous: Fred if Giftee is giver; Micah if Recipient is giver."
  1. respondent 1(haiku)이 "표 header가 Giftee / Recipient로 모순돼 Fred 또는 Micah"라고 보고함.
  2. analysis가 이를 `defer_to_execution`으로 받아들임.
  3. rewrite가 "column 방향이 문서에서 풀리지 않으면 어떤 모호함인지 말하고 **각 읽기에 따른 결과를 내라**"를 추가함.
  4. `context_additions`도 같은 모호함을 그대로 전달함.
  5. worker가 두 읽기를 모두 보고함.
  6. orchestrator가 re-check를 맡겼고 같은 결과가 나왔음.
  7. 최종 답이 양쪽 다 적은 답이 됨.
  - stage 1의 pattern B와 같은 결과인데, 이번엔 orchestrator의 re-check가 아니라 **refiner가 들여옴.**
- **9b54f9d9**: A와 c2는 "Soups and Stews". c3는 "Not uniquely determinable".
  1. respondent 2가 "짝짓기 몇 개는 판단의 문제"라고 보고함.
  2. rewrite가 "같은 음식일 때만 짝지어라. 비슷하다는 이유로 짝짓지 마라", "정확히 하나가 남는다고 증거가 뒷받침하지 않으면 모호함을 설명하라"를 추가함.
  3. worker가 이 엄격한 기준에서 clam/geoduck, pumpkin/squash 등도 짝이 아니라고 봄.
  4. orchestrator가 감사(audit)를 다시 맡김.
  5. 최종 답이 "Not uniquely determinable"이 됨.
  - stage 1의 pattern A(r7)가 r8에서도 그대로 재현됨.
- **9e1fc53b (WoW)**: A는 정답 "Death Knight, Hunter, Paladin, Priest, Warlock". c3는 "Cannot be determined", c2는 Warrior가 들어간 오답.
  - rewrite가 "**run reference date** 기준으로 새로 나온 dungeon을 정하고, 정확한 item version으로 'no one can use it'을 판정하라"를 추가함.
  - c3는 item 판정을 엄격하게 했음. "Hunter가 leather Kilt를 장착할 수 있다", "날짜상 새 dungeon에는 Kilt가 안 나온다"는 이유로 단서들이 서로 모순이라고 결론냄.
  - A는 그 단서를 "의도된 의미의 use"로 느슨하게 읽어서 맞힘.
  - 'run reference date'는 GAIA 문제가 만들어진 시점이 아니라 지금 날짜를 가리킴. 그래서 이 지시 자체가 잘못된 방향일 수 있음.

### 4.2 기준을 좁혀서 틀림 (A는 정답)
- **56137764 (c2)**: 정답 "Li Peng". c2는 "No matching contributor".
  - rewrite가 이름 일치 규칙을 엄격하게 하고 "증거가 일치를 확립하지 못하면 무엇이 빠졌는지 설명하라"를 추가함.
  - draft에 원래 있던 "credited for that addition"(그 기능을 추가한 사람)이 이 엄격함과 합쳐졌음. 그래서 worker가 "Li Peng은 4.0.0 기여자 목록에는 있지만 Mask-RCNN PR 작성자는 dkurt"라고 보고함.
  - orchestrator가 "일치하는 기여자 없음"으로 결론냄.
  - c3도 같은 clarify를 받았지만 정답이었음.
- **a7feb290 (c3)**: 정답 31. c3는 "Unknown".
  - rewrite가 "January 2020 **당시** PostScript가 있었는지를 archive로 확인하고, 그게 안 되면 현재 페이지로 센 수를 당시 수로 내지 마라"를 추가함.
  - worker 3명이 모두 Wayback으로 확인하는 데 실패했고 답은 "Unknown"이 됨.
  - A는 delegation 8번 끝에 31을 냈음.
- **676e5e31 (c2)**: 정답 86. c2는 "100%".
  - clarify("이름의 다른 수식어는 보존하라")가 후보 집합을 7개에서 6개로 줄였음. 그래서 6/6이 됨.
  - A는 7개 중 6개 = 86으로 맞힘.

### 4.3 refiner arm만 맞힌 task: refiner 때문이 아님
- **3da89939** (c2, c3 정답): c2는 draft가 그대로였음 → noise. A의 답 "8,29,unknown,1,8,26"은 한 칸만 찾지 못했음.
- **65638e28** (c2, c3 정답): 두 arm 모두 draft가 그대로였음 → noise.
- **16d825ff** (c3만 정답, "6:41 PM"): rewrite가 per-train passenger 정의를 지정함.
  - 정답은 delegation 8번 중 7번째에 archive PDF를 찾아서 나왔음. 끈질기게 찾아서 맞힌 것.
  - A와 c2도 delegation을 12번 했지만 찾지 못했음.

- 16d825ff와 3da89939 추가 확인(10-10)
  - **16d825ff**: rewrite가 "May 27, 2019는 Memorial Day이니 holiday schedule을 확인하라"를 추가했음. 그런데 A도 P685와 holiday schedule까지는 스스로 찾았음.
    - A는 현재 시간표(6:12 PM)만 찾았고 2019년 archive 시간표는 찾지 못했음. 갈린 지점은 이것임.
    - refiner 없는 v6 baseline도 holiday schedule을 스스로 찾아서 6:41 PM을 맞혔음.
  - **3da89939**: 세 arm 모두 cell 3에서 막혔음. 결국 draft를 그대로 쓴 c2와 c3가 나중 delegation에서 Semma(ref 22)를 찾았음.

### 4.4 결과는 바꾸지 않았지만 맞는 지적
rewrite 36개 중 내용상 맞는 지적은 아래와 같음. 모두 A도 실행 중에 스스로 처리해서 정답이었음.
- **4d51c4bf c2**: draft의 "run reference date 2026-10-09 기준 최근 90일" filter를 없앴음. task 전제와 충돌하는 filter였음.
- **bda648d7 c3**: St. Petersburg를 Saint Petersburg로 풀어 쓰게 함.
- **dd3c7503 c3**: 1 gallon = 16 cups를 명시함.
- **d5141ca5 c3**: template(navbox)의 수정 기록도 확인하게 함.
- **32102e3e c2/c3**: "oldest"를 `Year` column 기준으로 정함.
- **676e5e31 c3**: 대체 version 없이 폐지된 것은 superseded로 세지 않게 함.

반대로 384d0dd8 c3는 "records as of 2026-10-09"를 **새로 넣었음**. 같은 종류의 'run reference date' 지시가 4d51c4bf에서는 refiner가 빼서 도움이 됐고, 384d0dd8에서는 refiner가 넣었음. A는 384d0dd8을 어차피 틀렸음.

### 4.5 refiner 내부
- **`needs_verification`이 0이라 사전 check가 한 번도 실행되지 않았음.** stage 1–2와 같음.
- **decision 분포**: c2는 clarify 9 / defer_to_execution 3. c3는 defer_to_execution 19 / clarify 17.
- **c3에서 issue가 많은 이유는 haiku의 응답인 것으로 보임.**
  - issue evidence가 인용한 respondent: haiku만 5, 둘 다 10, luna만 0, 확인 안 됨 21.
  - haiku가 respondent 1일 때 rewrite 17/28(61%), luna가 1일 때 8/19(42%). 표본이 작음.
- **비답변 조항이 따라 들어옴**
  - 36개 rewrite 중 17개가 "어떤 모호함인지 설명하라", "도출할 수 없다고 보고하라" 같은 조건부 조항을 새로 넣었음(regex 기준).
  - 이 17개 중 7개가 비답변으로 끝남. 조항이 없는 rewrite 19개 중에서는 3개.
  - rewrite 규칙 "Report that the result cannot be derived only when a specific missing or conflicting piece of evidence prevents …"가 **instruction 안의 조건부 조항으로 거의 그대로 옮겨짐.**
    - 56137764: "If the evidence does not establish a match, explain the specific missing or conflicting evidence"
    - 9e1fc53b: "state that it cannot be derived only if specific evidence needed to decide is missing or conflicting"
  - 비답변을 막으려고 넣은 규칙이 오히려 비답변을 만드는 조항이 되었음. stage 1(r7)의 9b54f9d9에서 본 "규칙 4가 instruction으로 복사됨"과 같은 현상.
- **context_additions** (c2 3건, c3 9건): 대부분 respondent의 검증 안 된 관찰을 "not verified"라고 표시해서 전달한 것. cffe0e32에서는 이게 모호함을 worker에게 그대로 넘겨줬음.

## 5. 검색과 contamination
- **검색**
  - stage 4 web_search 3,465회 중 Serper 3,424회(98.8%), DDG 19회, 실패 22회. cache hit는 141회(새 cache라 적음).
  - Serper가 아닌 검색은 run 8개에 몰려 있음. 20:04–20:10 사이, key 1이 reserve까지 내려가 진행 중이던 run들이 fallback한 때임.
  - 이 중 결과가 갈린 run은 872bfbb1 c2(오답, 실패 1회) 정도. A 872bfbb1은 DDG 4회와 실패 4회가 있었지만 정답이었음.
- **Contamination** (`contamination.json`, blocklist v6; 141 run 중 32 run에 플래그)
  - 대부분은 "quotes_task_question_window (audit only)"(145건)로, audit 전용 휴리스틱임.
  - 휴리스틱이 아닌 노출은 11건이고 모두 검색 결과 snippet.
    - 5b2a14e8: 논문 "Towards Efficient Runtime Multi-Agent Systems". 세 arm 모두에서 나옴.
    - dd3c7503: arXiv 2601.18467 "OffSeeker"가 문제 문장을 인용. c2와 c3에서 나옴.
    - 16d825ff A: spam site.
    - 50f58759 c3, 56137764 A: 같은 결과 목록에 agent 논문이 섞여 있었음.
  - 노출은 arm 사이에 대칭이고 결과가 갈린 원인이 아님. 위 두 논문은 blocklist 후보.
- **audit script 버그 수정**: `audit_contamination.py`가 `messages.jsonl`을 `splitlines()`로 읽어서 문자열 안의 U+2028에서 줄이 끊겼음. `split("\n")`으로 고쳤음(제가 정한 것).

## 6. 해석 (결정은 하지 않음)
- **d0의 refiner는 이 task들에서 이득을 낼 여지가 거의 없음**
  - d0 draft가 곧 task 전체임(delegation 중앙값 1).
  - A의 executor는 실행하면서 스스로 확인함.
  - 그래서 refiner가 할 수 있는 일은 해석이나 증거 기준을 바꾸는 것뿐임. 이번 데이터에서 그 변화는 대부분 기준을 더 엄격하게 만들거나 모호함을 드러내는 쪽이었고, 그게 비답변으로 이어졌음.
- **c3(이질적 respondent 2명)는 issue를 3배 만들고 rewrite를 2배 함.** 늘어난 부분은 haiku가 보고한 모호함에서 옴.
- **1 rep의 한계**: 1 rep에서 run 간 noise가 17%라 정답 수 차이만으로는 결론을 낼 수 없음. 다만 trace에서 본 기제는 r5와 같은 유형(증거 기준 강화와 비답변 분기)이고 반복적으로 나타남.
- **사용자가 정할 수 있는 후보**(우선순위 순서 아님)
  1. rewrite 규칙에서 "cannot be derived only when …" 문장을 빼거나, "instruction에 조건부 비답변 조항을 넣지 마라"로 바꾸기.
  2. probe가 본 모호함을 `context_additions`로 넘기지 않기. 또는 넘길 때 "정답이 하나 있다고 보고 진행하라"를 함께 쓰기.
  3. c3를 같은 모델 둘로 바꾸기(homogeneous). 예전에 미뤄 둔 결정.
  4. d0 대신 d1 이후에서 refine하기(R3, `refine_at=all`).
  5. 2 rep째 돌리기: 약 $8.4, Serper 약 3,300 credit. 남은 credit은 4,171이라 1회만 가능.

## 7. 제가 정한 것
### 오늘 밤 (사용자가 자는 동안)
- **DDG 기간에 tools를 바꾸지 않았음.** v5와 v6를 같은 조건에서 비교하려고. v6도 같은 degraded 조건으로 돌림.
- **v5를 먼저 돌렸음.** v5 코드로 돌린 다음에 v6로 올렸음.
- **v6 smoke를 scratch copy로 함.** scratchpad의 별도 runs-root에서 c3 restore를 한 번 돌려 r8 로그를 확인했음.
- **r8 구현 세부**
  - shuffle은 `random.SystemRandom`으로.
  - label은 "respondent k".
  - probe가 하나인 condition(c2)도 똑같이 익명으로 처리.
  - c1 예측은 "predicted, sample k"로.
  - r7 config 값은 더 이상 유효하지 않게 함(r6처럼).
  - c3 config는 새로 만들지 않고 그 자리에서 고침.
- **probe tool 상한은 3으로 유지.**
- **분석용 regex는 제가 정했음.** CHECK(후속 delegation이 check인지), HEDGE와 비답변, fofw(보고서에 gold가 나왔는지), 비답변 조항. 정의는 scratchpad `s34_analyze.py`에 있음.
- **"fixable task" 정의**: stage 1–2에서 gold 자체에 문제가 있는 708b99c5와 ded28325를 빼고 셈.
- **stage 4에서 851e570a 제외.** v6 baseline 비용이 $1.99였기 때문(기준: > $1). restore는 checkpoint의 $5 예산을 그대로 쓰므로 run당 상한을 걸 수 없음.

### Serper 이후 (사용자가 깨어 있을 때, 세부는 제가 정함)
- **stage 4 session cap은 $14.** 남은 예산에 여유분을 두고 정했음.
- **parallel은 10.**
- **이전 cache는 지우지 않고 이름을 바꿔서 보관.** `tools_v4_ddg-period_until20261009T1925Z.sqlite`
- **K18 구현**: credit을 key 끝 4자리별로 셈. 테스트 1개 추가.
- **guard**
  - 150 아래면 key 전환(100에서 멈추는 건 사용자 규칙).
  - 전환 순서는 `SERPER_API_KEY2`, `SERPER_API_KEY3`, … 숫자 순.
  - 원래 key 1 값은 `SERPER_API_KEY1` 줄로 복사해 둠.
  - 멈출 때는 run_batch에 signal 15를 보내서 진행 중인 run은 끝나게 함.
- **DDG stage 4 13 run은 쓰지 않음.**
- **19:39 이후 시작한 run은 code_hash가 다름(K18 commit).** tool 동작은 같아서 그대로 섞어서 분석했음.

### 분석
- refine 결과가 `no_issues`인 run을 A와 같은 처리로 보고 noise를 추정했음.
- 비교의 기준점으로 DDG v6 baseline과 Serper A restore를 비교했음.
- `audit_contamination.py` 버그 수정(§5).
- report 파일 이름과 위치(`docs/reports/2026-10-09-baseline-and-probe-comparison.ko.md`).
- 2 rep째는 돌리지 않고 prompt도 바꾸지 않았음. 결과를 보고 사용자가 정할 일이라고 판단했음.

## 8. 남은 일
- §6의 후보 중에서 고르기.
- blocklist 후보: deepwiki AgentRx URL(stage 3에서 발견), "Towards Efficient Runtime Multi-Agent Systems", arXiv 2601.18467.
- v5와 v6 baseline을 Serper로 다시 돌릴지: 약 $8.5, Serper 1,500–2,000 credit. 지금 A restore 33 = v6 DDG 33이라 우선순위는 낮아 보임.
- 채점 문제: curly apostrophe(366e2f2b), 반올림과 단위(8131e2c0), 형식("INT. THE CASTLE - DAY"). orchestrator 답 형식 규칙이나 scorer normalize를 검토할 수 있음.
- 851e570a runaway: read_url reader가 큰 문서를 계속 읽음. reader 호출 상한을 검토할 수 있음.
- `docs/history/decisions-before-cleanup.md`: E9를 1 rep, $50, Serper로 수정했고, K18에 spare key 순서를 반영했음.

## 9. 해석 수정 (10-10, 사용자 검토 반영)
§6과 대화에서 제가 쓴 "전부 prompt 때문", "LLM 능력 문제는 아님", "방법과 GAIA가 근본적으로 맞지 않음"은 증거보다 강한 결론이었음. 아래처럼 고침.

**요약 문장**: 이 구현에서는 잠재적 모호함이 추가 제약과 비답변 조건으로 확대되는 실패가 반복됐다. GAIA의 평가 특성이 이를 불리하게 만들 수 있지만, 올바른 instruction 수정의 이득이 작은지는 아직 확인되지 않았다.

- **prompt의 기여**
  - 근거가 강함: 새로 추가된 지시를 worker가 따랐고, 그것이 최종 오답으로 이어진 경로가 trace에 보임. r8 rule이 instruction에 복사된 것도 확인됨.
  - 다만 7개 모두 prompt만으로 생겼다고 확정할 수는 없음. 같은 checkpoint라도 실행은 결정적이지 않음(draft가 그대로인 run도 17%에서 결과가 달랐음). trace는 작동 경로를 보여 주지만 재현 확률은 보여 주지 않음.
- **사례별 규정** (§4.1–4.2를 바로잡음)

| 사례 | 더 정확한 규정 |
|---|---|
| cffe0e32 (Secret Santa) | 가능한 다른 해석을 채택하고, 복수 답을 요구하는 실행 지시로 확대함 |
| 9b54f9d9 (음식) | 느슨한 대응 관계를 더 엄격한 동일성 기준으로 바꿈 |
| 676e5e31 (USDA) | 자료로 확인하기 전에 후보 집합을 바꾸는 해석을 확정함 |
| 56137764 (OpenCV) | draft가 원 task의 "버전 기여자"를 "기능 구현자"로 좁힌 오류를 refiner(c2)가 바로잡지 못함. 이름 일치 규칙 강화는 부차적임. c3는 이 좁힘을 바로잡아 정답 |
| a7feb290 (arXiv) | 과거 시점 확인 자체는 과한 요구가 아님. 문제는 archive 확인 경로가 실패한 것을 "결과 도출 불가"로 바로 연결한 것 |
| 9e1fc53b (WoW) | 실행 날짜를 "새로 나온 dungeon"의 시간 기준으로 적용함(harness의 날짜 줄) + item version을 엄밀하게 따짐 |

- **GAIA와의 관계**
  - 긴장은 실제로 있음. GAIA 논문도 "논리적 컴퓨터에게는 모호해도 사람에게 모호하지 않은 질문"을 허용함.
  - 다만 이번 결과가 직접 지지하는 것은 "현재 수정 정책이 GAIA에 필요한 통상적인 해석을 보존하지 못했다"까지임. 잘못된 대상, 범위, 조건을 고치는 개입(예: 4d51c4bf, 56137764 c3)은 GAIA에서도 유효할 수 있음.
- **prompt와 LLM 능력**
  - 둘을 완전히 분리할 수 없음. "실행 능력은 있었지만(A 정답) 검토와 수정 단계의 판단이 나빴고, prompt가 그 경향을 강화했다"가 정확함.
  - haiku가 쟁점을 더 많이 제시했다는 관찰만으로 그 모델이 문제를 만들었다고 할 수는 없음.
- **채점상 실패와 근거상 부당한 판단은 다름.** 정정한 분류:
  - 708b99c5 "Citation count" / "Number of citations" vs gold "Citations": gold 오류가 아니라 의미적 동치를 인정하지 않는 채점(공식 scorer는 정규화한 문자열만 비교함).
  - 8131e2c0 "101.38, 84.35": 문제는 반올림을 요구하지 않음(형식: "CFM number for Cheater, CFM number for Cheater beater"). A는 101.376으로 맞혔음. 채점 문제가 아니라 시키지 않은 반올림과 단위 표기를 한 모델 출력 문제.
  - 366e2f2b: curly apostrophe는 채점 정규화 문제. ded28325 "Ploybius"는 gold 표기 문제(그대로).
- **수정 방향** (사용자 피드백, 최소 범위)
  1. 실행 날짜가 질문의 시간 기준이 되지 않게 고침. 공통 harness 문제로 분리 → prompts v7 (F23).
  2. rewrite의 내부 규칙이 instruction에 복사되지 않게 하고, 필요한 작업, 해석, 확인 절차만 고침 → refiner r9 (R24).
  3. probe의 관찰과 해석을 구분함 → r9 analysis.
  4. probe 질문 구성은 유지함.

## 10. 수정 후 주요 trace 재실행 (10-10)
- **코드** (commit, local, push 안 함)
  - `dc893bd` refiner r9 (R24)
  - `894c99d` prompts v7 (F23)
  - `6d63c35` E10 (재실행 범위)
- **trace 묶음**: `outputs/analysis/2026-10-10-followup-traces/` (+ `.zip`, README와 runs.csv 포함)
- **비용**: phase A $2.26, phase B $2.27, a7feb290 재실행 $0.39. 합계 $4.92. 어젯밤부터 누적 약 $22.0 (상한 $50).
- **Serper**: key 2를 다 썼고 key 3 잔액은 2,380.

### 10.1 Phase A: 같은 v6 draft에서 r8 → r9 (2 rep)
| task | stage 4 r8 (A, c2, c3) | r9 rerun (A, c2, c3) |
|---|---|---|
| 56137764 | ✓, ✗, ✓ | ✓✓, ✓✓, ✓✓ |
| 676e5e31 | ✓, ✗, ✓ | ✓✓, ✓✓, ✗✗ |
| 9b54f9d9 | ✓, ✓, ✗ | ✓✓, ✓✓, ✓✓ |
| 9e1fc53b | ✓, ✗, ✗ | ✓✓, ✓✓, ✓✓ |
| cffe0e32 | ✓, ✓, ✗ | ✓✓, ✓✓, ✗✓ |
| a7feb290 | ✓, ✗, ✗ | ✗✗, ✗✗, ✗✗ |
| 4d51c4bf | ✓, ✓, ✓ | ✓✓, ✓✓, ✓✓ |
| 합계 | – | A 12/14, c2 12/14, c3 9/14 |

- **r8 rewrite가 망쳤던 5건**(56137764 c2, 676e5e31 c2, 9b54f9d9 c3, 9e1fc53b c2/c3)은 **2 rep 모두 정답**.
- **r9 rewrite에 결과 보류 조항이 없어짐.** r8은 "explain the specific missing…", "under each possible reading", "do not present a count from current pages" 같은 조항을 넣었음. r9의 조건문은 "확인 못 하면 best-supported result + 확인 못 한 것 명시" 형태임.
  - refiner arm 28 run 중 비답변 0. hedge는 1건("Fred or Micah").
- **draft가 좁힌 대상 복원이 작동함**: 56137764 c2 r0, c3 r1이 "credited for that addition"을 원래 task의 "그 version의 기여자"로 되돌렸음.
- **decision 분포가 바뀜**: r8 c3는 defer 19 / clarify 17이었고, r9 phase A는 clarify 15 / defer 5 / needs_verification 1임.
- **남은 실패**
  - cffe0e32 c3 r0 ("Fred or Micah")
    - 첫 worker 보고는 "Best-supported answer: Fred"였음. orchestrator가 표 방향을 다시 확인하게 했고, 확인 보고가 "문서가 방향을 정하지 않는다"고 하자 hedge로 끝냈음(stage 1 pattern B).
    - 이 run에서는 `context_additions`에 결론("두 읽기 모두 성립")이 섞여 들어갔음(r9 규칙 위반, 1/2). r1은 header 관찰만 넘겼고 정답이었음.
  - 676e5e31 c3 ×2 (57%, 71)
    - 갈린 점은 "amendment도 new version인가"임. A는 개정을 셌고(6/7), c3는 뺐음.
    - r1은 refiner가 draft를 바꾸지 않은 run이라 refiner 탓이 아님. task 해석이 불안정함.
  - a7feb290: A도 rerun 0/2 (30, 26). 숫자를 세는 과정 자체가 불안정해서 판단에서 뺌.

### 10.2 Phase B: v7(날짜 수정) fresh + r9 restore (1 rep)
| task | fresh v7 | A | c2 | c3 |
|---|---|---|---|---|
| 4d51c4bf | ✓ | ✓ | ✓ | ✓ |
| 56137764 | ✓ | ✓ | ✓ | ✓ |
| 676e5e31 | ✗ 71 | ✓ | ✓ | ✓ |
| 9b54f9d9 | ✓ | ✓ | ✓ | ✓ |
| 9e1fc53b | ✓ | ✓ | ✗ (Druid) | ✓ |
| cffe0e32 | ✓ | ✓ | ✗ Cannot be determined | ✗ Micah |
| a7feb290 | ✗ Unable to determine | ✓ 31 | ✗ Unknown (재실행도 ✗ Unknown) | ✗ Cannot be determined (재실행도 ✗ Not determinable) |
| 384d0dd8 | ✗ | ✗ | ✗ | ✗ |

- **날짜 수정은 의도대로 작동함**
  - 4d51c4bf: v7 draft가 "do not use the run date 2026-10-10"이라고 쓰고 90일 filter를 걸지 않았음. c3 rewrite도 filter를 빼고 run date를 쓰지 않았음.
  - 9e1fc53b: draft에 날짜가 없음. c3 rewrite는 "run date로 version을 고르지 마라"라고 썼음.
  - 384d0dd8: 날짜 언급이 없지만 모든 arm이 틀림(다른 원인).
- **Serper 사고**: 06:53–06:57에 시작한 restore 7개가 key 2 reserve에 걸려 검색 일부가 DDG였음(restore 검색의 25%).
  - 원인은 guard의 전환 기준 150이 parallel 10의 무거운 run에는 너무 낮았던 것.
  - 결론에 영향이 있는 a7feb290 c2/c3는 key 3로 다시 돌렸지만 결과가 같았음.
- **남은 실패 경로**: rewrite 문구에서 오는 경로는 사라졌고, 실패가 다른 단계로 옮겨갔음.
  1. **orchestrator re-check → 비답변 또는 반대 해석** (cffe0e32 c2, c3)
     - c2의 rewrite는 목표를 "선물하지 않은 사람"으로 분명히 했을 뿐 방향 얘기는 없었음. c3는 header 관찰만 넘겼음.
     - 첫 보고에서 표 방향이 가정으로 드러나자 orchestrator가 확인을 맡겼음. c2는 "Cannot be determined"로 끝났음. c3는 "Giftee = 받는 사람"으로 읽어 Micah를 택했음.
     - (10-10 정정) A와 fresh도 re-check를 했고 같은 "방향 불명확" 보고를 받았지만, finish에서 task 의도를 근거로 Fred를 택했음. 갈린 곳은 마지막 finish 판단임(`2026-10-10-refiner-diagnostics.ko.md` §7.1).
  2. **해석을 더 엄격한 쪽으로 확정** (a7feb290 c2, c3, 재실행 포함 4/4)
     - resolution이 "PS가 2020년 1월 **당시** 있었는가"로 정하고 "현재 기록에 있다는 이유만으로 세지 마라"를 붙였음.
     - 그 결과 r9의 "best available evidence로 답하라"가 적용될 길이 막혔음. archive 확인이 실패했고 orchestrator가 비답변으로 끝냈음.
     - draft 자체가 "당시인가 현재인가"를 물었고, refiner 없는 fresh v7도 같은 이유로 "Unable to determine"이었음. 같은 draft에서 A restore는 현재 format page를 다 세서 31을 맞힘.
  3. **퍼즐 단서를 문자 그대로 확인** (9e1fc53b c2)
     - 사전 확인(`needs_verification`)이 실제로 실행됐음(이번 재실행에서 2번째; 1번째는 phase A a7feb290 c3의 listing URL 확인으로 무해했음). "Kilt는 leather라 Hunter도 착용 가능"을 확인한 결과 답이 Hunter에서 Druid로 바뀌었음.
- **합계**: A 7/8, c2 4/8, c3 5/8. 384d0dd8을 빼면 A 7/7, c2 4/7, c3 5/7.

### 10.3 정리
- **r9는 r8의 실패 경로를 막았음**: rewrite 규칙이 instruction에 복사되거나 결과 보류 조항이 추가되는 경로임. 같은 draft에서(phase A) 확인했음.
- **불확실성이 비답변으로 바뀌는 일은 다른 단계에서 남아 있음**:
  - 검토 단계가 해석을 엄격한 쪽으로 확정하는 것(a7feb290)
  - 사전 확인이 단서를 문자 그대로 검증하는 것(9e1fc53b)
  - orchestrator가 확인을 다시 맡긴 뒤 비답변으로 끝내는 것(cffe0e32, a7feb290; refiner 없는 fresh에서도 발생)
  - 세 번째는 refiner가 아니라 orchestrator의 공통 prompt(re-check와 finish 정책) 문제임.
- **refiner가 A의 오답을 정답으로 바꾼 사례는 이번에도 없음.** 4d51c4bf와 56137764의 올바른 수정은 A도 맞히는 task였음.
- **표본 한계**: 8개 task, 1–2 rep이라 정답 수 차이는 noise 범위임. 이 절의 주장은 trace에서 본 경로에 대한 것임.

### 10.4 다음 후보 (결정은 사용자)
1. **orchestrator의 finish 정책(공통, A에도 적용)**: 증거가 불완전하면 "Unknown" 대신 best-supported answer를 내게 하기. re-check는 답을 바꿀 구체적 관찰을 찾는 데만 쓰기. a7feb290 fresh와 cffe0e32 c2가 대상.
2. **refiner의 해석 확정**: 해석을 고르는 resolution이 증거 기준까지 바꾸지 못하게 하기(예: "현재 기록은 세지 마라"). 단 이건 a7feb290 하나에 맞춘 수정일 위험이 있음.
3. **사전 확인(needs_verification)**: 1건뿐이라 판단을 보류함.
4. **r9의 순효과 측정**: 47개 전체로 다시 돌리기. 약 $8–9, Serper 약 3,300 credit이 필요한데 남은 건 2,380이라 Serper 충전이 필요함.

### 10.5 제가 정한 것 (이번 단계)
- **r9와 v7의 문구 전체.**
- **v7은 날짜 줄을 없애지 않고 의미만 바꿈**: "the run date is not the task's time reference". F19의 날짜 고정 기능은 유지함.
- **재실행을 두 phase로 나눔**: v7은 v6 checkpoint를 restore할 수 없어서, r9만의 효과는 phase A(같은 draft)에서, 날짜 수정과 r9를 합친 효과는 phase B에서 봄.
- **대상 선정**: 16d825ff, 3da89939는 뺐고(검색 운, credit), 384d0dd8은 phase B에만 넣음. A도 2 rep(phase A). phase B는 1 rep.
- **r8은 보관하지 않음**(r6, r7 관례대로). 그래서 r8 실패의 재현 확률은 재지 않음.
- **a7feb290 c2/c3만 Serper로 다시 돌림.** DDG가 섞인 다른 run(384d0dd8 ×3, a7feb290 A, 9e1fc53b c3)은 결론에 영향이 없다고 보고 그대로 둠.
- **비답변 regex와 "새 조건문" 추출 기준**: scratchpad의 `rerun_analyze.py`.
