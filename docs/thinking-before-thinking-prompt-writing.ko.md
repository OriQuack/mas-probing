# Thinking Before Thinking: 저자들은 프롬프트를 어떻게 썼는가

이 문서는 프롬프트 종류를 나열하는 대신, 저자들이 문장·제목·태그·예시를 어떻게 배치하여 원하는 행동을 명확히 했는지 분석한다. 근거는 로컬 PDF Appendix B–G이며 쪽수는 PDF 쪽수다. 원문 관찰과 재사용을 위한 해석을 구분한다. 개별 작성 기법의 효과를 분리한 ablation은 없으므로, 아래 기법이 성능 향상의 원인이라고 확정하지 않는다.

## 1. 첫 문장은 역할 이름보다 ‘이번 호출의 인지 작업’을 지정한다

Assess는 다음과 같이 시작한다. (p.21)

> You are an expert analyst assessing candidate solutions for a reasoning problem.

이어지는 문장은 objective, critical assessment를 산출하라는 목표를 붙이고, 단순 요약으로 흘러가는 것을 막는다.

> You are not summarizing --- you are evaluating.

이후 reasoning의 각 단계, 문제의 모든 evidence, 결론의 도출, 답 형식을 점검하라고 구체화한다. 즉 `전문가 역할 → 이번에 수행할 작업 → 혼동하기 쉬운 작업과의 경계 → 관찰 가능한 점검 기준`으로 좁힌다.

ProgramBench Assess도 senior software engineer라는 역할 다음에 factual snapshot을 유지하라는 동사를 둔다. 이어 요약이나 채점 대신 citation을 갖춘 상태 기록을 요구한다. 역할 이름이 비슷해도 text Assess와 coding Assess의 실제 작업은 다르게 정의한다. (p.22)

Propose는 strategist 역할로 시작하고, 현재 assessment를 받아 possible next actions를 제안하라고 한다. 여기서는 evaluation 단계가 무엇을 실행할지 결정한다는 설명으로 역할 경계를 밝힌다. Dispatch는 tool dispatcher로 시작하고 YAML recommendations를 concrete tool calls로 번역하라고 한다. (p.24, 28)

**재사용 원칙:** `You are an expert`에서 끝내지 말고, 이번 호출이 판단·발상·변환·실행 중 무엇을 해야 하는지 첫 단락에서 동사로 고정한다. 다른 작업으로 자주 새는 경우에만 그 경계도 적는다.

## 2. System의 상시 규칙과 user의 이번 입력을 분리한다

Assess user message는 인사나 긴 역할 설명 없이 아래 순서로 시작한다. (p.21)

```text
## Problem
{task}
## Memory
{memory}
## Previous State
{previous_state}
## New Artifacts
{new_artifacts}
```

역할·점검 기준·도구 사용·출력 형식은 system 쪽에 둔다. 바뀌는 task, memory index, previous state, new artifacts는 user 쪽의 이름 붙은 슬롯에 넣는다.

각 슬롯은 별도 설명에서도 정의한다. 예를 들어 memory는 ID와 title의 index이며 body는 read_memory로 얻는다고 밝힌다. new artifacts는 이전 state 이후 생긴 결과의 전체 텍스트다. 이름만 보고 index를 전체 본문으로 오인하거나, 새 후보만 보고 전체 pool에 대한 판단을 잊는 것을 막는다.

Evaluate user message도 `Problem → Memory → State → Proposals → Budget`로 구분하고 마지막에 평가와 추천 요청을 붙인다. Dispatch는 `Problem → Memory → Selected Action` 뒤에 실행 요청을 붙인다. (p.25, 27–28)

**해석:** 공통 목표를 먼저 두고, 재료와 현재 상태, 이번 결정의 직접 입력을 구분한다. 후속 단계의 목적과 가까운 자료를 뒤쪽에 놓는 패턴은 관찰되지만, 이 순서가 다른 순서보다 낫다는 실험은 없다.

## 3. 제목은 일반적인 ‘지침’ 대신 독자가 지금 해야 할 구분을 드러낸다

| 실제 heading | 독자에게 알려주는 것 |
|---|---|
| `## How this stage works (incremental)` | 전체 이력을 다시 평가하는 호출인지, 증분 갱신인지 |
| `## Output structure` | 여기부터 출력해야 할 블록과 필드의 설명 |
| `## When to recommend STOP` | 일반 평가와 별개인 종료 분기 조건 |
| `## Tools available` | 이번 역할에서 가능한 행동 |
| `## Translating the recommendation` | 추천 텍스트를 tool call로 변환하는 방법 |
| `## Writing subagent_prompts[i] --- IMPORTANT` | 위임 시 특히 자주 실패하는 필드 작성법 |
| `## Response requirements` | 답의 내용상 요건 |
| `## Mandatory output format` | 파서가 요구하는 표면 형식 |

내용상 올바른 답과 파싱 가능한 답의 규칙을 서로 다른 heading으로 나눈 점이 특히 유용하다. (p.21–29, 32)

**재사용 원칙:** heading이 답해야 할 질문을 정한다. `Guidelines` 한 묶음으로 역할, 입력 의미, 예외, 포맷을 섞지 않는다. 다만 실제 구분할 내용이 없으면 heading을 늘리지 않는다.

## 4. 입력의 ‘보이는 범위’를 먼저 설명한다

Assess는 `You receive:` 아래에 세 입력을 열거한다. 전체 pool의 ID/title, 이전 assessment, **ONLY** 새 후보다. 첫 라운드 previous assessment는 비어 있을 수 있다고도 적는다. (p.21)

이는 모델이 보지 못한 본문을 본 것처럼 판단하지 않게 하는 입력 계약이다. 오래된 후보 비교가 필요할 때 read_memory를 쓰라는 안내가 곧바로 이어진다.

Dispatch에는 worker가 deliberation을 보지 않고 steering string만 본다는 문장을 둔다. 이 설명 다음에 self-contained instruction을 요구한다. 따라서 self-contained가 막연한 문체 요구가 아니라 **수신자의 정보 부족을 메우는 조건**이 된다. (p.29)

**재사용 원칙:** 이 호출이 아는 것과 모르는 것을 적고, 모르는 정보가 필요할 때 조회·질문·위임 중 어떤 경로를 쓰는지 연결한다. 사용자에게 이미 주어진 입력을 반복 설명하는 대신 정보 비대칭이 있는 부분을 명확히 한다.

## 5. 도구 이름 옆에 ‘언제·왜 사용할지’를 쓴다

Assess의 read_memory 설명은 후보 body를 가져온다고 끝내지 않는다. 새 후보를 이전 assessment가 언급한 후보와 비교할 때 쓰라고 한다. Propose에서는 기존 결과를 바탕으로 action을 제안하기 전에 읽을 수 있다고 한다. 같은 도구를 단계의 목적에 맞춰 설명한다. (p.21, 24)

ProgramBench는 runtime 검증이 필요하면 worker action으로 제안하고, 코드의 현재 내용이나 commit 이력을 보고 싶으면 read-only git을 쓰라고 한다. 기능 설명에 작업 선택 기준까지 붙인다. (p.22, 36–37)

**재사용 원칙:** 도구 문장은 `할 수 있는 일 + 사용 조건 + 접근 범위`를 담는다. 프롬프트에서 허용한다고 적는 것만으로 실제 권한이 생기는 것은 아니므로 tool schema와 runtime 권한은 따로 일치시켜야 한다.

## 6. Tag는 내용의 역할을 나누고 ID는 항목을 연결한다

Assess는 평가를 다음처럼 나눈다. (p.21–22)

```xml
<per_candidate_assessment>
  <candidate id="X_Y">...</candidate>
</per_candidate_assessment>
<overall_assessment>...</overall_assessment>
<stop_recommended>...</stop_recommended>
<outstanding_questions>...</outstanding_questions>
```

큰 tag는 후보별 평가/전체 판단/종료 신호/미해결 질문의 의미를 분리한다. `<candidate id="X_Y">`는 평가와 실제 memory 항목을 연결한다. Propose의 `<action id="A">`와 Evaluate의 같은 action ID는 proposal과 평가, 최종 추천을 연결한다.

여기서 tag의 철자 자체보다 중요한 것은 **어떤 정보가 어디에 들어가며 어떤 ID를 공유하는가**다. 저자들은 exact pool IDs를 쓰라고 하고 출력 소비자가 downstream이라는 점을 설명한다.

이 tag들 중 모든 것이 코드로 엄격히 파싱되는지는 PDF에 공개하지 않는다. Worker title/confidence 파싱은 명시하지만, 각 XML형 블록 전체에 XML parser를 사용한다고 단정할 수는 없다.

**재사용 원칙:** 구조적 출력이 필요하면 의미별 경계와 ID 연결 규칙을 같이 설계한다. 기존 JSON schema가 있다면 그 계약을 유지하며 이 원칙을 적용한다. XML처럼 보이는 문법이 언제나 최선이라는 뜻은 아니다.

## 7. 각 tag 안에 ‘무엇을 적어야 하는지’를 직접 쓴다

저자들은 빈 skeleton만 주지 않는다. per_candidate_assessment에는 접근법, 타당한 부분, 빈틈, evidence 위반, 답 형식의 점검 기준을 넣는다. overall_assessment에는 시도한 접근과 미탐색 접근, 공유 오류, 독립적 합의인지 공유 가정인지, 진행 방향을 넣는다. (p.21–22)

Propose는 action마다 달성할 것, 지금 가치가 있는 이유, 가정, 바탕이 되거나 반박하는 후보 ID를 적게 한다. Evaluate는 기대 이득, 비용, 예산 대비 가치와 rating을 적게 한다. (p.24–25)

**해석:** 출력 skeleton이 동시에 사고를 조직하는 checklist 역할을 한다. 다만 이를 숨은 내부 사고의 정확한 구조라고 해석할 수는 없다. 관찰 가능한 응답에 필요한 판단 근거를 요구하는 것이다.

**재사용 원칙:** 필드 이름뿐 아니라 포함할 정보와 구체성 수준을 적는다. 서로 겹치는 필드가 있다면 입력·출력 예를 통해 경계를 먼저 정리한다.

## 8. Label을 정의하면서 후속 행동까지 연결한다

Assess verdict는 세 가지다. 단어만 나열하지 않고 의미와 downstream에 대한 시사점을 붙인다. (p.21–22)

| Label | 의미 | 후속 행동의 시사점 |
|---|---|---|
| LIKELY_CORRECT | 완전하고 올바른 후보 | 종료·제출을 고려 |
| HAS_GAPS | 일부는 맞지만 빈틈이 있음 | refinement 고려 |
| FUNDAMENTALLY_FLAWED | 접근이 잘못되었거나 다른 질문에 답함 | 포기 고려 |

이것은 후속 행동을 강제하는 일대일 매핑은 아니다. Evaluate는 Assess의 STOP hint를 독립적으로 재판단한다. label과 decision authority를 함께 정의한 셈이다.

**재사용 원칙:** enum을 쓸 때 이름, 판정 근거, 후속 영향, 최종 결정권자를 정한다. 단어의 강도만 다르게 하여 경계를 흐리지 않는다.

## 9. 출력의 사용처를 설명해 형식 규칙의 이유를 드러낸다

Worker prompt는 response가 title로 시작하고 confidence로 끝나야 한다고 적은 직후 orchestrator가 이를 parse한다고 설명한다. confidence는 refine/verify/submit 판단에 사용되므로 미검증 작업을 HIGH로 표시하면 compute를 낭비한다고 한다. (p.32)

Appendix E는 title이 memory index가 된다고 설명한다. 따라서 title은 글의 장식이 아니라, controller가 body를 열기 전에 무엇을 읽을지 결정하게 하는 요약이다. 원문의 예시 title은 접근법이나 수정 내용을 구별한다. (p.33)

```text
Generating function approach
Repair of 0_0 supplying the missing base case
```

**재사용 원칙:** metadata를 요구한다면 소비자와 용도를 함께 정의한다. 제목을 요구할 때는 ‘짧게’만 적기보다 무엇을 구별해야 하는지 적는다. 예를 들어 접근법, 확인한 쟁점, 수정한 결함을 드러내는 제목이 검색과 재사용에 도움이 될 수 있다. 이 마지막 문장은 분석자의 권고다.

## 10. Exact format은 위치·허용값·끝나는 조건까지 적는다

Worker의 Mandatory output format은 아래 세 위치를 명시한다. (p.32)

```text
FIRST LINE: <title>short descriptive title of your approach</title>
ANSWER LINE: your final answer in the form the problem requires
LAST LINE: confidence: HIGH
...or: confidence: MEDIUM
...or: confidence: LOW
```

그리고 마지막 **비어 있지 않은 줄**이 허용된 confidence 줄 중 하나여야 한다고 다시 적는다. `정해진 형식을 지켜라`보다 다음 모호함을 줄인다.

- title을 중간 heading으로 넣어도 되는가?
- confidence 뒤에 설명이나 인사를 덧붙여도 되는가?
- HIGH 대신 숫자나 자유 문장을 써도 되는가?
- final answer에 별도의 `ANSWER LINE:` 접두어가 필요한가? 원문은 문제에서 지정한 답 형식을 따르라고 하므로 이 표시를 보편적 literal 접두어로 추가해서는 안 된다.

**재사용 원칙:** parser가 민감한 부분만 정확히 고정한다. 필드명, 위치, 허용값, 끝난 뒤 추가 텍스트 가능 여부를 명시한다. prompt만으로 형식 준수가 보장되지는 않으므로 schema/validator와 맞춘다.

## 11. Context의 신뢰 수준을 앞뒤에서 지정한다

Worker는 Prior Attempts heading 다음에 이전 결과가 정확·완전·엄밀하지 않을 수 있다고 경고받는다. body들을 넣은 뒤에도 경계를 닫는 문장을 둔다. (p.32)

> End of prior attempts. Use them as input to your own reasoning, not as ground truth.

이는 단순 delimiter뿐 아니라 이전 artifact의 지위를 설명한다. 참고 재료를 정답이나 권위 있는 지시로 취급하지 않게 한다. 이후 `## Instructions`로 실제 이번 지시를 구분한다.

**재사용 원칙:** 외부 문서, 이전 답, 테스트 결과가 서로 어떤 지위를 가지는지 밝힌다. 입력 경계를 표시한다고 해서 prompt injection 방어가 완성되는 것은 아니다. 신뢰·권한은 runtime과 입력 처리에서도 관리해야 한다.

## 12. 모호한 품질 요구를 evidence 규칙과 상태 전이로 바꾼다

ProgramBench Assess는 모든 항목을 citation이 있는 factual bullet로 쓰고, 증거를 인용할 수 없으면 추가하지 말라고 한다. `구현됨`도 작성했다는 주장만으로 인정하지 않고 test나 reference diff 증거가 있어야 한다. (p.22–23)

`## Discipline`에서는 다음을 명령형으로 적는다.

- Citation-only: memory ID 또는 commit을 붙인다.
- Carry forward: 이전 상태 중 여전히 참인 것은 유지한다.
- Move, don't duplicate: 검증되면 unverified에서 implemented로, regression이면 broken으로 이동한다.
- One bullet per surface area: 같은 기능을 중복 기록하지 않는다.
- Be specific: 막연한 작동 주장 대신 실제 flag와 behavior를 적는다.

예시도 ‘CLI parsing works’ 같은 모호한 문장과 구체적 flag 목록을 대비시킨다.

**재사용 원칙:** ‘정확하게’, ‘최신 상태로’, ‘구체적으로’라는 형용사를 증거 조건, 업데이트 규칙, 중복 처리, 예시로 풀어 쓴다. 이 다섯 상태를 다른 작업에 그대로 강제할 필요는 없다.

## 13. 판단에는 분기 조건·우선순위·기본값을 붙인다

Evaluate의 STOP 규칙은 `ALL` 조건 (a)(b)(c)로 쓴다. 후보의 정오, 관련 미해결 질문, 추가 작업의 가치, 확신을 함께 요구한다. 충족되지 않거나 의심이 있으면 정상 action 추천을 출력하도록 한다. 여러 HIGH_VALUE가 경쟁하면 우선순위를 (a)(b)(c)로 지정한다. (p.25–27)

Dispatch도 `If STOP → finish / Otherwise → run_workers`로 나누고, recommendation이 없거나 malformed면 context 없는 worker 하나라는 fallback을 적는다. (p.28–29)

**재사용 원칙:** decision prompt에는 분기 조건, 동률 해소 기준, 입력 누락 시 처리, 결정권자를 적는다. 단, 논문의 CONTINUE 기본값이나 추가 worker fallback은 비용·목적에 의존한다. 모든 agent에 무조건 이 기본값을 복사하면 안 된다.

## 14. 강조는 깨지기 쉬운 규칙에 집중하고, 이유와 대안을 붙인다

저자들은 ONLY, EXACT, CRITICAL, VERBATIM, MUST, ALL과 bold를 사용한다. 강조하는 대상은 새 후보만 입력된다는 사실, exact ID, 원문 그대로의 제출, commit 전후 순서, worker 지시의 완결성처럼 실패 시 동작이 달라지는 지점이다.

Dispatch는 `Do NOT pass the action_id alone`에서 끝나지 않는다. worker가 deliberation을 볼 수 없어 추측하게 된다는 이유를 적고, full action body에서 concrete files/flags/commands/success criteria를 포함한 imperative instruction을 만들라고 대안을 준다. (p.29)

**재사용 원칙:** `금지 → 실패 이유 → 수행할 대안`을 한 묶음으로 쓴다. 강조가 많아질수록 구분력이 약해지므로 일반적인 조언까지 모두 MUST로 올리지 않는다.

## 15. Bad/Good 예시는 같은 실패를 겨냥한 한 쌍으로 둔다

Dispatch의 BAD 예시는 다음처럼 작업 이름 하나뿐이다. (p.29)

```text
merge_cli_quirks
```

GOOD 예시는 CLI parsing과 output quirks를 합치라는 작업, main.go라는 파일, 이전 worker 보고, 빈 입력·--raw의 newline 차이, reference binary와 --help 비교, byte-for-byte 일치 후 commit이라는 완료 기준을 포함한다.

이 한 쌍은 ‘길게 써라’보다 **어떤 정보가 없어서 실행할 수 없는가**를 보여준다. 원문의 200–500 characters 안내는 그 완결성을 유도하는 보조 지침이다. 길이만 채워도 좋은 prompt가 되는 것은 아니다.

**재사용 원칙:** 실제로 빈번한 오해 하나를 선택해 같은 작업의 불완전한 지시와 실행 가능한 지시를 대비한다. 예시의 기술 스택이나 파일명을 새 작업의 필수조건으로 복사하지 않는다.

## 16. 시간 순서를 명시해 ‘예전에 성공함’을 ‘현재 확인됨’으로 착각하지 않게 한다

ProgramBench worker에는 summary **전에** commit하라고 한다. source 또는 compile.sh를 수정했다면 **마지막 수정 후** compile.sh를 다시 실행하고 **실제 exit code**를 보고하라고 한다. 이전 실행 결과에서 build 상태를 추정하지 말라는 문장까지 붙인다. (p.32)

이는 `테스트하라`보다 강한 절차 명세다. 최종 결과물과 검증 증거의 시점을 맞춘다. commit을 모든 작업에 일반화할 필요는 없지만, 결과와 근거가 같은 버전을 가리켜야 한다는 원칙은 재사용할 수 있다.

## 17. 저자들의 작성 방식으로 압축한 골격

다음은 분석자가 만든 재사용용 골격이며 논문의 verbatim prompt가 아니다. 모든 블록을 매번 넣으라는 뜻은 아니다.

```text
[Role + current operation]
이번 호출에서 해야 할 일과 성공 조건을 첫 단락에 정의한다.

## Inputs and visibility
입력별 의미, 신뢰 수준, 비어 있을 수 있는 값, 보이지 않는 정보를 정의한다.

## Available actions
도구/행동을 언제 쓰며 무엇을 할 수 없는지 필요한 범위에서 적는다.

## Work criteria
판단 기준과 증거 조건을 구체적으로 적는다.
자주 생기는 오해가 있다면 이유와 대안, 대비 예시를 붙인다.

## Output contract
필드/블록마다 들어갈 내용, ID 연결, 허용 label, 소비자를 적는다.

## Decision and exceptions
조건, 우선순위, 불확실할 때의 처리, malformed 입력 처리를 정한다.
```

이번 입력은 별도로 `원 문제 → 필요한 context → 현재 요청`처럼 의미가 분리된 블록에 넣는다. 자료의 신뢰 지위와 지시를 구분하고, 수신자가 앞선 대화를 볼 수 없다면 지시를 그 자체로 완결시킨다.

## 18. 이 논문만으로 말할 수 없는 것

- 제목·XML tag·대문자 강조 중 무엇이 성능 향상을 일으켰는지 분리 검증하지 않았다.
- 이 순서나 영어 표현이 모든 모델·작업에서 최적이라고 보장하지 않는다.
- 모든 출력 tag를 엄격한 XML parser로 처리한다는 구현은 공개하지 않는다.
- ‘독립적으로 평가하라’는 문장이 판단의 통계적 독립성을 보장하지 않는다.
- ‘모든 claim을 정당화하라’는 문장을 모든 작업의 상세 사고 공개 요구로 일반화할 필요는 없다. 검증 가능한 근거와 결과를 요구하는 형태로 목적에 맞춰 적용한다.

앞선 [구조·memory·trace 분석](thinking-before-thinking-analysis.ko.md)은 시스템 구조를 설명한다. 이 문서는 그 구조를 모델이 이해하고 지키도록 저자들이 문장을 작성한 방식을 설명한다. 각 프롬프트가 어떤 행동 정책을 구현하는지, 단계 사이의 계약과 비교 조건의 문구 차이는 [prompt engineering 분석](thinking-before-thinking-prompt-engineering.ko.md)에서 다룬다.
