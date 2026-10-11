# Thinking Before Thinking: 프롬프트·context·memory·trace 분석

프롬프트의 문장 구성, heading·tag·title, 명확성을 높이는 작성 기법은 [별도 작성 분석](thinking-before-thinking-prompt-writing.ko.md)에 원문 사례와 함께 정리했다. 이 문서는 시스템의 입출력과 memory·trace 구조에 초점을 둔다. 단계 간 계약, 종료·예산 정책, baseline 프롬프트와의 차이는 [prompt engineering 분석](thinking-before-thinking-prompt-engineering.ko.md)에서 다룬다.

검토 대상: `Thinking Before Thinking- Scaling Agentic Inference Through Meta-Reasoning.pdf`, 2026-09-30, arXiv:2609.38147v1. 아래 쪽수는 PDF 페이지/논문 인쇄 쪽수다. 로컬 PDF 38쪽 전체 중 본문 §3–4, §6.5, Appendix B–G를 중심으로 확인했다. 외부 구현 코드를 검증한 보고서는 아니다.

## 1. 핵심 구조

이 논문의 핵심은 **지속하는 artifact 저장소와 매번 새로 시작하는 controller context를 분리**하는 것이다.

```text
task + memory index + previous state + new artifact bodies
  → Assess → current state
  → Propose → possible next computations
  → Evaluate (+ budget) → selected actions / STOP
  → Dispatch → instruction + selected artifact bodies → workers
  → worker outputs를 memory에 추가 → 다음 라운드
```

- 네 단계는 각각 별도 system prompt를 쓰는 agentic loop다. 매 라운드 fresh context로 시작하며, tool read/write 때문에 한 단계에 여러 LLM 호출이 필요할 수 있다. 네 단계 = 반드시 네 호출이라는 뜻은 아니다. (p.5, 20)
- 라운드 사이에는 압축 state를 전달한다. 전체 과거 대화를 다시 붙이지 않는다.
- 모든 controller 단계에는 memory의 **ID와 title 전체 목록**을 준다. body 전체를 주는 것은 아니다.
- worker는 원 문제, 해당 작업 지시, 선택된 artifact 본문만 본다. controller의 state나 deliberation을 자동으로 보지 않는다.
- text benchmark worker는 단일 LLM 호출, ProgramBench worker는 공유 filesystem에서 bash를 쓰는 다중 호출 agent다.
- 고정된 verifier/repairer 역할 집합이 아니라, instruction과 선택 context로 이번 작업의 성격을 정한다. (p.4)

## 2. Appendix B: 프롬프트를 어떻게 작성했는가

text benchmarks는 공통 prompt 구조를 공유하되 benchmark별 문구가 조금 다르다. ProgramBench 버전도 별도로 공개한다. task는 모든 단계와 라운드에서 동일하다. (p.20–29)

### 2.1 각 단계 user message 조립

| 단계 | 입력 블록 순서 | 핵심 차이 |
|---|---|---|
| Assess | Problem / Memory / Previous State / New Artifacts | 이전 state와 그 이후 생긴 artifact의 전체 텍스트 |
| Propose | Problem / Memory / Current State | 이번 Assess가 작성한 state; 마지막에 다음 행동 제안 요청 |
| Evaluate | Problem / Memory / State / Proposals / Budget | proposal 전체와 예산을 받아 행동·worker 수·context ID 선택 |
| Dispatch | Problem / Memory / Selected Action | Evaluate 출력 전체를 받아 실제 tool call로 변환 |

Appendix B는 Budget을 명시적으로 전달받는 단계를 Evaluate로 설명한다. 특히 Propose에는 예산을 주지 않아 비싼 선택지도 먼저 후보에 포함되게 한다. ProgramBench의 고정 환경 제한은 task 자체에도 들어가므로, 모든 자원 제약이 Evaluate에만 보인다는 의미는 아니다. (p.5, 25, 35–36)

### 2.2 Assess: 요약이 아니라 후보의 비판적 평가

text 버전은 reasoning의 모든 단계, 문제의 모든 evidence, final answer의 형식까지 확인하도록 지시한다. 새 후보를 분석한 뒤 기존 후보까지 포함한 전체 pool의 판단을 갱신한다. 이전 후보가 필요하면 `read_memory`로 다시 읽고, 재사용할 사실이나 경고는 `write_memory`로 남긴다.

출력 계약은 XML 형태의 텍스트다. (p.21–22)

```xml
<per_candidate_assessment>
  <candidate id="X_Y">
    접근법, 답, 타당한 부분, 논리적 빈틈, 제약 위반, 답 형식 검토
    LIKELY_CORRECT / HAS_GAPS / FUNDAMENTALLY_FLAWED
  </candidate>
</per_candidate_assessment>
<overall_assessment>
  이미 시도한 접근, 미탐색 접근, 공통 오류, 유망 후보, 진행 방향
</overall_assessment>
<stop_recommended>
  STOP X_Y 또는 CONTINUE + 한 문장 이유
</stop_recommended>
<outstanding_questions>
  미해결 단계, 정당화되지 않은 주장, 후보 간 불일치, 공유된 미검증 가정
</outstanding_questions>
```

`overall_assessment`를 downstream에 쓰는 compressed state라고 명시한다. 다만 다른 태그까지 런타임 state 문자열에 어떻게 포함·추출하는지는 이 PDF만으로 확정할 수 없다. Evaluate 설명은 Assess의 stop hint와 outstanding questions도 활용한다고 되어 있다. 따라서 구현 시 state를 overall_assessment만으로 잘라 버리면 필요한 판단 정보가 누락될 수 있다.

Assess의 STOP은 제안이다. 완전성·정확성·형식에 확신이 없으면 CONTINUE가 기본이며 Evaluate가 이를 재판단한다. worker의 HIGH confidence를 그대로 믿지 않도록 반복해서 경고한다.

**ProgramBench는 다른 출력 계약을 쓴다.** 후보 정오 verdict/stop signal 대신 다음 다섯 섹션에 citation이 붙은 사실 snapshot을 유지한다. (p.22–23)

| 섹션 | 기록할 내용 |
|---|---|
| implemented | 구현했고 실제 테스트·reference diff 등 작동 증거가 있는 기능 |
| broken | 테스트 실패, crash, 출력 차이, build 실패가 확인된 기능 |
| unverified | 구현했다고 주장하지만 증거·독립 확인이 없는 기능 |
| unexplored | target의 문서·help 등에서 존재를 알지만 아직 구현하지 않은 기능 |
| dead_ends | 시도 후 포기한 접근과 이유 |

각 bullet은 memory ID 또는 commit hash를 인용해야 한다. 이전에 참이던 항목은 유지하고, 새 증거가 나오면 섹션 사이에서 이동시키며, 같은 기능은 중복 기재하지 않는다. 실행 확인은 worker에게 맡기고 controller는 read-only git으로 코드를 확인할 수 있다. worker의 글만으로 사실을 확정하지 않는다.

### 2.3 Propose: 선택하기 전에 선택지를 펼친다

system prompt는 전략을 제안하되 실행하지 말고, 안전한 소수 선택지로 미리 줄이지 말라고 한다. 출력은 다음과 같다. (p.23–24)

```xml
<actions>
  <action id="A">
    무엇을 달성할지 / 왜 지금 유용한지 / 어떤 가정을 하는지 /
    어떤 이전 artifact ID를 기반으로 하거나 반박하는지
  </action>
</actions>
```

새 접근, 특정 오류 수정, 독립 검증, 공유 가정의 반례 찾기, 여러 부분 결과 합성, 종료 모두 가능하다. 정해진 action enum으로 제한하지 않는다. ProgramBench에서는 미구현 기능 탐색·구현, 오류 수정, 코드 변경 없이 검증하는 worker 파견 등을 제안한다.

### 2.4 Evaluate: 기대 이득·비용·종료를 결정

각 proposal을 같은 ID의 `<action>`으로 평가한다. 기대 이득, worker 수에 따른 비용, 남은 budget에서 가치가 있는지를 판단하고 `HIGH_VALUE / MEDIUM_VALUE / LOW_VALUE`로 끝낸다. 정확한 수치 최적화나 학습된 value-of-computation 모델이 아니라 **프롬프트로 유도한 정성 판단**이다. (p.5, 25–27)

text 버전의 추천 형식은 다음과 같다. 아래 ID는 설명용이다.

```yaml
recommendations:
  - action_id: A
    memory: ["0_1", "1_0"]
    parallel_workers: 2
  - action_id: B
    memory: []
    parallel_workers: 1
```

논문 예시는 ID를 따옴표 없이 제시한다. 구현에서는 `0_1`처럼 숫자와 underscore로 이루어진 ID가 YAML parser에 따라 숫자로 해석될 수 있으므로 문자열로 인용하고 타입을 검증하는 편이 안전하다. 이는 논문 원문의 규칙이 아니라 구현 권고다.

text의 동률 해소 순서는 미해결 질문을 많이 해결하는 행동 → worker 호출당 기대 이득 → 다양성이다. STOP은 다음을 모두 충족해야 한다.

1. Assess가 LIKELY_CORRECT로 평가했고 그 후보에 관련된 미해결 질문이 없다.
2. 추가 행동들의 가치가 LOW_VALUE다.
3. 그 후보의 정확성에 확신할 수 있다.

```yaml
recommendations:
  - action_id: STOP
    memory_id: "X_Y"
```

ProgramBench는 연관된 작은 proposal들을 `A+B+C`처럼 묶어 평가하고 **그룹당 worker**를 보낸다. 공유 workspace에 쓰는 coding 작업은 `parallel_workers: 1`로 제한한다. read-only 탐색/검증은 병렬화를 허용한다. 미완성 기능과 테스트 커버리지를 우선하며, 이미 통과하는 코드의 미관 개선은 낮게 평가한다.

ProgramBench 추천에는 아래 필드가 추가된다.

```yaml
subagent_prompt: |
  worker가 단독으로 이해할 수 있는 명령형 지시.
  구체적 파일, 명령, flag, 이전 결과, 성공 기준을 포함한다.
```

원문은 적어도 200–500 characters를 목표로 하라고 표현한다. 엄밀한 최소·최대 길이 검증 규칙이 공개된 것은 아니다. STOP에는 unexplored와 broken이 비었거나 정당하게 제외되었고, unverified는 비어 있어 독립 검증을 마쳤으며, 추가 행동이 모두 LOW_VALUE여야 한다는 조건을 둔다.

### 2.5 Dispatch: 선택을 실행 가능한 호출로 바꾼다

하나의 dispatch에서 `run_workers`는 한 번 호출한다. 여러 recommendation을 하나의 batch로 펼친다. (p.28–29)

```python
num_repeats = sum(action.parallel_workers for action in recommendations)
subagent_prompts[i] = i번째 worker의 steering
memory_blocks[i] = i번째 worker에게 전달할 artifact ID 목록
```

두 리스트 길이를 worker 수와 맞춘다. 추천이 STOP이면 지정된 ID로 finish한다. 추천이 비었거나 깨졌으면 원 문제에 대해 context 없는 worker 하나를 실행하는 fallback이 명시되어 있다.

ProgramBench에서는 Evaluate가 `subagent_prompt`를 썼으면 그대로 전달한다. 없으면 action 본문에서 완전한 지시를 만든다. **action ID만 전달하는 것을 가장 큰 dispatch 실패 원인이라고 명시한다.** worker는 evaluation을 보지 않기 때문이다. 좋은 지시는 무엇을 합칠지, 어느 파일·이전 결과를 쓸지, 어떤 명령으로 무엇과 비교할지, 성공 기준을 포함한다.

text에서 `finish(memory_id)`는 body를 title/confidence까지 그대로 제출한다. 형식을 정리해야 한다면 worker가 새 artifact를 먼저 만들게 해야 한다. ProgramBench에서는 report 텍스트보다 현재 workspace의 compile.sh와 실행파일이 평가 대상이다.

## 3. Appendix D: worker prompt

worker 입력 순서는 다음과 같다. (p.31–33)

```text
역할 설명
## Problem 또는 Task
{task}
## Prior Attempts 또는 Prior Work (memory blocks)
이전 결과는 틀리거나 불완전할 수 있으므로 비판적으로 사용하라는 경고
{selected_artifacts}
## Instructions
{steering}
## Response requirements 또는 Workflow
```

text worker는 reasoning을 보이고 하나의 답으로 결론 내며, 모든 주장을 정당화하고 재검토하고 문제의 정확한 답 형식을 따르도록 요구받는다. 필수 형식은 다음과 같다.

```text
<title>접근법을 설명하는 짧은 제목</title>
...풀이와 문제에서 요구한 형식의 최종 답...
confidence: HIGH
```

마지막 비어 있지 않은 줄은 HIGH/MEDIUM/LOW 중 정확한 confidence 줄이어야 한다. title은 memory index에, confidence는 사후 monitoring 분석에 사용된다.

ProgramBench worker는 종료 summary 전에 변경을 commit한다. source/compile.sh를 수정했다면 마지막 수정 이후 compile.sh를 다시 실행하고 실제 exit code를 보고한다. `<summary>`에는 branch, 구체적 변경 파일/기능, binary 관찰, build 결과, 남은 broken/unverified 항목, confidence를 포함한다. commit subject가 memory title이 되며 read-only git 안내는 `[short_hash] subject` 형식을 설명한다. (p.32–33, 36)

## 4. Context list는 어떻게 구성하는가

이 논문에서 구분해야 할 목록은 세 가지다.

| 이름 | 담는 것 | 받는 주체 |
|---|---|---|
| memory index | 전체 artifact의 ID + title | 각 controller 단계 |
| recommendation.memory / memory_blocks[i] | 해당 worker에 필요한 ID 부분집합 | harness가 해석하는 tool 인자 |
| selected_artifacts | 위 ID들의 실제 body를 순서대로 렌더링한 문자열 | worker |

선택 방법은 embedding 검색·top-k 검색이 아니다. Evaluate가 action에 필요한 **정확한 ID를 명시적으로 선택**하고 Dispatch가 tool call로 변환한다. 각 단계는 제목만으로 부족하면 `read_memory`로 본문을 읽을 수 있다. 자동 relevance ranking, chunking, context token limit에서의 절단 정책은 PDF에 공개되어 있지 않다.

```json
{
  "num_repeats": 3,
  "subagent_prompts": ["후보의 누락된 경우를 확인하라", "후보의 누락된 경우를 확인하라", "새 접근으로 풀어라"],
  "memory_blocks": [["0_1", "1_0"], ["0_1", "1_0"], []]
}
```

이는 구조 설명용 예시다. 첫 두 worker는 동일 action에 같은 context, 셋째는 fresh attempt다. 실제 worker에는 ID 목록 대신 해당 body들이 전달된다. 기본 렌더링은 다음과 같으며 **ID를 숨긴다**. 따라서 worker가 context artifact의 ID를 직접 인용할 수 있다고 가정하면 안 된다. (p.33)

```xml
<memory>
...artifact body...
</memory>
<memory>
...another artifact body...
</memory>
```

공유 파일을 읽는 ProgramBench에서는 전달 context 외 정보도 볼 수 있다. artifact dependency graph는 controller가 선택한 context 연결을 기록할 뿐, 모든 실제 정보 흐름을 포착하지 않는다. (p.4–6)

## 5. Appendix E–F: memory pool 생성·접근

pool은 모델 내부 기억이 아니라 **harness가 관리하는 artifact 저장소**다. 기본 논리 record는 `{id, title, body}`다. ID 형식은 `{round}_{worker}`이며 `2_1`은 세 번째 라운드의 두 번째 worker를 뜻한다. controller note도 같은 pool에 현재 라운드의 새 ID로 저장한다. note까지 섞였을 때의 상세 allocator 구현은 공개되지 않았다. (p.33–35)

생성 경로는 두 가지다.

1. worker 종료 → output을 harness가 자동 저장 → title 추출.
2. controller가 `write_memory(entries=[{"title": ..., "body": ...}])` → 새 ID의 note 생성.

정답 artifact와 controller note는 같은 index에 등장한다.

```text
0_0: TITLE: Induction on n with a strengthened hypothesis
0_1: TITLE: Direct construction via the pigeonhole principle
1_0: TITLE: Note: the n=1 base case in 0_0 is unproven
1_1: TITLE: Repair of 0_0 supplying the missing base case
```

`read_memory(ids=["1_1"])`의 반환은 다음과 같아 controller는 ID를 확인할 수 있다. 모르는 ID는 `NOT FOUND`를 반환한다.

```xml
<memory id="1_1">
<title>Repair of 0_0 supplying the missing base case</title>
...full body...
</memory>
```

이 구조는 한 문제의 run 안에서 축적하는 기억이다. 다른 문제 사이의 장기 기억·학습이나 vector DB를 제안한 것으로 읽으면 안 된다. pruning/eviction, 디스크 DB 형식, ID 충돌 처리, crash recovery는 PDF에 명시되어 있지 않다.

또한 compact state가 작더라도 전체 prompt가 상수 크기로 제한되는 것은 아니다. index는 artifact 수에 따라 늘고, 새 artifact와 tool로 읽은 body도 입력에 추가된다. 논문도 state 크기 측정이 실제 decision input의 하한이라고 설명한다. (p.13–15)

## 6. Trace를 분석 가능하게 만드는 논문의 방법

**PDF는 trace의 JSONL 파일명이나 전체 저장 schema를 공개하지 않는다.** 공개된 것은 분석 가능한 정보를 만드는 출력 계약과 artifact graph/metric 정의다. 아래 내용과 다음 절의 구현 제안을 구분해야 한다.

### 6.1 Artifact graph (본문 §3.4, §4)

worker output을 node로 두고, 나중 worker에게 context로 전달한 이전 artifact에서 output으로 edge를 기록한다.

```text
0_0: initial solution ────────────→ 1_0: critique
  └──────────────────────────────→ 2_0: repair ←── 1_0
```

`2_0`에 `memory_blocks=["0_0", "1_0"]`를 줬다면 두 edge를 기록한다. 제목이나 body를 사후에 읽어 연결을 추측하는 것이 아니라 **dispatch 당시 ID를 저장**하는 방식이다. 기존 artifact만 입력하므로 DAG다.

전체 pool에는 note도 있지만 본문 graph 진단의 node는 worker output이다. note 경유 관계를 어떤 규칙으로 worker graph에 반영하는지는 PDF에서 충분히 명시하지 않는다. 구현 시 전체 provenance graph와 worker-only 분석 graph의 규칙을 별도로 선언해야 한다. note를 임의로 solution node로 세면 안 된다.

### 6.2 논문이 분석하는 항목

| 항목 | 필요한 기록 / 의미 |
|---|---|
| budget utilization | 실제 controller+worker 호출 수 / nominal call budget |
| graph 구조 | worker node·edge 수, roots, fan-in 평균/최대, 최장 경로 depth, 같은 depth 최대 node 수 width |
| memory 사용 | read/write 단계, 대상, 횟수, worker output인지 controller note인지 |
| state 크기 | 라운드별 compressed state 문자 수; 전체 prompt 크기와 구분 |
| coverage(k) | k번째 누적 호출 이내에 correct solution이 하나라도 생성되었는가 |
| monitoring | worker confidence와 controller verdict 각각이 정답 후보를 더 높게 순위화하는가; Type-2 AUC |
| selection | correct 후보가 존재한 run 중 correct 후보를 최종 제출한 비율 |
| frontier selection gain | correct 후보가 있는 run에서 실제 제출 정오 − 가장 깊은 terminal node들의 정답 비율의 평균 |

Monitoring의 AUC는 순위 구분력이지 confidence calibration이 아니다. coverage/selection에는 intermediate artifact를 독립 채점할 수 있어야 한다. ProgramBench는 현재 workspace를 제출하므로 text candidate처럼 report만 채점해서 같은 지표를 계산할 수 없다.

실패도 두 종류로 나뉜다. correct candidate가 한 번도 없으면 coverage-bound, 있었지만 다른 것을 냈으면 selection-bound다. 지시 개선이 생성 능력을 바꿨는지, 선택 능력을 바꿨는지 분리해 볼 수 있다. (p.7–8)

## 7. 현재 min_pilot에 적용한다면 — 논문 사실이 아닌 구현 제안

현재 framework의 `context`는 orchestrator가 작성하는 문자열이며 ID 부분집합 interface가 아니다. `runtime/trace.py`는 이미 llm_calls/messages/tool_calls/events JSONL, stage/delegation/worker 태그, message hash 기반 중복 제거를 제공한다. harness도 draft, 최종 instruction, 원 context, context_additions, sent_context와 report를 기록한다. 따라서 새 trace 시스템으로 갈아엎기보다는 **명시적인 artifact provenance를 보완**하는 것이 적합하다.

논문 전체 네 단계 controller로 교체하면 현재 연구의 개입 범위도 바뀐다. 우선 trace에서 활용할 수 있는 설계와 runtime을 바꾸는 설계를 분리해야 한다. 이 검토에서는 코드를 변경하지 않았다.

### 7.1 제안하는 저장 구조

```text
run/
  llm_calls.jsonl, messages.jsonl, tool_calls.jsonl, events.jsonl  # 기존 원본
  artifacts.jsonl       # 본문 또는 본문 참조 + 생성 출처
  context_links.jsonl   # 실제 전달한 artifact/발췌 provenance
  assessments.jsonl    # 후보별 verdict·판단 이유·판단 시점
  analysis/            # 원본에서 재생성 가능한 표·graph·사람용 timeline
```

예를 들어 worker output record는 다음 필드를 가질 수 있다. **논문 원본 schema가 아니라 제안이다.**

```json
{
  "artifact_id": "d2.execution.report",
  "kind": "worker_output",
  "delegation": 2,
  "stage": "execution",
  "worker": "gen_luna",
  "title": "...",
  "body_ref": "...",
  "source_call_id": "...",
  "instruction_ref": "...",
  "input_artifact_ids": ["d1.execution.report"],
  "input_context_ref": "...",
  "available_after_call": 17,
  "confidence": null,
  "status": "ok"
}
```

title과 confidence는 현행 prompt의 계약과 다르므로 기존 결과에서 확실한 값으로 취급하면 안 된다. prompt에 추가한다면 버전과 실험 조건 변경이 필요하다.

### 7.2 남겨야 할 provenance

- **선택과 실제 전달을 구분한다.** 선택 ID, 조회 성공 ID, 실제 전달 본문 hash와 순서, 누락과 절단 여부를 기록한다.
- **본문 전달과 요약 전달을 구분한다.** 현행 context는 자유 텍스트이므로 source artifact ID와 실제 전달 문자열을 함께 남긴다.
- **controller 조회와 worker context 전달을 구분한다.** 둘은 서로 다른 event와 edge다.
- **probe·verification·execution 경계를 유지한다.** 실제 채택한 instruction과 context additions를 연결점으로 삼는다.
- **결과가 이용 가능해진 시점을 남긴다.** 병렬 worker의 시작 순서와 완료 순서가 다르면 coverage(k)의 후보 집합도 달라진다.
- **채점은 별도 후처리 파일에 저장한다.** artifact ID, 평가기 버전, 정오, 채점 가능 여부를 남기고 gold는 모델용 memory에 넣지 않는다.
- **종료 이유를 남긴다.** 정상 종료, 예산 소진, fallback, 잘못된 ID를 구분하고 최종 답의 출처를 기록한다.

### 7.3 사람이 읽는 표시

기존 JSONL을 원본으로 유지하고 delegation마다 `draft → review/probe → 채택 판단 → rewrite/context additions → 실제 전달 → execution report`를 표시한다. 별도 artifact 표에는 ID, 종류, 생성 단계, 출처, 전달 대상, 판정, 최종 답 채택 여부를 나란히 보여준다.

논문에서 특히 참고할 부분은 **출력 계약에 분석 가능한 표식을 넣고, dispatch 시 context 선택을 기록하고, 생성 실패와 선택 실패를 분리하는 것**이다.

## 8. 재현 시 확인할 사항

- Appendix F의 schema는 num_repeats만 required로 지정하지만 설명은 memory_blocks를 첫 라운드 이후 mandatory라고 한다. schema와 자연어 요건이 다르다. (p.34)
- Dispatch prompt는 잘못된 finish ID에 최신 candidate fallback을 언급하지만 엄밀한 validation 구현은 공개하지 않는다. (p.28–29)
- compact state의 고정 길이 상한은 보장하지 않는다. ProgramBench에서는 state도 증가하며 index와 조회 body를 포함한 전체 입력 길이를 따로 측정해야 한다. (p.13–15)

이 사항들은 PDF만으로 구현을 단정하지 말고 재현 시 명시적으로 결정해야 한다.
