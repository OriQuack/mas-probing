# 세 arm이 모두 정답인 22개 과제: probe 항목과 tool observation의 실제 역할 (stage 4, refiner r8)

## 0. 범위, 방법, 라벨 정의

- 대상: stage 4(`stage4-serper-20261009T192620Z`, v6 d0 checkpoint 복원, Serper 검색, refiner r8, 1 rep)에서 A_none, c2_probe_tools, c3_probe_multi가 모두 정답인 22개 과제의 refiner 기록 44개(c2 22개: respondent luna 1명, c3 22개: luna와 haiku 2명).
  - 상태: c2는 no_issues 18 / rewritten 4, c3는 no_issues 10 / rewritten 12.
  - issue는 모두 19개(c2 4, c3 15). decision은 clarify 10, defer_to_execution 9. needs_verification과 not_relevant는 0개였다. analysis 출력에는 받아들인 issue만 나오고, 받아들이지 않은 점은 따로 기록되지 않는다(no_issues 기록의 analysis 출력은 `{"issues":[],"followups":[],"verifications":[]}`뿐이며 추론 텍스트도 없다). 그래서 "무시했다"는 판단은 probe 답변과 issue 목록을 비교해서 내렸다.
- 이 22개 과제는 v5 fresh와 v6 fresh에서도 모두 정답이었다(`stage3-v5-base`, `stage3-v6-base`의 batch.jsonl로 확인). 실패한 run이 없으므로 "실패를 예견했는가"는 해당 사항이 없다. 대신 "실제 위험"은 run 안에서 실제로 비용이나 혼란을 만든 지점으로 판단했다. 예: 5b2a14e8의 브랜드 식별, d5141ca5의 템플릿 전치, 114d5fd0의 JSTOR 차단.
- probe 항목 라벨(응답자 × 항목마다 하나):
  - `M`(matters, 이 과제에 의미 있는 내용): 하위 유형은 `dev`(초안이 과제에서 벗어난 점을 지적), `risk`(실재하는 과제 특이적 위험), `check`(필요하거나 유효한 확인 방법), `interp`(초안에 없던 비자명한 올바른 해석), `find`(실질적 사실 발견이나 사전 풀이).
  - `S`(spurious): `generic`(구체적 근거 없는 일반론), `ambig`(신중한 독자라면 보지 않을 모호성), `strict`(과제가 요구하지 않는 증거 기준), `wrong`(사실 오류나 잘못된 독해).
  - `N`(nothing): 과제나 초안을 재진술했거나 초안을 그대로 따라가는 계획.
  - `M+S`: 한 항목에 둘 다 들어 있음. 집계에서는 matters로 세고, "S 포함" 열에도 따로 표시한다.
  - `NA`: 형식 실패(ad37a656 c3의 haiku). observation에서는 tool을 쓰지 않은 경우를 `no-tool`로 표시했다.
  - choices와 risks가 과제나 초안 조건을 재진술하면 `restate` 플래그를 붙였다. M인데 초안이 이미 다룬 내용이면 `covered by draft`를 붙였다.
- issue 품질 라벨은 RUBRIC 4.5를 따랐다. 출처는 issue의 `evidence`가 근거로 삼은 응답 항목이며, 여러 항목이면 주(primary) 출처를 하나 정했다.
- rewritten 기록과 A 비교: run.json(비용, delegation 수), events.jsonl(지시와 보고)을 사용했고, 필요하면 렌더링한 transcript를 확인했다. transcript는 `scratchpad/allc/tr/<task8>_<arm>.md`에 있으며 아래 줄 번호는 이 파일 기준이다.
- 노이즈 주의: 초안이 바뀌지 않은 no_issues run도 A와 delegation 수가 ±2 정도 다르다(e2d69698 c2 2 vs A 4, d5141ca5 c2 2 vs A 4, b7f857e4 c3 2 vs A 1). 그래서 delegation 수 차이만으로는 rewrite 탓이라고 하지 않았다. 보고서나 이후 지시에 rewrite가 넣은 요구가 명시적으로 등장할 때만 rewrite에 귀속했다.

## 1. 과제별 요약

### 0bdb7c40 (APOD → NASA Group 2 → White; 5876)
- 초안은 과제에 충실하다. c2와 c3 모두 no_issues.
- luna(c2, c3 r1) choices: APOD 캡션에서 "Conrad reflected in Bean’s helmet"을 확인하고 Group 2까지 찾았다(M:find).
- luna risks: "The reflection could be mistaken for the larger astronaut in the photo"는 이 과제의 실제 함정이다(M:risk).
- haiku: understanding에서 이미 Conrad를 식별했다. 반면 choices와 risks에 "Wayback snapshots dated around August 2023", "Group membership can be ambiguous (Group 2 versus other 1962 groupings)" 같은 과잉 기준과 허구의 모호성이 섞였다(S).
- analysis는 이것들을 모두 무시했고, 옳았다. Conrad 발견은 전달되지 않았지만 실행에는 문제가 없었다.

### 114d5fd0 (DOI 책 p.11 endnote; 4)
- 초안은 충실하다. c2 no_issues, c3 rewritten.
- haiku(c3 r1)가 짚은 의미 있는 점: JSTOR anti-bot 차단을 관찰하고 OAPEN 대안을 제시했으며(M), printed page와 PDF index의 차이를 지적했다(M).
- haiku가 틀린 점: "The endnote is probably in chapter 11"은 DOI 접미사 `.11`을 쪽 번호와 혼동한 것이다(S:wrong).
- analysis의 `page-numbering` clarify는 두 응답에 공통된 "printed page"를 명시했을 뿐이다. A 워커도 printed p.11에서 같은 note 14를 찾았으므로 REDUNDANT.
- 경로는 A와 같다(dokumen.pub 사용, 양쪽 모두 d0 tool_limit 20). JSTOR 차단 관찰은 context로 넘어가지 않았지만, A도 대체 출처를 스스로 찾았다.

### 32102e3e (스프레드시트 최고(最古) Blu-Ray; Time-Parking 2)
- 함정: Platform 열은 비어 있고 Blu-Ray는 섹션 라벨 행이다. 같은 제목이 DVD 섹션에도 있다. 초안의 "earliest release/recorded date field"는 다소 모호하지만 Year 열밖에 없으므로 실질적 편차는 아니다.
- c2 luna: plan "Filter records to `Platform` = Blu-Ray"는 틀린 전제다(S:wrong).
  - issue `i1`(oldest = lowest Year)는 REDUNDANT.
  - rewrite에 "identify records whose Platform is Blu-Ray"라는 틀린 전제와 tie/blank 조항이 들어갔다. 워커는 "the Platform cells for those movie records are blank. I treated the records beneath that heading as the Blu-Ray inventory"라며 스스로 바로잡았다.
- c3:
  - haiku가 섹션 구조와 "same title appears in both the DVD and Blu-Ray blocks"라는 진짜 함정을 짚었고, 답까지 미리 계산했다(M).
  - luna(r2)는 row 4의 `DVD` 라벨을 관찰했다(M).
  - `I1` REDUNDANT. rewrite의 "format labels or Platform values"는 정확했지만 A는 이 안내 없이도 해냈다.
- 결과: 비용만 늘었다(A $0.0008 → c2 $0.0028, c3 $0.0045. 대부분 refine 비용).

### 3ff6b7a9 (Greenland; 56000)
- c2 no_issues. luna는 Greenland shark → Greenland를 찾았다(M:find). risk "current page may differ"는 초안이 이미 다룬 내용이다.
- c3 rewritten:
  - haiku가 2020-12-12 snapshot에서 56,081을 읽고 "I did not read a snapshot dated exactly 1 January 2021 or check the page history"라고 썼다.
  - 이를 바탕으로 `I1` defer(2021-01-01 이전 최신 revision 사용)가 나왔다. A와 c2 워커도 이미 oldid=997702868을 썼으므로 REDUNDANT.
  - context_additions가 probe 값 56,081을 그대로 전달했다(답 누출).
- c3 실행은 revision API로 바로 확인해 tool 5회로 끝났다(A 13회).

### 4d51c4bf (awning; 8)
- 22개 중 초안에 실제 편차가 있는 유일한 과제다. 초안에 v6 run-date 문구가 들어왔다: "using run reference date 2026-10-09 and the stated last-90-days condition if dates require filtering".
- 응답자 셋(c2 luna, c3 luna, c3 haiku) 모두 "no order-date column → rely on the task’s statement"를 냈다(M:dev).
- c2 analysis의 `date-filter` clarify는 CORRECT-CATCH다. 다만 날짜 열이 없어서 효과는 0이었다.
- c3는 같은 신호가 있었는데도 no_issues였다. 조건부 문구라 무해하다고 판단한 것으로 보인다. haiku의 "If some orders are older than 90 days, the count would be lower than 8", "‘in this region’ may not apply to all of them" 같은 S는 무시했고, 옳았다.
- 세 arm 모두 tool 1회로 8을 냈다.

### 56db2318 (ISBN 변형; 7, 9)
- 초안이 매우 정밀하다(w 2..9, i 3..10을 사실상 명시). 모든 응답의 choices가 초안을 재진술했고(N, restate), risks는 일반론이었다("An indexing or alternating-weight parity error could produce false candidates").
- haiku는 "The swapped pair can be a same-weight pair (e.g., indices 3 and 5 both odd)"라는 잘못된 주장을 했다. 3과 5는 인접 열이 아니다.
- no_issues ×2는 옳다.

### 5b2a14e8 (하네스 브랜드 → 앰배서더 기사; bacon). 가장 중요한 사례
- 실제 난관은 이미지에서 브랜드(Ruffwear)를 식별하는 일이었다. A는 d0–d4 동안 Hurtta와 curli를 헤매다 d5에서야 Ruffwear 기사를 찾았다(6 delegation).
- c2 (luna):
  - choices "I would treat the date as the story’s publication date"는 자연스럽고 올바른 독해다(N).
  - analysis는 이것을 편차로 보고 `date-meaning` clarify를 만들었다: "do not assume it means publication date if the site distinguishes those dates". 조건부라 약하지만 HARMFUL-STRICT다.
  - c2 d0는 운 좋게 Ruffwear 기사(bacon)를 바로 찾았고, d1은 08/12/22 날짜 형식만 확인했다(2 delegation). 이 차이는 rewrite와 무관하며 효과는 unclear.
- c3 (haiku r1, luna r2):
  - haiku choices "The harnesses look like Ruffwear Front Range models"는 정답 브랜드다(M:find, view_image 관찰에 기반).
  - 같은 choices의 "For ‘added Dec 8th 2022,’ I would take the publication or posted date shown on the story page"는 자연스러운 독해다.
  - analysis는 브랜드 단서를 버리고 날짜 문구만 issue로 삼았다: "Find the story whose website listing or metadata says it was added on Dec 8, 2022; do not substitute a different publication date" (HARMFUL-STRICT).
  - 오케스트레이터는 이 조건을 d1부터 d9까지 모든 지시에 반복했다. d1의 "Do not use publication date in place of added date"(line 705)부터 d7의 "publication date alone is insufficient"까지.
  - d3 워커는 검색 결과 1위로 "Snow Camping With Theresa & Cassie - Ruffwear"를 받고도(line 1624) tool 한도 때문에 열지 못했다.
  - d8은 기사를 찾았지만 이렇게 썼다: "Under the requirement not to treat publication date as an added date, the match remains **unverified**. Bacon is the answer only if the clue’s “added Dec 8th 2022” refers to the story’s displayed date" (line 3668). 그 결과 d9 검증이 추가됐다.
  - 총 10 delegation, $0.188(A 6 delegation, $0.111). 최소 1 delegation(d9)과 보고서의 유보는 rewrite 탓이고, 나머지는 브랜드 식별 노이즈다.
- 이 과제에서 probe가 준 가장 값진 정보(Ruffwear)를 analysis가 버렸다.

### 5cfb274c (Earl의 Hamiltonian cycle; No)
- c2와 c3 모두 no_issues.
- luna: "The workbook reader reports 0 rows × 0 columns despite showing fills through G17"(도구 특이점, M:risk), `FF00FF00` = 녹색(M:find).
- haiku: parity와 degree를 이용한 증명을 제안했다(M:check).
- 초안이 충실하고 실행도 문제없었다.

### 5d0080cb (fish bag 부피; 0.1777)
- no_issues ×2.
- haiku는 PDF를 읽어 0.1777 m³, 그리고 혼동할 수 있는 0.0889(반 bag), 0.0016, 0.0071을 열거했다(M). 초안의 "distinguish the bag’s volume from any other volume"과 같은 방향이다.
- luna의 choices와 risks는 초안 재진술이다.

### 8e867cd7 (Mercedes Sosa; 3)
- c2 no_issues. luna risk "A release in the period may be a double or multi-part album"은 Cantora 1/2를 가리키는 실제 함정 후보다(M:risk).
- c3 rewritten:
  - haiku의 관찰 "The dedicated discography page had no snapshot on or before 2022-12-31"은 사실이다.
  - 하지만 잘린 snippet을 근거로 "the count may be 2"라고 썼다(S:wrong). choices는 "Where an archive is unavailable, use the closest one and say so"였다.
  - analysis의 `version-fallback` defer는 이 합리적인 fallback을 뒤집었다: "Do not substitute a revision from outside 2022; if no 2022 version can be accessed, report that specific limitation". 과제는 "You can use the latest 2022 version"이라는 허용 표현이므로 이것은 HARMFUL-STRICT이고, 이번에는 잠재적 위험에 그쳤다.
- 실행은 A와 같은 revision 1126540422를 썼다. tool 12회 vs 9회, $0.025 vs $0.0075.

### a56f1527 (Vogue 표지 → Washington Monument; 185)
- 과제가 의도한 것은 US Vogue(Jill Biden 표지)이고, 초안은 충실하다("noting country edition if relevant").
- c2:
  - luna choices "I would not assume the US edition"은 S:ambig다.
  - 이것이 `edition` defer가 됐다: "Check August 2021 covers across relevant Vogue editions … if more than one cover fits, report the candidates and the ambiguity" (HARMFUL-AMBIG).
  - d0 워커는 영국판과 인도판 표지 조사에 예산을 쓰고 tool_limit에 걸려 이렇게 보고했다: "The **Washington Monument** is a possible landmark, but I could not confirm from the available evidence" (line 852).
  - 그 결과 시각 확인 delegation(d1)이 추가됐고, 높이는 d2에서 구했다. 3 delegation, $0.059(A 2 delegation, $0.016).
- c3:
  - haiku는 오히려 정답 쪽 독해를 냈다: "Treat ‘the August 2021 issue’ as US Vogue unless the cover image shows otherwise"(M:interp). 정답 가설도 냈다: "The Jill Biden cover was shot at the White House, so a landmark behind trees there could plausibly be a nearby monument".
  - analysis는 luna(r2)의 "I would not assume the U.S. edition"과 haiku의 edition risk만 취했다: "Do not assume a country edition" (HARMFUL-AMBIG).
  - d0은 tool_limit 20(A는 16회로 ok)에 걸렸고 "I did not independently inspect every international edition’s cover image"라는 유보를 달았다. 추가 delegation은 없었다.

### ad37a656 (Tunguska → Castle Bravo; Bravo)
- no_issues ×2.
- haiku는 tool 한도에 걸린 뒤 네 항목 형식을 지키지 않고 "Result: Not verified in this run. The likely answer is ‘Bravo’"로 답했다(파싱 실패, NA). analysis에는 원문 그대로 전달됐다.
- luna risk "Britannica may state a range"는 Britannica의 "as much as 15 megatons"를 고려하면 약하게나마 실재하는 위험이다(M).
- 초안이 충실하고 판단은 옳았다.

### b7f857e4 (Python → URL → C++; 47)
- no_issues ×2.
- haiku는 URL과 47을 미리 도출했다. 또 "Read ‘third and fifth integers’ as 1-based positions"(M:interp)와 "the C++ section may contain more than one program"(실재, M:risk)을 짚었다.
- luna의 choices는 재진술이다.
- c3의 2 delegation은 오케스트레이터가 실제 C++ 실행 확인을 요구한 결과로, 노이즈다.

### bda648d7 (Nedoshivina 2010; Saint Petersburg)
- c2 no_issues.
- c3 rewritten:
  - haiku choices "I would give the city as ‘Saint Petersburg’ or ‘St. Petersburg’ as the paper spells it"는 과제와 충돌한다(S:wrong).
  - `I1` clarify는 이를 과제 쪽으로 바로잡았다: "report ‘Saint Petersburg’ if the paper says ‘St. Petersburg’". 하지만 초안이 이미 "Report the full city name without abbreviations"라고 했으므로 REDUNDANT다. 게다가 rewrite 예시에 답 문자열이 그대로 들어갔다.
- 실행은 A와 같다.

### c3a79cfe (지하철 역 수; 8)
- c2 no_issues. luna의 "Cleveland Elementary’s own Metro page lists both Shaw–Howard University and U Street–Cardozo"(U Street이면 9, M:risk)와 Mall과 Udvar-Hazy의 구분(M:interp)이 있었지만, 초안이 이미 "closest"를 요구하므로 무시한 것은 옳다.
- c3 rewritten:
  - haiku plan의 잠정 경로 "7 intervals"는 Archives를 빠뜨린 오류다(S:wrong).
  - analysis는 이 계산 오류가 아니라 "continuity unverified"를 issue로 만들었다(`I1` defer): "If 2022 evidence shows no continuous same-line route, explain which specific evidence prevents deriving the requested number" (HARMFUL-AMBIG, r8의 withholding 규칙).
  - d0 보고: "The answer is **8** if the trip is during the part of 2022 when Yellow Line service was operating. There is no single valid answer for all of 2022", "**8 is conditional**" (line 1289).
  - 오케스트레이터는 8로 종료했다. A와 c2 보고서도 2022년 9월 Yellow Line 중단을 언급했지만, 결론을 조건부로 만들지는 않았다.

### c8b7e059 (Lauria 각주 397 → Leviathan; 8)
- c2 no_issues. luna의 내용은 재진술과 "the August 2023 museum reference may also differ"뿐이었다.
- c3 rewritten에서 issue 두 개가 나왔고, 둘 다 HARMFUL-STRICT다:
  - `I1`: luna(r2) choices "I would treat ‘as of August 2023’ as requiring museum evidence from that date or earlier"(S:strict)에서 나왔다.
  - `I2`: haiku risks "No full text of the dissertation is available to me, so footnote 397 is unverified"에서 나온 "verify footnote 397 directly from its full text".
  - rewrite에는 r8 문구도 들어갔다: "report the limitation rather than infer the result".
- 실행 경로:
  - d0: "I could not verify the two SAAM paintings or their chapter references, so I cannot calculate the requested absolute difference" (line 822).
  - d1이 8을 도출했지만 "likely"라는 단서를 달았다.
  - d2 지시는 rewrite가 만든 증거 공백을 메우는 추가 delegation이었다: "Resolve only the stated evidence gaps: (1) … footnote 397 … (2) … Leon Karp’s SAAM painting … by August 2023 using a dated archived page" (line 1337).
  - 최종 근거는 결국 A와 같았다(검색 색인에 잡힌 각주와 1984년 기증 기록).
- 3 delegation vs A 2. 비용은 $0.072로 A($0.080)와 비슷한데, A의 d0가 비쌌기 때문이다.

### d5141ca5 (Aquinas 그림 최초 등장; 19/02/2009)
- 정답 메커니즘: `{{Thomism}}` 템플릿 전치(transclusion)가 2009-02-19에 추가됐다.
- c2 no_issues. luna risks는 초안 재진술이었고("an image change could be mistaken for the first appearance"), 템플릿 메커니즘은 예견하지 못했다.
- c3:
  - haiku risks는 핵심 메커니즘을 짚었다: "an Aquinas painting … in the Thomas Aquinas navbox … the article history and the template history could give different dates" (M).
  - 그러나 haiku choices "Count only images added to the article’s own wikitext"는 틀렸다(S:wrong).
  - analysis는 위험만 채택하고 틀린 선택은 버렸다(`navbox-image` defer, CORRECT-CATCH).
- 효과는 불분명하다:
  - A d0는 힌트 없이 바로 전치 날짜를 찾았다.
  - c3 d0는 템플릿 생성일만 찾고 "the earliest supported candidate, but not conclusively established"라는 단서를 달았다.
  - c3는 3 delegation, A는 4 delegation이다(A의 오케스트레이터가 과잉 검증했다).

### dd3c7503 (꿀/마요네즈 밀도; 6)
- c2 no_issues. luna risk "snippet lists mayonnaise as 0.92 and honey as 0.910"은 snippet을 잘못 읽은 것이다(S:wrong). 무시한 것은 옳았다.
- c3 rewritten, issue 3개. 출발점은 haiku choices "Treat ‘compiled 08/21/2023’ as a request for the snapshot on or before 2023-08-21", "do not assume 25 °C"(S:strict)다.
  - `source-version` (HARMFUL-STRICT): analysis는 snapshot 해석은 버렸지만 다른 엄격한 기준으로 바꿨다: "Verify that the source you use matches the requested compilation using its title, attribution/license, and compilation information".
  - `temperature` (REDUNDANT): haiku의 엄격함을 뒤집는 anti-withholding 조항이다. 표에 이미 25°C가 명시돼 있다.
  - `volume-units` (REDUNDANT): US 기준 16 cups.
- 실행 경로:
  - d0: "The values above should therefore be treated as findings from a candidate source, not as fully verified values from the specified compilation" (line 912).
  - d1과 d2가 08/21/2023 컴파일 여부 확인에 쓰였다. 라이브 InfoPage는 "This text was compiled on 10/09/2026"이었다.
  - 결국 같은 값으로 6을 냈다.
- 3 delegation, $0.063(A 1 delegation, $0.015). A 워커도 "I could not independently verify the specific 08/21/2023 compilation date"라고 썼지만 A의 오케스트레이터는 그대로 종료했다.

### de9887f5 (harlequin shrimp; 22)
- no_issues ×2.
- luna와 haiku 모두 두 논문을 식별했다(M:find). haiku는 Fiedler의 "small (approximately 1 cm) pieces of seastar"를 확인했다.
- haiku risk "Fiedler’s 1 cm is a fragment, not a whole sea star. The task’s ‘sea star fed’ wording may mean a different measure"는 S:ambig다. 무시한 것은 옳았다.

### df6561b2 (빨강/초록 수 통계; 17.056)
- no_issues ×2.
- luna의 두 응답은 초안 재진술에 일반론 risk("Small or blurry signs, decimal points, or color differences")를 더한 것이다.
- haiku는 이미지에서 27개 + 27개 수를 읽고 17.056을 계산했다. "The red/green split is the main risk"(M)도 짚었다.

### e2d69698 (Survivor 5월생 우승자; Michele Fitzgerald)
- c2 no_issues. luna choices가 cutoff를 season 1–44로 확정했다(CBS 기준 S44 finale 2023-05-24, S45 premiere 2023-09-27, M:find).
- c3 rewritten:
  - luna(r1)는 같은 사실을 냈다.
  - haiku(r2)는 틀렸다: "seasons 1–45, aired by August 2023", "through Survivor 45’s spring 2023 finale"(S:wrong).
  - analysis는 이 불일치를 issue로 만들어 올바른 쪽(S44)으로 해소했다(`scope` clarify). 모든 arm의 워커가 S44를 스스로 썼으므로 REDUNDANT.
- 세 arm 모두 "only" 검증 루프로 2–4 delegation을 썼다. 차이는 노이즈다.

### ed58682d (Thriller 다섯 번째 싱글; stare)
- no_issues ×2.
- luna와 haiku 모두 Thriller(여섯 번째 솔로 스튜디오 앨범)와 Human Nature를 찾았다(M:find).
- 지역별 발매 순서와 chorus 라벨링 위험(M:risk)은 초안이 이미 "noting any ambiguity", "distinguish choruses from repeated refrains"로 다루고 있었다.

## 2. 집계

### 2.1 probe 항목 × 응답자 모델: matters / spurious / nothing

응답 수: luna 44개(c2 22, c3 22), haiku 22개(1개는 형식 실패). "matters"는 M과 M+S를 합한 수이고, "그중 M+S"는 그 안에 spurious 내용도 섞인 수다. "S 포함"은 S와 M+S를 합한 수다.

| 항목 | 모델 | matters | (그중 M+S) | spurious만 | nothing | NA | S 포함 |
|---|---|---|---|---|---|---|---|
| understanding | luna (44) | 2 | 0 | 0 | 42 | 0 | 0 |
| understanding | haiku (22) | 10 | 0 | 2 | 9 | 1 | 2 |
| choices | luna (44) | 21 | 0 | 3 | 20 | 0 | 3 |
| choices | haiku (22) | 18 | 5 | 2 | 1 | 1 | 7 |
| risks | luna (44) | 29 | 5 | 11 | 4 | 0 | 16 |
| risks | haiku (22) | 15 | 8 | 6 | 0 | 1 | 14 |
| plan | luna (44) | 6 | 1 | 1 | 37 | 0 | 2 |
| plan | haiku (22) | 12 | 4 | 2 | 7 | 1 | 6 |
| observations | luna (44; no-tool 10) | 28 | 0 | 0 | 6 | – | 0 |
| observations | haiku (22; no-tool 1) | 19 | 1 | 0 | 2 | – | 1 |

luna를 arm별로 나누면 choices의 matters는 c2 8/22, c3 13/22이고, risks는 c2 14/22, c3 15/22다. c3의 luna가 tool을 더 써서 발견을 choices에 더 많이 담았기 때문이다.

### 2.2 "matters"의 내용: 대부분 발견(find)이고, 초안 편차 지적(dev)은 드물다

| 항목 | 모델 | find | risk | interp | check | dev | 초안이 이미 다룬 M |
|---|---|---|---|---|---|---|---|
| understanding | luna | 2 | – | – | – | – | 0 |
| understanding | haiku | 10 (사전 풀이 다수) | – | – | – | – | 0 |
| choices | luna | 16 | 2 | 3 | – | 2 | 1 |
| choices | haiku | 13 | – | 7 | 2 | 1 | 0 |
| risks | luna | 6 | 24 | – | – | 1 | 5 |
| risks | haiku | 2 | 12 | – | 2 | – | 0 |
| plan | luna | 5 | – | – | 1 | – | 0 |
| plan | haiku | 5 | – | – | 7 | – | 0 |
| observations | luna / haiku | 28 / 19 | – | – | – | – | – |

(한 항목에 여러 하위 유형이 있으면 각각 셌다.)

- `dev`(초안 편차 지적)는 4d51c4bf의 날짜 열 부재 하나뿐이고 세 응답자 모두 이를 짚었다(c2 luna choices와 risks, c3 luna choices, c3 haiku choices). 22개 초안 중 실제 편차가 있던 것은 이 하나였다.
- haiku의 understanding은 사전 풀이를 담는 그릇이었다(10/22). 3ff6b7a9 56,081, 5d0080cb 0.1777, df6561b2 17.056, b7f857e4 47, 32102e3e 제목, 4d51c4bf 8, c3a79cfe Shaw-Howard 경로, ed58682d Human Nature 등.

### 2.3 choices와 risks의 재진술(restate)

| | choices restate | risks restate |
|---|---|---|
| luna | 19/44 (43%) | 14/44 (32%) |
| haiku | 4/21 | 1/21 |

probe 지시가 "Do not merely repeat given conditions"라고 했는데도 luna의 choices 중 43%는 초안이나 과제 조건을 되풀이했다. 예: "I would use Britannica’s stated yield as the matching criterion", "I would count the first appearance of an image depicting Aquinas, not a later replacement". luna의 risks 중 32%도 초안이 이미 요구한 확인을 위험으로 바꿔 말한 것이었다.

### 2.4 issue 출처 × 품질 (19개)

주 출처 항목 기준:

| 출처 항목 | CORRECT-CATCH | REDUNDANT | HARMFUL-STRICT | HARMFUL-AMBIG | 계 |
|---|---|---|---|---|---|
| choices | 1 (4d51c4bf c2) | 7 | 5 | 2 | 15 |
| risks | 1 (d5141ca5 c3) | 1 | 1 | 0 | 3 |
| plan | 0 | 0 | 0 | 1 (c3a79cfe) | 1 |
| understanding | 0 | 0 | 0 | 0 | 0 |
| draft-vs-task (probe 근거 없음) | 0 | 0 | 0 | 0 | 0 |
| 계 | 2 | 8 | 6 | 3 | 19 |

- observation이 보조 근거로 인용된 issue는 9개였다: 32102e3e c3 R, 3ff6b7a9 R, 4d51c4bf CC, 8e867cd7 HS, a56f1527 c3 HA, c8b7e059 I2 HS, d5141ca5 CC, dd3c7503 source-version HS, e2d69698 R.
- WRONG-READING, HARMFUL-NARROW, OTHER는 없었다.

주 출처의 모델 기준(c3에서 응답자는 익명이고 순서는 무작위였다):

| 출처 모델 | CORRECT-CATCH | REDUNDANT | HARMFUL-STRICT | HARMFUL-AMBIG | 계 |
|---|---|---|---|---|---|
| luna (c2) | 1 | 1 | 1 | 1 | 4 |
| luna (c3) | 0 | 1 | 1 | 0 | 2 |
| haiku (c3) | 1 | 5 | 4 | 2 | 12 |
| 두 응답의 불일치 (e2d69698) | 0 | 1 | 0 | 0 | 1 |

decision 기준:

| decision | CORRECT-CATCH | REDUNDANT | HARMFUL-STRICT | HARMFUL-AMBIG | 계 |
|---|---|---|---|---|---|
| clarify | 1 | 7 | 2 | 0 | 10 |
| defer_to_execution | 1 | 1 | 4 | 3 | 9 |

### 2.5 rewritten 16건: A 대비 경로, 비용, 유보

| 과제 | arm | issue 품질 | A: del / $ / d0 | arm: del / $ (refine) / d0 | 경로 변화와 유보 | 효과 |
|---|---|---|---|---|---|---|
| 114d5fd0 | c3 | R | 1 / 0.0262 / 20 tool_limit | 1 / 0.0364 (0.0052) / 20 tool_limit | 동일 | none |
| 32102e3e | c2 | R | 1 / 0.0008 / 2 ok | 1 / 0.0028 (0.0017) / 2 ok | 동일. rewrite의 "Platform is Blu-Ray" 전제를 워커가 교정 | none |
| 32102e3e | c3 | R | 1 / 0.0008 / 2 ok | 1 / 0.0045 (0.0039) / 1 ok | 동일 | none |
| 3ff6b7a9 | c3 | R | 1 / 0.0119 / 13 ok | 1 / 0.0135 (0.0084) / 5 ok | revision API로 직행. context에 답 누출 | none |
| 4d51c4bf | c2 | CC | 1 / 0.0008 / 1 ok | 1 / 0.0029 (0.0021) / 1 ok | 동일 | none |
| 5b2a14e8 | c2 | HS | 6 / 0.1106 / 20 tool_limit | 2 / 0.0430 (0.0012) / 20 tool_limit | d0에서 Ruffwear를 우연히 찾음(rewrite 무관) | unclear |
| 5b2a14e8 | c3 | HS | 6 / 0.1106 / 20 tool_limit | 10 / 0.1877 (0.0051) / 20 tool_limit | "added date" 조건이 d1–d9로 전파됨. d8 유보 → d9 추가 | cost+ |
| 8e867cd7 | c3 | HS | 1 / 0.0075 / 9 ok | 1 / 0.0249 (0.0054) / 12 ok | 같은 revision 사용 | none |
| a56f1527 | c2 | HA | 2 / 0.0160 / 16 ok | 3 / 0.0593 (0.0015) / 20 tool_limit | 판본 조사로 d0 예산 소진, 유보 → 시각 확인 delegation 추가 | cost+ |
| a56f1527 | c3 | HA | 2 / 0.0160 / 16 ok | 2 / 0.0257 (0.0052) / 20 tool_limit | d0 tool_limit, "cannot rule out" 유보 | hedge+ |
| bda648d7 | c3 | R | 1 / 0.0047 / 4 ok | 1 / 0.0093 (0.0040) / 7 ok | 동일 | none |
| c3a79cfe | c3 | HA | 1 / 0.0243 / 20 tool_limit | 1 / 0.0396 (0.0164) / 20 tool_limit | "8 is conditional" 유보 | hedge+ |
| c8b7e059 | c3 | HS, HS | 2 / 0.0801 / 20 tool_limit | 3 / 0.0718 (0.0100) / 20 tool_limit | d0 "cannot calculate". d2가 rewrite의 증거 공백을 메움 | cost+ |
| d5141ca5 | c3 | CC | 4 / 0.1262 / 14 ok | 3 / 0.1607 (0.0077) / 20 tool_limit | d0 유보(템플릿 생성일만 확인). A도 과잉 검증 | unclear |
| dd3c7503 | c3 | HS, R, R | 1 / 0.0152 / 20 tool_limit | 3 / 0.0629 (0.0105) / 20 tool_limit | d0 "candidate source" 유보 → 컴파일 확인 delegation 2개 추가 | cost+ |
| e2d69698 | c3 | R | 4 / 0.0937 / 20 tool_limit | 3 / 0.0807 (0.0056) / 20 tool_limit | 모든 arm이 같은 uniqueness 루프 | none |

- 정리: 16건 중 비용이나 delegation 증가가 rewrite에 귀속되는 것은 4건(cost+)이다. 유보만 늘어난 것이 2건(hedge+), 효과 불명 2건, 효과 없음 8건이다. 정답성은 어디서도 바뀌지 않았다.
  - cost+: 5b2a14e8 c3, a56f1527 c2, c8b7e059 c3, dd3c7503 c3.
  - hedge+: a56f1527 c3, c3a79cfe c3.
  - 도움이 된 경우(helped)는 0건이다. 22개 모두 A도 정답이었으므로 도울 여지가 거의 없었다.
- 비용 합계(같은 과제끼리 비교):
  - c3 rewritten 12건: $0.718(A $0.517, +39%), delegation 30(A 25).
  - c3 no_issues 10건: $0.233(A $0.147). 차이는 refine 비용과 노이즈다.
  - c2 rewritten 4건: $0.108(A $0.128). 5b2a14e8 c2의 운이 a56f1527 c2의 3.7배 비용을 상쇄했다.
  - refine 비용 총액: c2 $0.052, c3 $0.140.

### 2.6 analysis가 무시한 probe 내용 (옳게 / 잘못)

- **no_issues 28건**: 초안 21/22개가 충실했으므로 no_issues는 거의 언제나 옳은 출력이었다. 무시된 S 내용은 그대로 버려졌다. 예:
  - haiku의 0bdb7c40 snapshot 요구와 group 모호성, 114d5fd0 chapter 11 오독, 4d51c4bf 중복 행·지역·90일 유보, 56db2318 같은 가중치 쌍 오류, de9887f5 "whole sea star" 모호성.
  - luna의 dd3c7503 snippet 오독.
  - 경계 사례 하나: 4d51c4bf c3는 세 응답이 모두 날짜 열 부재를 짚었는데도 초안의 run-date 문구를 남겼다. 조건부라 무해했지만, c2는 같은 신호로 수정했으니 analysis 판단이 일관되지 않다.
  - no_issues 기록에서는 probe의 발견(Conrad, Tunguska/Bravo, 0.1777, 17.056 등)이 워커에게 전혀 전달되지 않는다. 실행에 필요하지 않아 손해는 없었다.
- **rewritten 기록에서 잘못 무시된 M**:
  1. 5b2a14e8 c3: haiku의 "Ruffwear Front Range"를 버렸다. 브랜드 식별에 8 delegation을 쓴 이 run에서 가장 비싼 누락이다.
  2. a56f1527 c3: haiku의 "Treat … as US Vogue unless the cover image shows otherwise"와 White House 가설을 버리고, luna의 "would not assume the U.S. edition" 쪽을 채택했다.
- **S나 틀린 선택을 과제 쪽으로 바로잡은 경우(좋은 필터링)**: e2d69698(haiku의 S45 오류 → S44), bda648d7("St." 유지 → "Saint"로 확장), dd3c7503 temperature("do not assume 25 °C" → 값은 보고), d5141ca5(wikitext만 → 템플릿 포함). 모두 과제 텍스트나 검증 가능한 사실이 답을 정해 주는 경우였다.
- **S나 "확인 못함"을 엄격한 요구, 모호성, 유보로 키운 경우(나쁜 필터링)**: a56f1527 c2/c3(edition), 5b2a14e8 c2/c3(added vs publication), c8b7e059 I1/I2, dd3c7503 source-version, 8e867cd7 version-fallback, c3a79cfe continuity. 모두 과제 텍스트가 침묵하는 지점이었다(판본, "added", "as of", "compiled", "2022 version", 연중 운행 변화).
- 대략적 비율: S가 들어 있는 항목은 약 50개(luna 21, haiku 29+obs 1)였다. 그중 issue에 연결된 것은 10개 안팎이고, 나머지 약 80%는 버려졌다. 연결된 경우의 절반은 과제 쪽으로 교정됐고, 절반은 harmful issue가 됐다. harmful 9개 중 S 항목이 그대로 승격된 것은 3개뿐이다(a56f1527 c2·c3, c8b7e059 I1). 나머지 6개는 다음 두 경로로 생겼다.
  - 정답인 자연스러운 독해를 편차로 오인한 경우 2개: 5b2a14e8 ×2.
  - 실재하는 검증 한계나 위험을 필수 검증 게이트나 유보 조건으로 바꾼 경우 4개: 8e867cd7, c8b7e059 I2, dd3c7503, c3a79cfe.

## 3. 결론

1. **understanding은 instruction review에서 역할이 없다.**
   - luna 42/44가 재진술이었고, 어떤 issue의 출처도 되지 않았다.
   - haiku에게는 사전 풀이를 적는 자리였다(10/22). 과제가 쉬운지 알려 주는 신호는 될 수 있지만 refiner는 이를 쓰지 않았다.
2. **choices는 issue의 주된 생성기(15/19)이고, 좋은 issue와 나쁜 issue가 모두 여기서 나온다.**
   - 유일하게 초안 편차를 잡은 CORRECT-CATCH(4d51c4bf)가 choices에서 나왔다.
   - 그러나 harmful 9개 중 7개도 choices에서 나왔다.
   - analysis는 응답자가 명시한 해석이 초안에 적혀 있지 않기만 하면, 그것이 자연스러운 정답 독해여도 issue로 삼는 경향이 있다. 5b2a14e8 c2의 "treat the date as the story’s publication date"가 그 예다.
   - luna의 choices는 43%가 재진술이었고, matters의 대부분은 발견(find)이었다.
3. **risks는 "matters" 건수는 가장 많지만 instruction 개선에 쓸 만한 것은 드물다.**
   - risks는 실행상 진짜 난관을 여러 번 정확히 예견했다:
     - 5b2a14e8의 로고 판독 불가
     - d5141ca5의 템플릿 전치
     - 114d5fd0의 JSTOR 차단
     - c3a79cfe의 두 역 후보와 2022년 운행 중단
     - 8e867cd7의 double album
   - 하지만 이것들은 instruction의 결함이 아니라 실행상의 난관이다. analysis가 이런 위험으로 할 수 있는 일은 검증 단계를 추가하는 것뿐이었고, 결과는 1번의 CORRECT-CATCH(d5141ca5, 효과 불명)와 harmful 게이트(c8b7e059 I2, c3a79cfe)였다.
   - risks에는 일반론과 초안 재진술도 많다: luna는 S 포함 16/44, 재진술 14/44, haiku는 S 포함 14/21이다.
4. **plan은 거의 쓸모가 없었다.**
   - luna의 plan은 37/44가 초안을 그대로 따라갔다.
   - haiku의 plan에는 유용한 실행 팁이 있었지만(parity 증명, Python 교차 확인, OAPEN 등) 사용되지 않았다.
   - 한 번은 틀린 경로(c3a79cfe의 7 intervals)가 harmful issue로 이어졌다.
5. **tool observation은 가장 꾸준히 유용한 내용이지만, 전달 경로가 issue와 rewrite에 묶여 있다.**
   - tool을 쓴 응답 기준으로 luna 28/34, haiku 19/21이 실질적 발견을 냈다(엔티티, 파일 구조, 심지어 답).
   - 이런 발견이 워커에게 닿은 것은 rewrite에 딸린 context_additions 4건뿐이었다:
     - 3ff6b7a9: 답 56,081 누출
     - c8b7e059: 논문 정보
     - d5141ca5: navbox 단서
     - e2d69698: 시즌 날짜
   - no_issues 기록에서는 아무것도 전달되지 않는다. 가장 값진 관찰(5b2a14e8의 Ruffwear)도 버려졌다.
   - 반대로 발견을 넘기면 답이 누출되는 문제도 생긴다(3ff6b7a9, bda648d7의 rewrite 예시).
6. **응답자 모델 차이.**
   - haiku의 답은 길고 모든 것을 더 많이 담는다. matters(사전 풀이, 올바른 해석)도 많고, S(snapshot 요구, 판본 모호성, 과잉 유보)도 많다.
   - c3의 issue 15개 중 12개의 주 출처가 haiku였다.
   - 그 결과 c3의 rewrite율은 12/22로 c2(4/22)의 3배이고, harmful issue는 c3 7개, c2 2개였다.
   - haiku의 S가 그대로 채택된 경우보다, haiku의 S가 analysis로 하여금 "그 지점을 명시하라"고 반응하게 만들고 그 명시가 엄격한 쪽으로 기우는 경우가 더 많았다(dd3c7503, 8e867cd7).
7. **analysis 필터링의 패턴.**
   - 잡음의 대부분(약 80%)은 버린다.
   - 응답의 선택이 과제 텍스트와 충돌하면 과제 쪽으로 바로잡는다(4건, REDUNDANT 또는 CORRECT).
   - 과제 텍스트가 침묵하는 지점(판본, "added", "as of", "compiled", 연중 변화)에서는 검증 게이트나 "후보 보고/한계 보고" 조건을 추가하는 쪽으로 해소한다. 이것이 harmful 9개 전부의 성격이다.
   - 이 경향은 defer_to_execution에 몰려 있다(9개 중 7개가 harmful). 이 decision의 resolution 형식("the check and how to proceed for each relevant outcome")과 r8의 "report the limitation rather than infer" 규칙이 결과 분기와 유보 조건을 만들어 내기 쉽다.
   - clarify는 10개 중 7개가 REDUNDANT였다.
8. **이 22개에서 이상적인 출력은 거의 언제나 no_issues였다**(초안 21/22이 충실).
   - c2는 18/22를 달성했다. rewrite 4건은 CC 1, R 1, HS 1, HA 1.
   - c3는 10/22에 그쳤다.
   - 정답 과제에서 refiner의 순효과는 비용 증가(특히 c3)와 일부 run의 delegation 및 유보 증가였다. 도움이 된 사례는 없었다.
   - 정답성이 유지된 것은 오케스트레이터가 유보된 보고서를 받고도 결국 답을 냈기 때문이다(c3a79cfe, 5b2a14e8 c3 d10, dd3c7503 d3). r8의 limitation 문구가 더 강하게 작동하는 과제에서는 같은 유형의 issue가 실패로 이어질 수 있다.

## 4. 기록별 데이터

```json
[
 {
  "task": "0bdb7c40",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right: draft faithful; Conrad finding not needed as context",
  "effect_vs_A": "none"
 },
 {
  "task": "0bdb7c40",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "M:find",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M+S:find/strict (restate)",
    "risks": "S:generic/ambig (restate)",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right: spurious snapshot/group-membership points ignored",
  "effect_vs_A": "none"
 },
 {
  "task": "114d5fd0",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M:risk (covered by draft)",
    "plan": "M:find",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "114d5fd0",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "M+S:interp/wrong",
    "risks": "M+S:risk/generic",
    "plan": "M:check",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:interp (covered by draft)",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "page-numbering",
    "decision": "clarify",
    "source": "r1.choices+r1.risks (haiku); r2.choices (luna)",
    "source_model": "haiku",
    "quality": "REDUNDANT",
    "note": "printed page is the reading every worker used; A found the same note on printed p.11"
   }
  ],
  "ignored_points": "chapter-11 misinference ignored (right); JSTOR-block observation not passed (A found dokumen.pub anyway)",
  "effect_vs_A": "none",
  "path_note": "same path as A (dokumen.pub, tool_limit 20 in both)"
 },
 {
  "task": "32102e3e",
  "arm": "c2_probe_tools",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "S:generic",
    "plan": "M+S:find/wrong",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "i1",
    "decision": "clarify",
    "source": "r1.choices (+r1.observation)",
    "source_model": "luna",
    "quality": "REDUNDANT",
    "note": "oldest = lowest Year: the only reading; rewrite also imported the wrong premise \"records whose Platform is Blu-Ray\" and tie/blank clauses; worker noted Platform is blank and used the section heading"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "none",
  "path_note": "same 2-tool path; report adds \"no Blu-Ray entries have a blank Year\" in answer to the rewrite"
 },
 {
  "task": "32102e3e",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M:interp",
    "risks": "M:risk",
    "plan": "M:check",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:risk",
    "risks": "M:find",
    "plan": "M:check",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "I1",
    "decision": "clarify",
    "source": "r2.choices+r2.observation (luna); r1.choices (haiku)",
    "source_model": "luna",
    "quality": "REDUNDANT",
    "note": "lowest Year; \"format labels or Platform values\" correct but A worker did it unaided"
   }
  ],
  "ignored_points": "section-structure risk partly carried into rewrite (\"format labels\")",
  "effect_vs_A": "none",
  "path_note": "1 tool, same answer"
 },
 {
  "task": "3ff6b7a9",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "M:find",
    "choices": "M:find",
    "risks": "M:risk (restate) (covered by draft)",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "3ff6b7a9",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M:find",
    "risks": "M+S:check/generic",
    "plan": "M:find",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:risk (restate) (covered by draft)",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "I1",
    "decision": "defer_to_execution",
    "source": "r1.risks+r1.observation (haiku)",
    "source_model": "haiku",
    "quality": "REDUNDANT",
    "note": "latest revision <= 2021-01-01 is what A and c2 workers did unaided"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "none",
  "path_note": "context_additions carried the probe value 56,081 (answer leak); exec 5 tools vs A 13"
 },
 {
  "task": "4d51c4bf",
  "arm": "c2_probe_tools",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:dev",
    "risks": "M:dev",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "date-filter",
    "decision": "clarify",
    "source": "r1.choices+r1.risks+r1.observation",
    "source_model": "luna",
    "quality": "CORRECT-CATCH",
    "note": "removes the draft run-date (2026-10-09) 90-day filter; moot here (no date column)"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "none",
  "path_note": "same 1-tool path"
 },
 {
  "task": "4d51c4bf",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:dev",
    "risks": "M+S:find/generic",
    "plan": "N",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M+S:dev/ambig",
    "risks": "S:ambig",
    "plan": "M+S:find/ambig",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right on spurious duplicate/region/90-day points; draft run-date clause left in (harmless, conditional on dates that do not exist)",
  "effect_vs_A": "none"
 },
 {
  "task": "56db2318",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "S:generic (restate)",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "56db2318",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "S:generic (restate)",
    "plan": "N",
    "observations": "NA:none"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "S:wrong/generic",
    "plan": "N",
    "observations": "N"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "5b2a14e8",
  "arm": "c2_probe_tools",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N",
    "risks": "M+S:risk/generic",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [
   {
    "id": "date-meaning",
    "decision": "clarify",
    "source": "r1.choices",
    "source_model": "luna",
    "quality": "HARMFUL-STRICT",
    "note": "invents added-vs-publication distinction (conditional form); no visible effect: d0 found Ruffwear story; d1 checked date format 08/12/22"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "unclear",
  "path_note": "c2 2 delegations vs A 6: brand found at d0 by chance, not by the rewrite"
 },
 {
  "task": "5b2a14e8",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "M:find/check",
    "risks": "M+S:risk/generic",
    "plan": "M:check",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "date-meaning",
    "decision": "clarify",
    "source": "r1.choices (haiku: \"publication or posted date\")",
    "source_model": "haiku",
    "quality": "HARMFUL-STRICT",
    "note": "requires listing/metadata saying \"added\"; orchestrator repeated \"do not use publication date\" in d1-d9; d8 found bacon but hedged \"only if ... displayed date\" -> extra d9"
   }
  ],
  "ignored_points": "WRONG: haiku Ruffwear lead (correct brand) not passed to the worker while brand identification consumed 8 delegations",
  "effect_vs_A": "cost+",
  "path_note": "10 delegations vs A 6; >=1 extra delegation (d9) attributable to the rewrite, rest brand-ID noise"
 },
 {
  "task": "5cfb274c",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "5cfb274c",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "M:find/check",
    "risks": "M+S:risk/check/generic",
    "plan": "M:check",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "5d0080cb",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M:find (restate)",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "5d0080cb",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "M:find",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "S:generic (restate)",
    "plan": "M:find",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "8e867cd7",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M:risk",
    "plan": "M:find",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "8e867cd7",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M:find/risk",
    "plan": "N",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "M:interp (restate)",
    "risks": "M+S:find/wrong",
    "plan": "N",
    "observations": "M+S:find/wrong"
   }
  ],
  "issues": [
   {
    "id": "version-fallback",
    "decision": "defer_to_execution",
    "source": "r2.choices+r2.observation (haiku)",
    "source_model": "haiku",
    "quality": "HARMFUL-STRICT",
    "note": "reverses a reasonable fallback into \"do not substitute an out-of-2022 revision; report limitation\"; latent (main article had a 2022 revision); \"use main article\" part redundant"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "none",
  "path_note": "same revision 1126540422 as A; 12 tools vs 9"
 },
 {
  "task": "a56f1527",
  "arm": "c2_probe_tools",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "S:ambig",
    "risks": "S:ambig/generic",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [
   {
    "id": "edition",
    "decision": "defer_to_execution",
    "source": "r1.choices+r1.risks",
    "source_model": "luna",
    "quality": "HARMFUL-AMBIG",
    "note": "\"check relevant editions; if multiple covers fit report candidates\" for a task that means US Vogue"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "cost+",
  "path_note": "d0 checked UK/India covers, hit tool limit, hedged \"Washington Monument is a possible landmark\" -> extra visual-verification delegation; $0.059 vs A $0.016"
 },
 {
  "task": "a56f1527",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "S:ambig",
    "choices": "M:interp/find",
    "risks": "M+S:find/ambig",
    "plan": "S:ambig",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "S:ambig",
    "risks": "S:ambig",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [
   {
    "id": "edition-ambiguity",
    "decision": "defer_to_execution",
    "source": "r1.choices+r1.observation (haiku); r2.choices/risks (luna)",
    "source_model": "haiku",
    "quality": "HARMFUL-AMBIG",
    "note": "\"Do not assume a country edition\"; analysis took the ambiguity and dropped haiku's default-to-US reading and White-House hint"
   }
  ],
  "ignored_points": "WRONG: haiku default-to-US interpretation and monument hypothesis ignored",
  "effect_vs_A": "hedge+",
  "path_note": "d0 tool_limit (20 vs 16) with \"cannot rule out all other editions\"; no extra delegation"
 },
 {
  "task": "ad37a656",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M:risk",
    "plan": "N",
    "observations": "N"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "ad37a656",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "NA:format",
    "choices": "NA:format",
    "risks": "NA:format",
    "plan": "NA:format",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M:risk",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [],
  "ignored_points": "right; haiku answered in free form (Result/Evidence/Interpretation/Unfinished, pre-solved \"Bravo\"), items unparsed but shown raw to analysis",
  "effect_vs_A": "none"
 },
 {
  "task": "b7f857e4",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M+S:risk/generic",
    "plan": "N",
    "observations": "N"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "b7f857e4",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M+S:risk/generic",
    "plan": "N",
    "observations": "N"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M:interp/find",
    "risks": "M:risk",
    "plan": "M:check",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "bda648d7",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "M:risk (restate) (covered by draft)",
    "plan": "M:find",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "bda648d7",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find (restate)",
    "risks": "M:risk (covered by draft)",
    "plan": "N",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "M+S:find/wrong",
    "risks": "S:ambig/generic",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "I1",
    "decision": "clarify",
    "source": "r2.choices (haiku) + r1.risks (luna)",
    "source_model": "haiku",
    "quality": "REDUNDANT",
    "note": "draft already said \"full city name without abbreviations\"; rewrite example writes the answer \"Saint Petersburg\""
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "none",
  "path_note": "same path; report says \"I expanded St. to Saint\""
 },
 {
  "task": "c3a79cfe",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:interp",
    "risks": "M+S:risk/generic",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right: draft already asks for the closest station",
  "effect_vs_A": "none"
 },
 {
  "task": "c3a79cfe",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "M+S:find/wrong",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "I1",
    "decision": "defer_to_execution",
    "source": "r1.plan+r1.risks (haiku)",
    "source_model": "haiku",
    "quality": "HARMFUL-AMBIG",
    "note": "\"verify continuous single line in 2022 ... if none, explain which evidence prevents deriving the number\" (withholding condition); did not catch the 7-vs-8 miscount itself"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "hedge+",
  "path_note": "d0: \"The answer is 8 if ... There is no single valid answer for all of 2022\"; orchestrator still answered 8 (A/c2 reports also noted the Sept-2022 Yellow Line suspension, more mildly)"
 },
 {
  "task": "c8b7e059",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "S:strict (restate)",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "c8b7e059",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "M:find (restate)",
    "risks": "M+S:risk/generic",
    "plan": "M+S:check/strict",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "S:strict",
    "risks": "S:generic (restate)",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [
   {
    "id": "I1",
    "decision": "defer_to_execution",
    "source": "r2.choices (luna)",
    "source_model": "luna",
    "quality": "HARMFUL-STRICT",
    "note": "SAAM evidence dated <= Aug 2023 required; drove the extra d2"
   },
   {
    "id": "I2",
    "decision": "defer_to_execution",
    "source": "r1.risks+r1.observation (haiku)",
    "source_model": "haiku",
    "quality": "HARMFUL-STRICT",
    "note": "footnote 397 must be verified from full text; d0 hedged, d2 extra; final answer still relied on the indexed snippet"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "cost+",
  "path_note": "3 delegations vs A 2; d0 \"cannot calculate\", d2 resolves rewrite-created gaps; $0.072 vs A $0.080 (A d0 was expensive)"
 },
 {
  "task": "d5141ca5",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "N (restate)",
    "plan": "N",
    "observations": "N"
   }
  ],
  "issues": [],
  "ignored_points": "right (nothing to catch; luna did not foresee the template mechanism)",
  "effect_vs_A": "none"
 },
 {
  "task": "d5141ca5",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "M+S:interp/wrong",
    "risks": "M:risk",
    "plan": "M+S:check/wrong",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "N (restate)",
    "plan": "N",
    "observations": "N"
   }
  ],
  "issues": [
   {
    "id": "navbox-image",
    "decision": "defer_to_execution",
    "source": "r1.risks+r1.observation (haiku)",
    "source_model": "haiku",
    "quality": "CORRECT-CATCH",
    "note": "answer is the {{Thomism}} transclusion date; analysis kept the risk and discarded haiku's wikitext-only choice"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "unclear",
  "path_note": "A found the transclusion unaided at d0; c3 d0 found template creation but not transclusion date; 3 delegations vs A 4 (A orchestrator over-verified)"
 },
 {
  "task": "dd3c7503",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N",
    "risks": "S:wrong",
    "plan": "N",
    "observations": "N"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "dd3c7503",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "S:strict",
    "risks": "M+S:risk/strict",
    "plan": "S:strict",
    "observations": "N"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find/risk",
    "risks": "M:risk",
    "plan": "S:strict",
    "observations": "M:find"
   }
  ],
  "issues": [
   {
    "id": "source-version",
    "decision": "defer_to_execution",
    "source": "r1.choices (haiku) + r2.risks/observation (luna)",
    "source_model": "haiku",
    "quality": "HARMFUL-STRICT",
    "note": "verify compilation by \"compilation information\"; d0 hedged (\"candidate source\"), 2 extra delegations to verify 08/21/2023"
   },
   {
    "id": "temperature",
    "decision": "clarify",
    "source": "r1.choices (haiku, reversed)",
    "source_model": "haiku",
    "quality": "REDUNDANT",
    "note": "anti-withholding fix of haiku's \"do not assume 25 C\"; table states 25 C"
   },
   {
    "id": "volume-units",
    "decision": "clarify",
    "source": "r1.choices (haiku)",
    "source_model": "haiku",
    "quality": "REDUNDANT",
    "note": "US 16 cups/gallon used by all workers"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "cost+",
  "path_note": "3 delegations vs A 1; $0.063 vs $0.015"
 },
 {
  "task": "de9887f5",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:find/risk",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "de9887f5",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "N",
    "choices": "M:find",
    "risks": "S:ambig/generic",
    "plan": "N",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:find (restate)",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "df6561b2",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "S:generic",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "df6561b2",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "N (restate)",
    "risks": "S:generic",
    "plan": "N",
    "observations": "NA:none"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "M:find",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "e2d69698",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "N (restate)",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "e2d69698",
  "arm": "c3_probe_multi",
  "status": "rewritten",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "N (restate)",
    "plan": "N",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_haiku",
    "understanding": "S:wrong",
    "choices": "S:wrong",
    "risks": "S:generic",
    "plan": "N",
    "observations": "NA:none"
   }
  ],
  "issues": [
   {
    "id": "scope",
    "decision": "clarify",
    "source": "r1.choices+r1.observation (luna) vs r2.choices (haiku, wrong)",
    "source_model": "both",
    "quality": "REDUNDANT",
    "note": "fixes cutoff to S44; every arm's worker used S44 unaided; analysis correctly rejected haiku's wrong cutoff"
   }
  ],
  "ignored_points": "-",
  "effect_vs_A": "none",
  "path_note": "uniqueness-verification loop in all arms (A 4, c2 2, c3 3 delegations)"
 },
 {
  "task": "ed58682d",
  "arm": "c2_probe_tools",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:interp/find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 },
 {
  "task": "ed58682d",
  "arm": "c3_probe_multi",
  "status": "no_issues",
  "respondents": [
   {
    "id": "r1",
    "model": "gen_haiku",
    "understanding": "M:find",
    "choices": "M:interp/find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   },
   {
    "id": "r2",
    "model": "gen_luna",
    "understanding": "N",
    "choices": "M:find",
    "risks": "M:risk",
    "plan": "N",
    "observations": "M:find"
   }
  ],
  "issues": [],
  "ignored_points": "right",
  "effect_vs_A": "none"
 }
]
```
