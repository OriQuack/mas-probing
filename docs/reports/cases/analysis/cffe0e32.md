# cffe0e32 (Secret Santa, level 1) 심층 분석

## 4.1 Task와 의도된 풀이

- **질문**: 12명이 각자 다른 한 명에게 선물하도록 배정됨. 선물은 11개만 전달됐고 각 선물은 받는 사람의 관심사 하나에 맞음. "who did not give a gift?"
- **문서 내용** (모든 run이 같은 내용을 읽음): 직원 목록, "Gift Assignments" 표(header `Giftee | Recipient`, 12행), 12명의 profile(관심사 3개), 선물 11개 목록.
- **gold = Fred**. annotator 풀이: 선물을 관심사에 맞춰 받는 사람 11명을 정함(Raku guide → Fred(Perl), chisel set → Jun 등). 선물을 못 받은 사람은 Rebecca. "Find who was supposed to give Rebecca a gift (Fred)". 즉 표의 행 `Fred | Rebecca`를 **첫 column = 주는 사람, 둘째 column(`Recipient`) = 받는 사람**으로 읽음.
- **틀릴 수 있는 곳**
  1. 선물-관심사 대응(Galileo ↔ Miguel/Lucy, Raku ↔ Fred/Jun, War and Peace film ↔ Perry/Alex 등). 실제로는 모든 run이 같은 대응(받지 못한 사람 = Rebecca)에 도달했음. 이 단계에서 틀린 run은 없음.
  2. **표 방향**. header `Giftee | Recipient`는 글자 그대로 보면 두 column이 모두 "받는 사람"임. 첫 column을 받는 사람으로 읽으면 `Rebecca | Micah`에서 Micah가 주는 사람이 되어 답이 Micah가 됨. 두 읽기 모두 12명의 순열이라 문서 내부에서 방향을 검증할 방법은 없음. 의도된 읽기를 지지하는 근거: 둘째 column에 명시된 `Recipient`라는 label, 왼쪽→오른쪽 = 주는 사람→받는 사람이라는 관례, task의 "each ... was assigned one other employee ... to present with a gift"(배정표 = 주는 사람별 대상). `Giftee`는 "Gifter"의 오기로 보는 것이 자연스러움.
  3. 받지 못한 사람(Rebecca)과 주지 않은 사람(Fred)을 혼동하는 것. 실제로 이 혼동을 한 run은 없음.
- 실패한 4개 run은 모두 2번 지점(표 방향)에서 갈렸고, 1번과 3번에서는 모두 맞았음.

## 4.2 Run별 경로

### 정답 run 묶음 A: delegation 1번으로 끝남 (8 run: v5 fresh + v6 draft 계열 7)
- **v6 draft**(s4/rA restore의 공통 draft, `v6__fresh.md` L54): "Read the attached DOCX and determine which of the twelve employees did not give a gift. Extract the employee names, assignments (if present), ... Match gifts to recipients' interests and infer the giver, explaining any ambiguity."
  - "assignments ... infer the giver"라는 틀 때문인지, worker는 표를 주는 사람→받는 사람으로 바로 읽었음.
- **v5__fresh**: draft는 "all eleven gifts with any stated giver/recipient clues ... matching the gifts to recipients' interests and assignments"(L45). worker가 header를 언급하지 않고 Giver/Recipient 표로 바꿔 적고 Fred를 보고함(L171-207). 유일한 단서는 "A programming guide could broadly suit Jun’s JavaScript interest"(Raku). orchestrator가 바로 finish(L258).
- **v6__fresh** (L171-206): "Fred’s assigned recipient, Rebecca ... none of the eleven gifts matches". header 언급 없음. 바로 finish(L265).
- **s4__A_none_r0** (L171 전후): "The document lists these assignment pairs, interpreted as giver → recipient" — 해석임을 밝혔지만 header 문제는 말하지 않음. orchestrator가 바로 finish(L252).
- **rA__A_none_r0 / r1**: 둘 다 "The assignment table says **Fred → Rebecca**" 식으로 header 언급 없이 Fred. 바로 finish(r0 L212, r1 L252).
- **s4__c2 / rA__c2 r0 / rA__c2 r1** (status no_issues라 draft 그대로): worker가 "The document’s assignment table is giver → recipient"(rA c2 r0 L281), "Assignments (giver → recipient)"(rA c2 r1 L281)로 적고 Fred. 모두 delegation 1번에 finish.
- **성공 요인**: draft가 "assignments"와 "infer the giver"를 함께 말해 worker가 배정표를 주는 사람별 목록으로 읽었고, 보고에 header 문제가 드러나지 않아 orchestrator가 re-check를 하지 않았음. v6 draft를 그대로 실행한 6 run이 모두 이 경로였음(6/6).

### 정답 run 묶음 B: v7 draft 계열, re-check 후 Fred (2 run)
- **v7 draft**(`rBfresh__base_r0.md` L53): "Identify ... the eleven gifts and any clues about which recipient each gift matches. Determine who did not give a gift. ... Be careful: each employee was assigned one other employee, so exclude self-assignments if the clues imply gift-recipient mapping."
  - 배정표를 "assignments"로 부르지 않음. 그래서 worker가 표를 스스로 해석해야 했고, 4 run 모두 첫 보고에서 방향 가정을 드러냈음.
- **rBfresh__base_r0**
  - d0 보고(L180 전): "The table’s heading reads “Giftee | Recipient,” so the role of its first column is not perfectly labeled; the conclusion assumes it identifies the giver".
  - orchestrator가 re-check를 맡김(L198): "do not assume column semantics if the document defines them otherwise".
  - re-check 보고(L413 전): "**Fred is only a conditional answer** ... the document does not clearly establish that direction".
  - finish(L437): "This is the intended inference for the requested giver, although the table headings leave the direction less than fully explicit." → Fred.
- **rB__A_none_r0**
  - d0 보고: "This treats the table’s first column as the employee assigned to the recipient in the second column, consistent with the task’s description". header는 직접 언급하지 않았음.
  - 그런데도 orchestrator가 re-check를 맡김(L186): "the conclusion depends on interpreting the assignment table as giver-to-recipient. Verify that table orientation".
  - re-check 보고(L377 전): "**Fred is a conditional answer, not a conclusion established by the document’s exact wording**".
  - finish(L399): "Although the column label is ambiguous, the task’s intended giver-to-recipient interpretation supports Fred."
- 두 run 모두 re-check 보고가 "Fred가 조건부 답"이라는 Fred 중심 표현이었고, finish에서 task의 의도를 근거로 Fred를 골랐음.

### 정답 run: rA__c3_probe_multi_r1 (rewrite됨)
- rewrite(L324): "Inspect the assignment table's labels ... use the best-supported reading. If the document does not resolve the column direction, state that ambiguity and give the best-supported answer."
- context_additions: header 관찰만 넘김("A reviewer reported seeing a table header “Giftee | Recipient” ... unverified").
- d0 보고(L513-566): "**Fred is the best-supported answer** ... Reading the explicitly labeled right-hand **Recipient** column as the person assigned to receive the gift makes the first-column name the giver ... the column wording leaves some ambiguity". Micah라는 이름은 꺼내지 않았음.
- orchestrator가 re-check 없이 finish(L568): "the best-supported reading treats Fred as the giver ... though the table’s labels leave some ambiguity."

### 실패 run 1: s4__c3_probe_multi_r0 → "Ambiguous: Fred if Giftee is giver; Micah if Recipient is giver."
- **refiner**(r8)
  - haiku probe의 risks: "The table headers are contradictory ... If column 1 is the recipient, the answer flips to Micah"(L171). 같은 probe의 choices는 "Treat the column labeled "Recipient" as the person receiving the gift, so Rebecca's giver is Fred ... This follows the header's plain meaning."로 올바른 해석을 이미 골랐음.
  - analysis(L310): issue `table_direction`, defer_to_execution. resolution: "If the document does not resolve the column direction, state the ambiguity and both resulting names rather than silently assuming a direction."
  - rewrite(L330/L336): "do not assume a direction from the column order alone ... If the document itself leaves the column direction unresolved, say which specific ambiguity prevents a single answer and **give the result under each possible reading**."
  - context_additions: "opposite column readings could produce Fred or Micah as the answer".
- **d0 보고**(L516): "Rebecca received no gift, but the document does not establish which employee was assigned to give her one. Under one reading the answer is **Fred**; under the reverse reading it is **Micah**." 지시대로 두 읽기를 모두 냈음.
- **d1 re-check**(L551): "Do not infer direction from column order alone or from general convention ... Report ... whether one giver is justified or both readings remain possible."
  - 관례를 근거로 쓰지 못하게 해서 의도된 읽기의 근거 하나를 막았음.
- **re-check 보고**(L751): "Either **Fred** or **Micah** could be the missing giver ... choosing one giver is not justified."
- **finish**(L777-782): "Ambiguous: Fred if Giftee is giver; Micah if Recipient is giver." 조건 표기 자체는 맞음(둘째 column이 주는 사람이면 `Rebecca | Micah`에서 Micah).
- **결정적 실패 지점**: rewrite(L330)가 "give the result under each possible reading"을 지시하고 context_additions가 Fred/Micah 두 답을 미리 알려 준 것. 이 뒤로 worker 보고는 한 번도 단일 답을 내지 않았음.

### 실패 run 2: rA__c3_probe_multi_r0 → "Fred or Micah"
- **refiner**(r9)
  - haiku probe의 choices(L161): "The gift table headers are "Giftee | Recipient", which is ambiguous. Both column readings give a valid 12-to-12 pairing, so I would test which reading makes the gifts match interests."
    - 방법이 틀렸음. 선물-관심사 대응은 표 방향과 무관하므로 이 test로는 방향을 정할 수 없음.
  - analysis(L312): issue `assignment_direction`, defer. resolution은 "do not choose a column reading merely because it makes more gifts fit ... If the source does not resolve direction, state the ambiguity and give the best-supported result." haiku의 잘못된 방법은 막았음.
  - 둘째 issue `gift_matching`, defer: "do not force an arbitrary match or assume one-to-one recipient coverage unless the document supports it".
  - rewrite(L332): "Use the document's labels and wording, together with the task's description ... to establish assignment direction ... If the source leaves multiple results consistent, give the best-supported result and state the unresolved ambiguity."
  - context_additions(L342): "that either column reading yields a valid pairing but different givers for the same recipient". 관찰이 아니라 결론을 넘긴 것임(r9 규칙 위반).
- **d0 보고**(L555): "**Best-supported answer: Fred did not give a gift.** ... reading the explicitly labeled **Recipient** column as the assigned-to person makes Fred Rebecca’s giver." 그런데 "Direction ambiguity" 절에서 "If the table were instead read in the opposite direction, **Micah** would be paired as Rebecca’s giver"라고 대안 이름을 명시했음.
- **d1 re-check**(L665-677): "assess the ordinary meaning of the labels in context and the task wording, without using which interpretation makes the gift matching work ... if not, confirm the viable alternative and ambiguity."
- **re-check 보고**(L787): "The DOCX does not resolve the direction ... does not establish whether **Fred** or **Micah** was assigned to give Rebecca a gift." 대안 쪽으로 기울지는 않았지만 Fred를 조건부 답으로 두지도 않았음.
- **finish**(L809-814): "Fred and Micah remain equally consistent; there is no supported basis to prefer one." → "Fred or Micah".
- **결정적 실패 지점**: d1 finish(L809). d0에서 Fred가 best-supported로 나왔고, re-check 보고 뒤에도 orchestrator는 rB A처럼 Fred를 고를 수 있었음. re-check 자체는 rB A와 fresh에서도 있었고 그 run들은 회복했음.
- 이 run의 d0 보고가 Micah를 명시한 것은 context_additions의 "either column reading yields ... different givers"와 연결됨. 같은 rewrite 계열인 r1은 Micah를 말하지 않았고 re-check도 없었음.

### 실패 run 3: rB__c2_probe_tools_r0 → "Cannot be determined"
- **refiner**(r9): luna probe는 tool을 쓰지 않았고 문서를 보지 않았음. plan의 "Identify the employee left without a gift assignment"를 analysis가 목표 혼동으로 잡았음.
  - analysis(L182) evidence: "The instruction’s closing phrase instead asks for the employee left without a gift assignment". 이 문구는 draft가 아니라 probe의 plan에 있는 것이라 근거를 잘못 짚었음.
  - rewrite(L202-208): "Do not mistake the recipient who received no gift for the employee who did not give one unless the evidence establishes they are the same person." 표 방향은 언급하지 않음.
- **d0 보고**(L304): "**Fred did not give a gift**, assuming the assignment table’s left-hand name is the giver ... The document’s table header says “Giftee | Recipient”; I have interpreted its left-hand names as the assigned givers".
- **d1 re-check**(L327-339): "Determine whether Fred is actually the giver assigned to Rebecca, or whether the header means the reverse."
- **re-check 보고**(L498): "the missing giver cannot be uniquely identified from this document." 사전에서 giftee를 검색함(Cambridge: "a person who is given something as a gift").
- **finish**(L558-563): "it cannot identify the missing giver" → "Cannot be determined".
- **결정적 실패 지점**: finish(L558). 같은 v7 draft의 A와 fresh는 같은 re-check와 비슷한 보고 뒤에 Fred를 골랐음.

### 실패 run 4: rB__c3_probe_multi_r0 → "Micah"
- **refiner**(r9)
  - haiku(r2)의 choices(L193): "Under the reading where the second column is the recipient, the answer is Fred ... Under the reverse reading ... Micah. I would state both and flag the header as ambiguous."
  - analysis(L315): issue `direction-of-assignment`, **clarify**. resolution: "Resolve the table direction from the document; do not present alternative answers unless the document genuinely leaves the direction indeterminate."
  - rewrite(L335/L341): "Resolve the direction of any assignment table from its headers and structure in light of the task wording. If the direction remains unclear, give the result best supported by the document and briefly state the basis."
  - context_additions: header와 `Fred | Rebecca` 행이라는 관찰만 넘김.
- **d0 보고**(L449-457): "**Result: Fred** is the best-supported answer ... the second column is explicitly headed “Recipient,” and this row-based reading fits the task’s giver-to-recipient framing. **Unfinished:** The header wording leaves some ambiguity about direction".
  - 의도된 해석과 그 근거를 정확히 냈음.
- **d1 re-check**(L485-497): "Is the employee named first in a row the assigned giver or the recipient? ... If genuinely indeterminate, state that and the best-supported reading."
- **re-check 보고**(L615-621): "Its best-supported reading of the first column is **recipient**, because the header is **“Giftee”** ... “Giftee” ordinarily means the person receiving the gift, so the header does **not** support treating Fred as the giver". re-check worker가 반대 해석 쪽으로 기울었음.
- **finish**(L645-650): "“Giftee” best supports reading the first column as the recipient; under that reading, the row “Rebecca | Micah” makes Micah the likely giver." → Micah.
- **결정적 실패 지점**: d1 re-check(L485). 맞는 d0 결과(Fred + 근거)를 확인하겠다고 다시 맡겼고, re-check 보고가 `Giftee` label을 `Recipient` label보다 우선해 반대 해석을 택했으며, finish가 그것을 따랐음.

## 4.3 Cause codes (실패 run)
| run | primary | secondary | 요지 |
|---|---|---|---|
| s4__c3_probe_multi_r0 | I-REWRITE | O-RECHECK, O-FINISH | rewrite가 "result under each possible reading"을 요구함. context_additions가 Fred/Micah를 미리 제시함 |
| rA__c3_probe_multi_r0 | O-FINISH | O-RECHECK, I-REWRITE(부차) | d0의 "Best-supported: Fred"를 re-check한 뒤 hedge로 끝냄. context_additions의 결론("either reading valid")이 대안을 부각했음 |
| rB__c2_probe_tools_r0 | O-FINISH | O-RECHECK | A와 같은 경로를 거쳤고 finish에서 비답변을 택함. rewrite는 방향과 무관 |
| rB__c3_probe_multi_r0 | O-RECHECK | O-FINISH | 맞는 d0 결과를 re-check한 보고가 반대 해석을 택했고 finish가 따랐음 |

## 4.4 사전 예방 가능성 (d0 instruction 수정)
- **A-equivalent 실패는 없음**
  - v6 draft를 그대로 실행한 run 6/6 정답: s4 A, rA A ×2, no_issues c2 ×3.
  - v7 draft를 그대로 실행한 run 2/2 정답: rB A, rBfresh.
  - 따라서 task_level은 NA.
- **s4 c3: YES-FAITHFUL (high)**
  - rewrite가 task의 단일 답 요구를 "각 읽기별 결과"로 바꿨음.
  - draft를 그대로 보냈다면 v6 base rate(6/6)대로 맞았을 가능성이 높음.
  - 최소 수정: rewrite를 하지 않거나, 아래 rA c3 r0의 해석 문장을 넣음.
- **rA c3 r0: YES-TASKTEXT (med)**
  - instruction은 task에 충실했지만, 방향 문제를 부각하고 풀지 않은 채 넘겼음.
  - refiner는 실행 전에 probe의 tool 관찰로 header를 알았음(hindsight 아님). 그래서 아래 해석을 정할 수 있었음:
    > "Read the assignment table so that the column labelled “Recipient” is the person receiving the gift and the other column is the employee assigned to give to them, as the task describes (each employee was assigned another employee to present with a gift); answer with that single employee."
  - 이 문장은 답 이름을 담지 않으며, task 문장과 문서 label에서 나옴.
  - 신뢰도가 med인 이유: 실패의 직접 원인은 orchestrator의 re-check와 finish임. d0 수정은 worker 보고의 caveat를 줄여 re-check를 덜 일으킬 뿐임.
- **rB c2: NO**
  - 같은 v7 draft의 A와 fresh도 같은 re-check를 거쳤음. 갈린 곳은 finish임.
  - c2 probe는 문서를 보지 않아 refiner가 header를 알 수 없었음.
  - "배정표를 주는 사람별 목록으로 읽어라"는 일반 문장이 caveat를 줄였을 수는 있음(v6 draft 6/6이 그 근거). 하지만 rB A는 caveat가 약한데도 re-check를 했음. 그래서 instruction 수정으로 막을 수 있었다고 보지 않음.
- **rB c3: YES-TASKTEXT (low)**
  - refiner는 header를 알았고 clarify까지 했지만 "If the direction remains unclear ..."로 남겨 두었음.
  - 위 해석 문장을 확정했다면 d0 보고에 "Unfinished: ... ambiguity"가 붙지 않았을 가능성이 있음.
  - 그러나 d0 보고는 이미 Fred와 올바른 근거를 냈고, 실패는 orchestrator의 re-check에서 생겼음. 그래서 low.
- **noise에 대한 판단**
  - v7 계열 4 run은 모두 re-check를 거쳤고 finish가 2/4로 갈렸음(1 rep).
  - refiner arm의 rB 실패 2건은 A와 같은 위험 경로에서 생긴 결과라, refiner 때문인지 noise인지 구별할 수 없음.

## 4.5 Refiner 기록

### s4__c2_probe_tools_r0 (r8, no_issues)
- **probe (luna, tool 0)**
  - understanding: "employee whose assigned recipient received no gift"(정확).
  - choices / risks / plan: 선물 중복 대응 같은 일반적인 내용.
  - header 문제는 언급하지 않음.
- issue 없음. 결과는 A와 같음(정답, d1 finish). effect none.

### s4__c3_probe_multi_r0 (r8, rewritten) — 실패
- **r1 = haiku (tool 1: read_file로 문서 전체를 읽음)**
  - understanding: Rebecca가 선물을 못 받았고 표에서 짝지어진 사람을 찾는다고 함. **답까지 미리 말함**.
  - choices: "Treat the column labeled "Recipient" as the person receiving the gift, so Rebecca's giver is Fred" → (a) **올바른 해석을 고름**.
  - risks: "The table headers are contradictory ... the answer flips to Micah" → (c) 실제 실패 원인을 예견함. 동시에 (b) 이미 풀 수 있는 모호함을 부각함.
  - plan: "Report Fred, and state that Micah is the answer only if the first column is read as the recipient."
- **r2 = luna (tool 1: 파일 크기만 확인)**
  - 모든 항목이 일반적임. observation은 "exists ... 17,525 bytes; I have not read its contents yet"로 무의미함.
- **issue `table_direction`**
  - source: r1.risks + r1.observation(tool read).
  - decision: defer_to_execution.
  - quality: **HARMFUL-AMBIG**. resolution이 "state the ambiguity and both resulting names"였고, rewrite가 이를 "give the result under each possible reading"으로 옮겼음. r1.choices에 있던 올바른 해석은 쓰지 않았음.
  - analysis evidence에는 "Micah if “Rebecca | Micah” means Rebecca gives to Micah"라는 방향 오기도 있음.
- context_additions가 Fred/Micah 두 답을 worker에게 미리 알려 줌.
- effect_vs_A: **hurt**. 같은 draft의 A-equivalent는 6/6 정답이었음.
- probe 신호 사용: 실패 원인(방향)을 probe가 정확히 짚었음. analysis는 그 신호를 "풀어야 할 문제"가 아니라 "답을 둘로 나누는 조건"으로 사용했음.

### rA__c2_probe_tools_r0 / r1 (r9, no_issues)
- **luna probe, tool 0**
  - 두 run 모두 일반적인 내용.
  - r1의 choices "I would not assume the recipient’s assigned giver is the person who gave that item"은 (b) 이상한 해석(배정된 사람이 주는 사람이 맞음)이지만 analysis가 채택하지 않았음.
- issue 없음. 두 run 모두 정답, d1 finish. effect none.

### rA__c3_probe_multi_r0 (r9, rewritten) — 실패
- **r1 = haiku (tool 1, 문서 읽음)**
  - understanding: "12 giver→recipient assignments"(맞음).
  - choices: (b) "Both column readings give a valid 12-to-12 pairing, so I would test which reading makes the gifts match interests. I would not assume the header is correct."
    - 방향과 무관한 test를 제안했으므로 잘못된 방법임.
    - 이름 앞뒤 공백을 지적한 것은 무해함.
  - risks: (c) "The header inversion could flip the answer." 그리고 Galileo / Raku / War and Peace의 중복 대응.
  - plan: 두 읽기를 모두 test한다는 계획.
- **r2 = luna (tool 0)**
  - choices: "Treat a listed assignment as the intended giver-to-recipient link." → (a) 올바른 해석.
  - risks: "Confusing a gift’s recipient with its giver could lead to the wrong name."
- **issue `assignment_direction`**
  - source: r1.choices / r1.risks + r1.observation.
  - decision: defer_to_execution.
  - quality: **OTHER (HARMFUL-AMBIG 경향)**. rewrite 문장 자체는 faithful함("best-supported result"). 하지만 r2.choices의 올바른 해석으로 정하지 않고 방향을 열린 문제로 남겼음.
  - "do not choose a column reading merely because it makes more gifts fit"는 r1의 잘못된 방법을 막은 맞는 처리임.
- **issue `gift_matching`**
  - source: r1.choices / r1.risks, r2.risks.
  - decision: defer.
  - quality: **HARMFUL-STRICT (경미)**. "do not ... assume one-to-one recipient coverage unless the document supports it"는 task가 이미 주는 1:1 구조를 의심하게 만드는 문장임. 실제 실행에는 영향이 보이지 않았음.
- **context_additions**: "either column reading yields a valid pairing but different givers for the same recipient". 결론을 전달한 것(r9 규칙 위반)이고, d0 보고의 Micah 언급으로 이어졌음.
- effect_vs_A: **hurt (likely)**.
  - 같은 draft의 A는 header 문제를 꺼내지 않고 d1에서 끝났음.
  - 이 run은 d0 보고가 대안 이름을 명시해 re-check와 hedge로 이어졌음.
  - 다만 같은 계열 r1은 정답이라 확률적인 효과임.
- probe 신호: 실패 원인을 예견했음. 올바른 해석(r2.choices)도 probe 안에 있었지만 analysis가 쓰지 않았음.

### rA__c3_probe_multi_r1 (r9, rewritten) — 정답
- **r1 = haiku (tool 1)**
  - choices: "Read the table's "Giftee | Recipient" header literally: "Recipient" is the person receiving the gift, so the "Giftee" column is the giver." → (a) 올바른 해석. 이어서 "I would test the other reading too"라고 함.
  - risks: 방향(c), 중복 대응.
  - plan: python-docx로 parse하고 두 방향을 모두 test.
- **r2 = luna (tool 0)**: 일반적인 내용.
- **issue `i1`**
  - source: r1.risks + observation.
  - decision: defer_to_execution.
  - quality: **OTHER**. 풀 수 있는 모호함을 풀지 않고 넘겼지만 "give the best-supported answer"를 명시했고 결과는 정답이었음.
- context_additions: header 관찰만 전달(규칙 준수).
- effect_vs_A: none (A와 같은 정답, d1 finish).
- r0과의 차이: context_additions에 결론이 없었고, d0 보고가 Micah를 명시하지 않았음.

### rB__c2_probe_tools_r0 (r9, rewritten) — 실패
- **r1 = luna (tool 0, 문서를 보지 않음)**
  - understanding / choices: 일반적인 내용. draft의 self-assignment 문구를 반복함.
  - risks: 선물 중복.
  - plan: "Identify the employee left without a gift assignment" — 받지 못한 사람으로 읽힐 수 있는 표현(b).
  - header 문제는 언급하지 않음.
- **issue `1`**
  - source: r1.plan. analysis는 이를 "instruction의 문구"라고 잘못 귀속했음.
  - decision: clarify.
  - quality: **REDUNDANT**. 모든 run의 worker가 이미 주는 사람을 답으로 냈음.
  - "unless the evidence establishes they are the same person"은 증거 기준을 약간 강조하는 표현이지만 영향은 확인되지 않음.
- foresaw_failure: false (방향 문제를 몰랐음).
- effect_vs_A: **unclear**. A와 같은 re-check 경로였고 finish만 달랐음(1 rep).

### rB__c3_probe_multi_r0 (r9, rewritten) — 실패
- **r1 = luna (tool 0)**
  - choices: "if the clues do not uniquely determine a mapping, report the ambiguity rather than force an answer" → (b) 비답변 경향. analysis는 채택하지 않았음.
  - plan: "employee left without a gift-giving assignment".
- **r2 = haiku (tool 1, 문서 읽음)**
  - understanding: "naming that recipient's assigned giver from the table"(맞음).
  - choices: 두 읽기와 그에 따른 Fred/Micah를 제시하고 "I would state both" → (b). (c) 실패 원인을 예견함.
  - risks: 방향이 주된 risk. Rebecca가 선물을 못 받았다는 사전 확인(맞음).
  - plan: "Resolve the header direction ... explain the choice from the task wording" 그리고 "Report the non-giver under each reading".
- **issue `direction-of-assignment`**
  - source: r2.choices / r2.risks + r2.observation, r1.plan.
  - decision: clarify.
  - quality: **OTHER**. 목표(주는 사람) 부분은 REDUNDANT임. 방향 부분은 "do not present alternative answers"로 복수 답을 막은 점은 맞음. 하지만 "If the direction remains unclear, give the result best supported"로 남겨 방향을 확정하지 않았음.
- context_additions: 관찰만 전달.
- d0 worker는 이 instruction으로 Fred와 올바른 근거를 냈음. 실패는 그 뒤 orchestrator의 re-check에서 생겼음.
- effect_vs_A: **unclear** (rB A도 같은 re-check를 거쳤음).
- probe 신호: 실패 원인을 예견했음. 하지만 analysis가 해석을 확정하지 않았고, d0 보고에 남은 caveat가 orchestrator re-check의 계기가 됐음.

## 이전 분석과의 대조
- **stage34 §4.1 (s4 c3)**: 단계 1–7은 trace와 일치함. 덧붙일 점 두 가지:
  - haiku probe의 **choices는 Fred 해석을 이미 골랐고**, Micah는 risks에만 있었음. analysis가 올바른 choice 대신 risk를 "두 이름 모두 보고"로 확대했음.
  - "refiner가 들여옴"은 맞음. 다만 d1에서 orchestrator가 "관례로 추론하지 마라"는 re-check를 다시 맡긴 것도 hedge를 굳혔음.
- **r9v7 §6 / §10.1 (rA c3 r0)**: "첫 보고는 'Best-supported answer: Fred' → re-check → 'Fred or Micah'"와 "context_additions에 결론이 섞였고 r1은 관찰만 넘겼음"은 확인됨.
  - 덧붙일 점: d0 보고가 Micah를 명시한 것이 re-check의 직접 계기로 보임. r1의 d0 보고는 Micah를 말하지 않았고 re-check도 없었음.
- **r9v7 §7.1 (phase B "네 run이 같은 흐름, 마지막 판단만 달랐음")**: 흐름이 같다는 데는 동의함. **"확인 보고는 모두 '문서가 방향을 분명히 정하지 않는다'였음"에는 부분적으로 동의하지 않음.**
  - fresh와 A의 re-check 보고: "Fred is only/a conditional answer"(Fred 중심).
  - c2의 re-check 보고: 중립("cannot be uniquely identified").
  - c3의 re-check 보고: "Its best-supported reading of the first column is **recipient**"로 반대 해석 쪽.
  - 마지막 판단은 re-check 보고가 어느 쪽으로 기울었는지와 일치했음. 그래서 "finish만의 문제"라기보다 re-check 보고의 framing과 finish가 함께 결과를 정했음.
  - re-check instruction도 run마다 달랐음. fresh는 "do not assume column semantics", c2는 "or whether the header means the reverse", c3는 "Is the employee named first ... the assigned giver or the recipient?".
- **v6 draft와 v7 draft의 차이 (이전 report에 없는 관찰)**
  - v6 draft("assignments (if present) ... infer the giver")에서는 6/6 run의 worker가 방향을 묻지 않았고 re-check도 0이었음.
  - v7 draft("any clues about which recipient each gift matches ... exclude self-assignments")에서는 4/4 run이 방향 caveat를 냈고 re-check도 4/4였음.
  - orchestrator system prompt는 날짜 줄 외에 같음. 즉 draft 문구가 re-check 빈도에 영향을 줬을 가능성이 있음(표본이 작음).

```json
{
 "task": "cffe0e32", "gold": "Fred",
 "summary": "All 15 runs found that Rebecca was the recipient left without a gift. The four failures all came from the direction of the assignment table headed 'Giftee | Recipient'. In s4 c3 the r8 rewrite asked for the result under each reading. In the r9 runs the orchestrator re-checked a correct d0 result and then hedged, refused to answer, or took the reverse reading. No A-equivalent run failed (v6 draft 6/6, v7 draft 2/2), although the v7 A runs also went through the same risky re-check.",
 "runs": [
  {"run": "v5__fresh", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "Worker read the table silently as giver->recipient; finished at d1."},
  {"run": "v6__fresh", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "Shared v6 draft ('assignments (if present) ... infer the giver'); no header caveat; finished at d1."},
  {"run": "s4__A_none_r0", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "'interpreted as giver -> recipient' was stated but the orchestrator finished at d1."},
  {"run": "s4__c2_probe_tools_r0", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "no_issues; same as A."},
  {"run": "s4__c3_probe_multi_r0", "ok": false, "answer": "Ambiguous: Fred if Giftee is giver; Micah if Recipient is giver.", "primary_cause": "I-REWRITE", "causes": ["I-REWRITE", "O-RECHECK", "O-FINISH"], "failure_point": "Rewrite (L330): 'give the result under each possible reading'; context_additions named Fred/Micah; d0 report gave both (L516); the re-check banned convention (L551); the finish hedged (L777).", "preventable": "YES-FAITHFUL", "fix": "Send the draft unchanged, or: 'Read the assignment table so that the column labelled Recipient is the person receiving the gift and the other column is the employee assigned to give to them, as the task describes; answer with that single employee.'", "confidence": "high", "notes": "The haiku probe's choices already chose the Fred reading; the analysis turned its risk into a two-answer condition."},
  {"run": "rA__A_none_r0", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "d1 finish, no header mention."},
  {"run": "rA__A_none_r1", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "d1 finish, no header mention."},
  {"run": "rA__c2_probe_tools_r0", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "no_issues."},
  {"run": "rA__c2_probe_tools_r1", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "no_issues."},
  {"run": "rA__c3_probe_multi_r0", "ok": false, "answer": "Fred or Micah", "primary_cause": "O-FINISH", "causes": ["O-FINISH", "O-RECHECK", "I-REWRITE"], "failure_point": "d0 gave 'Best-supported answer: Fred' but named Micah as the alternative (L555); the orchestrator re-checked (L665); the re-check said indeterminate (L787); the finish hedged (L809).", "preventable": "YES-TASKTEXT", "fix": "Read the assignment table so that the column labelled Recipient is the person receiving the gift and the other column is the employee assigned to give to them, as the task describes (each employee was assigned another employee to present with a gift); answer with that single employee.", "confidence": "med", "notes": "context_additions passed the conclusion 'either column reading yields a valid pairing but different givers' (r9 rule violation). The sibling r1, whose context held only the observation, finished correctly at d1."},
  {"run": "rA__c3_probe_multi_r1", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "Rewrite deferred the direction but required a best-supported answer; d0 gave Fred without naming Micah; no re-check."},
  {"run": "rBfresh__base_r0", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "v7 draft; d0 flagged the header; re-check said 'Fred is only a conditional answer'; the finish chose the intended reading."},
  {"run": "rB__A_none_r0", "ok": true, "answer": "Fred", "primary_cause": null, "causes": [], "failure_point": null, "preventable": null, "fix": null, "confidence": null, "notes": "Re-checked although the d0 caveat was mild; the finish chose 'task's intended giver-to-recipient interpretation'."},
  {"run": "rB__c2_probe_tools_r0", "ok": false, "answer": "Cannot be determined", "primary_cause": "O-FINISH", "causes": ["O-FINISH", "O-RECHECK"], "failure_point": "Finish (L558) after a re-check (L327) whose report said the giver 'cannot be uniquely identified' (L498); A on the same draft finished Fred after a similar re-check.", "preventable": "NO", "fix": null, "confidence": null, "notes": "The rewrite only clarified giver vs recipient (redundant); the c2 probe never read the file."},
  {"run": "rB__c3_probe_multi_r0", "ok": false, "answer": "Micah", "primary_cause": "O-RECHECK", "causes": ["O-RECHECK", "O-FINISH"], "failure_point": "Re-check (L485) of a correct d0 result ('Result: Fred ... second column is explicitly headed Recipient', L449); the re-check report preferred the 'Giftee' label (L615); the finish followed it (L645).", "preventable": "YES-TASKTEXT", "fix": "Resolve the direction in the instruction instead of leaving 'if unclear': the column labelled Recipient is the receiver, and the other column is the assigned giver, per the task's description.", "confidence": "low", "notes": "The refiner knew the header from the probe; the clarify resolution stopped at 'if the direction remains unclear, best supported'."}
 ],
 "refine": [
  {"run": "s4__c2_probe_tools_r0", "status": "no_issues", "probe_items": {"understanding": "correct target (giver of the unmatched recipient)", "choices": "generic", "risks": "generic gift overlap", "plan": "generic", "observations": "none"}, "issues": [], "foresaw_failure": false, "effect_vs_A": "none", "note": ""},
  {"run": "s4__c3_probe_multi_r0", "status": "rewritten", "probe_items": {"understanding": "haiku: Rebecca unmatched, giver from table", "choices": "haiku: 'Recipient' column = receiver, so Fred (correct, (a)); luna generic", "risks": "haiku: header contradiction flips to Micah ((c) foresaw, (b) amplified a resolvable ambiguity)", "plan": "haiku: report Fred, mention Micah as conditional", "observations": "haiku read the whole docx; luna only checked the file size"}, "issues": [{"id": "table_direction", "source": "r1.risks + r1.observation", "decision": "defer_to_execution", "quality": "HARMFUL-AMBIG", "note": "Resolution 'state ... both resulting names' became 'give the result under each possible reading'; ignored r1.choices; the evidence also misstates the direction of the Micah reading."}], "foresaw_failure": true, "effect_vs_A": "hurt", "note": "r8; context_additions pre-announced Fred/Micah."},
  {"run": "rA__c2_probe_tools_r0", "status": "no_issues", "probe_items": {"understanding": "correct", "choices": "generic", "risks": "generic", "plan": "generic", "observations": "none"}, "issues": [], "foresaw_failure": false, "effect_vs_A": "none", "note": ""},
  {"run": "rA__c2_probe_tools_r1", "status": "no_issues", "probe_items": {"understanding": "correct", "choices": "odd: 'would not assume the recipient's assigned giver is the person who gave that item' ((b), not adopted)", "risks": "generic, mentions an assignment may be unclear", "plan": "generic", "observations": "none"}, "issues": [], "foresaw_failure": false, "effect_vs_A": "none", "note": ""},
  {"run": "rA__c3_probe_multi_r0", "status": "rewritten", "probe_items": {"understanding": "haiku: giver->recipient assignments (correct)", "choices": "haiku: test which column reading makes gifts match (flawed, direction-independent) (b); luna: assignments are giver->recipient (correct, (a))", "risks": "haiku: header inversion flips the answer (c); gift overlaps", "plan": "haiku: test both readings", "observations": "haiku read the docx (header Giftee | Recipient)"}, "issues": [{"id": "assignment_direction", "source": "r1.choices/r1.risks + r1.observation", "decision": "defer_to_execution", "quality": "OTHER", "note": "Faithful wording (best-supported), and it correctly blocked 'choose by gift fit', but it left a resolvable direction open instead of adopting r2's reading."}, {"id": "gift_matching", "source": "r1.choices/r1.risks, r2.risks", "decision": "defer_to_execution", "quality": "HARMFUL-STRICT", "note": "'do not assume one-to-one recipient coverage unless the document supports it' questions a structure the task gives; no visible effect."}], "foresaw_failure": true, "effect_vs_A": "hurt", "note": "context_additions carried the conclusion 'either column reading yields a valid pairing but different givers'; the d0 report named Micah, which led to re-check and hedge. The effect is probabilistic (sibling r1 succeeded)."},
  {"run": "rA__c3_probe_multi_r1", "status": "rewritten", "probe_items": {"understanding": "correct", "choices": "haiku: 'Recipient' is the receiver, so the Giftee column is the giver (correct, (a)); will test the other reading too", "risks": "haiku: column direction (c); gift overlaps", "plan": "haiku: parse, test both directions", "observations": "haiku read the docx"}, "issues": [{"id": "i1", "source": "r1.risks + r1.observation", "decision": "defer_to_execution", "quality": "OTHER", "note": "Deferred a resolvable label issue but demanded a best-supported answer; context passed only the observation."}], "foresaw_failure": true, "effect_vs_A": "none", "note": "Correct at d1, like A."},
  {"run": "rB__c2_probe_tools_r0", "status": "rewritten", "probe_items": {"understanding": "generic", "choices": "one-to-one, no self-assignment (echo of the draft)", "risks": "gift overlap", "plan": "'employee left without a gift assignment' (ambiguous wording, (b))", "observations": "none (the probe did not read the file)"}, "issues": [{"id": "1", "source": "r1.plan (misattributed by the analysis to the instruction)", "decision": "clarify", "quality": "REDUNDANT", "note": "Giver vs recipient: every worker already answered with the giver."}], "foresaw_failure": false, "effect_vs_A": "unclear", "note": "Same re-check path as A; it diverged at the finish."},
  {"run": "rB__c3_probe_multi_r0", "status": "rewritten", "probe_items": {"understanding": "haiku: giver of the unmatched recipient (correct)", "choices": "haiku: give both Fred/Micah and flag the header ((b)); luna: report ambiguity rather than force an answer ((b))", "risks": "haiku: direction flips the answer (c); Rebecca unmatched (correct pre-check)", "plan": "haiku: resolve direction from task wording, but also report each reading", "observations": "haiku read the docx"}, "issues": [{"id": "direction-of-assignment", "source": "r2.choices/r2.risks + r2.observation, r1.plan", "decision": "clarify", "quality": "OTHER", "note": "Correctly forbade alternative answers and restated the giver target (redundant), but left 'if the direction remains unclear' instead of fixing the Recipient-label reading."}], "foresaw_failure": true, "effect_vs_A": "unclear", "note": "The d0 worker got Fred with correct reasoning; the failure came from the orchestrator re-check, which also happened in A."}
 ],
 "task_level": {"preventable": "NA",
                "explanation": "No A-equivalent run failed: v6 draft 6/6 (A x3, no_issues c2 x3), v7 draft 2/2 (A, fresh). The refiner-arm failures came from making the column-direction issue salient without resolving it (s4 c3 r8: required both readings), and from orchestrator re-check/finish behaviour that the v7 A runs also showed but survived. A rewrite that resolved the direction toward the column labelled 'Recipient' (known from the probe's tool read, consistent with the task wording) would probably have avoided the refiner-induced failures. The v7-draft re-check risk lies in the orchestrator's finish policy, not in the d0 instruction.",
                "test_with_counterfactual": false,
                "counterfactual_instruction": null}
}
```
