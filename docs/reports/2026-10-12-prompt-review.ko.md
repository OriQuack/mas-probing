# 현재 프롬프트 검토: 모호함, 정보 경계, state, 구성과 복잡성

검토일: 2026-10-12 KST. 대상은 작업 트리의 실행 `v14`, probe/refiner `r16`, evaluator `e4`다. 커밋에 저장된 이전 버전이 아니라 현재 파일을 읽었다. 프롬프트·코드·설정은 수정하지 않았다.

아래 1–8절은 수정 전 `v14/r16/e4` 검토 기록이다. 사용자 승인 후 적용한 `v15/r17/e5`, tools `v7` 변경은 9절에 별도로 기록한다.

`src/minpilot/prompts/` 전체와 실제 입력을 만드는 `harness.py`, 출력 소비자인 `controller.py`·`memory.py`, worker·reader 실행 코드를 대조했다. 기본 `multi` pool에서 삽입되는 역할 문장도 확인했다. 논문은 로컬 PDF Appendix B.1–B.4, D–E, 특히 pp.21–23의 state 갱신 규칙과 pp.27–29의 위임 계약을 직접 확인했다.

아래의 **확인된 계약**은 코드나 원문에서 확인한 사실이다. **위험**은 그 계약에서 가능한 오해이며, 실제 모델이 그 오류를 냈다는 관측이 아니다. **제안**은 효과를 검증하지 않은 수정 방향이다. 평가 전용 split과 정답은 읽지 않았고 유료 모델 호출은 하지 않았다.

## 1. 전체 판단

현재 프롬프트는 역할, 입력의 의미, 판단 기준, 출력 계약을 구분하고 있다. 대부분의 문장은 행동으로 연결되므로 전체를 AI Slop으로 분류할 근거는 없다. 특히 보이지 않는 이전 대화에 의존하지 않게 하는 설명과 원 질문의 기준을 보존하는 설명은 유지할 가치가 있다.

가장 큰 문제는 장황한 문체보다 **모델이 실제로 확인하거나 전달할 수 있는 정보와, 프롬프트가 요구하는 판단 사이의 틈**이다. State 자체는 유용한 구조지만, `supported`의 적용 범위, state를 압축·정리하는 기준, 승인 전후 context의 관계는 보완이 필요하다.

| 우선순위 | 항목 | 판단 |
|---|---|---|
| 높음 | 도구 결과 조회를 실제 관측 전체의 재검토로 오인할 수 있음 | 모델 답변·이미지·코드 실행마다 조회 가능한 증거의 범위가 다름 |
| 높음 | `supported`가 조건부 결론과 전제의 확정을 혼동하게 할 수 있음 | 현재 규칙은 조건 보존을 요구하지만 판정 예시가 없음 |
| 높음 | state 승인과 worker context 사이에 이전 판단이 남을 수 있음 | snapshot 규칙은 정확히 설명했으나 반전된 행을 전달할 때의 처리 설명이 부족함 |
| 중간 | probe에서 생성한 파일의 접근 가능성 | 대화뿐 아니라 workspace도 분리되지만 모델에게 파일 경계를 설명하지 않음 |
| 중간 | refiner가 읽은 record의 전달 여부 | 조회 결과는 executor에게 자동 전달되지 않음 |
| 중간 | state의 유지·압축·삭제 기준 | 누적 보존은 명시했으나 다음 판단에 불필요해진 내용의 정리 기준은 약함 |
| 중간 | `refs`의 증거 수준과 빈 목록 | ID 존재 검사와 사실 검증은 분리되어 있지만 빈 참조 허용 조건은 정의되지 않음 |
| 중간 | 처음 읽는 모델이 추측해야 하는 문구 | `adequate`, `when the distinction matters`, `approved changes`의 일부 경계 |
| 낮음 | 중복 입력과 advisory 필드 | 작은 중복은 있으나 제거 이득이 입증된 것은 아님 |
| 낮음 | reader의 답 없음·부분 문서 처리 | `refuse to answer`가 자료 부재의 범위를 충분히 설명하지 않음 |

## 2. 현재 구성과 형식: 유지할 부분

### 역할을 실제 작업으로 연결한다

[orchestrator.py:3](../../src/minpilot/prompts/orchestrator.py#L3)는 다음 결과 선택·위임·context 선택·종료를 첫 문단에 적는다. [evaluator.py:5](../../src/minpilot/prompts/evaluator.py#L5)는 보고의 의미 평가와 전체 state 제안을, [refiner.py:3](../../src/minpilot/prompts/refiner.py#L3)는 승인 변경의 표현을 지정한다. 역할 이름만 바꾸는 generic persona와 다르다.

`What you receive → 판단 기준 → 결과 작성 → memory 조회 → 출력 계약`의 흐름도 읽을 수 있다. 역할마다 필요한 절이 다르므로 순서를 완전히 통일할 이유는 없다. 특히 orchestrator의 executor 선택·reconsider 설명은 실제 분기를 반영한다.

### Input catalog와 본문을 구분한다

[orchestrator.py:8](../../src/minpilot/prompts/orchestrator.py#L8), [evaluator.py:10](../../src/minpilot/prompts/evaluator.py#L10)는 목록의 제목을 근거로 취급하지 말고 필요하면 본문을 읽으라고 한다. 논문 Appendix B.1·E의 index/body 구분을 현재 인터페이스에 맞게 반영했다.

### 이전 결과를 보존하고 원 질문의 범위를 확인한다

[evaluator.py:15](../../src/minpilot/prompts/evaluator.py#L15)의 원 질문과 실제 instruction을 함께 확인하는 규칙은 수정된 지시가 원 질문을 좁히는 문제를 직접 겨냥한다. 같은 파일의 19–23행은 추가 증명 요구, 기존 결과 뒤집기, 탐색 실패의 오해를 구분한다. 이는 한 문장으로 합치면 서로 다른 실패 조건이 사라질 수 있다.

Orchestrator의 재시도 근거, worker의 가정 보고, evaluator의 결과 보존, refiner의 새 판단 금지는 역할별 적용 지점이 다르다. 여러 파일에 비슷한 문장이 있다는 이유만으로 불필요한 중복이라고 볼 수 없다. 각 모델은 다른 system prompt를 받는다.

### JSON과 자유 형식 보고의 선택이 소비자와 맞는다

Controller 결정은 JSON이고 worker·probe 보고는 제목과 section을 갖춘 텍스트다. [memory.py:18](../../src/minpilot/memory.py#L18)는 worker 첫 줄의 `Title:`을 실제로 읽는다. 반면 worker의 네 section을 엄격히 파싱하는 코드는 없다. 따라서 section은 평가자가 읽기 위한 내용 구분이며 모든 문장 위치를 고정할 필요는 없다.

`schemas.py`만 보면 unused field에 null이 허용되지 않는 것처럼 보이지만, [client.py:58](../../src/minpilot/llm/client.py#L58)의 `strict_schema`가 optional field를 nullable로 바꾸고 모든 property를 required로 만든다. 실제 전달 schema에서 `worker_id: null`이 허용됨을 확인했다. **현재 null 지침과 schema가 충돌한다는 지적은 맞지 않는다.** Type별 state status 조합도 `memory.validate_state`가 검사한다.

## 3. state: 논문에서 가져온 것과 현재 추가한 것

### 논문의 state는 하나의 고정 형식이 아니다

Appendix B.1 text 버전(pp.21–22)은 후보별 평가와 전체 assessment, 종료 hint, 미해결 질문을 나눈다. `overall_assessment`를 compressed state라고 설명하지만 모든 태그를 런타임에서 어떻게 추출하는지는 공개하지 않는다.

ProgramBench 버전(pp.22–23)은 다음 다섯 의미를 구분한다.

| 논문의 구분 | 핵심 의미 | 현재 state에서 표현할 수 있는 곳 |
|---|---|---|
| implemented | 구현과 작동 증거가 함께 있음 | `result`/`observation` + `supported` |
| broken | 실패가 관측됨 | 실패 사실의 `observation` + `supported`, 미해결 작업의 `progress` |
| unverified | 구현 주장에 대한 확인이 없음 | `unverified`인 주장과 필요한 `progress` |
| unexplored | 대상에서 존재를 확인했지만 아직 하지 않은 일 | `progress/incomplete`와 대상의 관측 |
| dead_ends | 포기한 접근과 이유 | 접근·실패·포기 사유를 적은 `progress` |

위 표는 **현재 필드로 옮길 수 있는 해석**이며 저자들이 제시한 대응표가 아니다. `broken → rejected`로 단순 대응하면 안 된다. “빌드가 실패했다”는 관측은 supported이고 “빌드가 성공한다”는 주장은 rejected다.

논문에서 가져올 핵심은 section 철자보다 다음 규칙이다. 이전의 유효한 판단을 유지하고, 새 증거로 기존 항목을 갱신하며, 같은 대상을 중복 기록하지 않고, 근거로 되돌아갈 수 있게 한다. 현재 [evaluator.py:25](../../src/minpilot/prompts/evaluator.py#L25)는 이 규칙을 상당 부분 반영한다.

현재의 네 필드, claim/progress별 status, orchestrator의 전체 승인/거부, 행 번호에 의한 context 선택은 이 저장소의 설계다. 논문이 이 조합의 효과를 입증한 것은 아니다. 반대로 논문의 다섯 coding section을 GAIA에 그대로 옮기는 것도 적절하지 않다.

### S1. `supported`는 무엇까지 지지하는가

**문구:** [evaluator.py:29](../../src/minpilot/prompts/evaluator.py#L29)는 observation을 “something reported as observed”, assumption을 “an interpretation or premise”, result를 “a conclusion or calculation”로 정의한다. 31행의 supported는 “the cited evidence supports the stated claim”이다.

**좋은 점:** 유형은 주장의 성격, status는 지지 여부를 표현한다. 따라서 `assumption/supported` 자체는 모순이 아니다. 조건부 결론도 조건부 형태 그대로 지지될 수 있다.

**모호함:** worker가 관측했다고 쓴 사실, 출처가 그렇게 말한다는 사실, 외부 세계에서 그 내용이 참이라는 사실 사이의 경계가 예시 없이 남는다. 특히 조건부 result의 supported를 읽고 전제까지 확정됐다고 이해할 수 있다. 원문 17행에서 조건을 분리하라고 했지만 유형·status의 실제 적용을 보여주지는 않는다.

**제안:** 필드를 늘리지 말고 조건부 사례 한 쌍으로 경계를 보여준다. 예를 들어 다음 두 행은 동시에 가능하다.

```json
[
  {"type":"assumption","content":"두 번째 열이 수신자를 뜻한다.","status":"unverified","refs":["a00000"]},
  {"type":"result","content":"두 번째 열이 수신자라면 표에서 나온 후보는 Mina다.","status":"supported","refs":["a00000"]}
]
```

이는 설명용 가상 사례다. 두 번째 행은 Mina를 무조건 최종 답으로 확정하지 않는다. 이후 첫 행이 rejected로 바뀌어도 조건부 명제 자체는 유지될 수 있으나 현재 답 후보로 쓰면 안 된다. Worker에게 넘길 때 전제와 결론 중 필요한 내용을 함께 선택하거나 instruction에 조건을 적어야 한다. 새로운 dependency graph를 만들 필요는 없다.

Observation 예시도 “페이지에 X라고 적혀 있다”와 “X가 사실이다”를 구분하면 좋다. 출처 문구가 바로 정답 근거인 과제도 있으므로 모든 주장에 별도 원문·독립 검증을 강제해서는 안 된다.

### S2. `refs`가 있다는 것과 근거가 충분하다는 것은 다르다

**문구:** [evaluator.py:32](../../src/minpilot/prompts/evaluator.py#L32)는 refs가 근거 또는 가정·시도·장애물의 기록을 가리킨다고 설명하며, 참조 자체가 진실성을 보장하지 않는다고 명시한다. 이는 적절하다.

**남은 경계:** [memory.py:62](../../src/minpilot/memory.py#L62)의 검증은 ID 존재·type·status·content를 검사한다. `refs: []`도 허용한다. 이 동작을 대표 입력으로 확인했다. 따라서 현재 state는 논문 ProgramBench의 “citation이 없으면 항목을 넣지 않는다”를 런타임에서 강제하는 구조가 아니다. 빈 참조가 무조건 버그라는 뜻도 아니다. 원 질문에 이미 주어진 조건을 기록하는 경우가 있을 수 있다.

**제안:** 외부 관측·계산 결과·탐색 장애물을 기록할 때는 해당 보고나 도구 record를 가리키고, 원 질문에서만 온 조건은 그 사실을 content에 명시하도록 한다. 원 질문을 새 artifact로 만들거나 가짜 ID를 쓰게 해서는 안 된다. 특정 주장에 필요한 자료를 못 봤다면 status와 설명으로 한계를 남기되 전체 답에 불필요한 추가 입증 조건은 만들지 않는다.

### S3. 보존은 자세하지만 압축·퇴역 기준은 약하다

**문구:** [evaluator.py:26](../../src/minpilot/prompts/evaluator.py#L26)는 유효 항목 유지, status 갱신, 중복 제거, 충돌·미해결 작업 보존, 반복 시도의 요약을 요구한다. [evaluator.py:23](../../src/minpilot/prompts/evaluator.py#L23)는 실패한 검색의 terms·sources·read scope·cause·next clue를 보존하게 한다.

**위험:** 모든 단계의 완료 내역, 더 이상 쓸 가능성이 없는 rejected 후보, 과거 검색어를 계속 남길 수 있다. State는 모든 controller 입력에 다시 붙는다. [memory.py:85](../../src/minpilot/memory.py#L85)는 선택한 행의 refs 본문까지 context에 넣으므로, 지나치게 넓은 행·많은 참조는 worker 입력도 키운다.

**제안:** 다음 판단·답·재시도 방지에 필요한 현재 정보는 state에, 세부 이력은 artifact에 둔다는 기준을 붙인다. 같은 실패 경로는 이유와 재사용할 단서를 보존하며 압축한다. 더 이상 답이나 다음 행동에 영향을 주지 않는 항목은 제외할 수 있다고 설명한다. 해소된 과거 판단이 사라져도 원본과 `state_replace` 전후 trace는 남는다.

압축을 위해 임의의 행 수·문자 수를 정하는 것은 우선순위가 낮다. 길이만 제한하면 미해결 조건이나 실패 원인이 먼저 잘릴 수 있다. 논문도 index와 조회 body 때문에 전체 입력 길이가 상수라고 주장하지 않는다.

### S4. 전체 승인/거부는 단순하지만 유효한 새 판단까지 함께 보류할 수 있다

[orchestrator.py:24](../../src/minpilot/prompts/orchestrator.py#L24)와 [harness.py:237](../../src/minpilot/harness.py#L237)에서 state는 전부 채택하거나 전부 거부한다. 거부하면 이전 state를 유지하고 latest evaluation은 처리 후 비운다.

하나의 잘못된 포함 기준 때문에 유효한 새 관측까지 state에 반영되지 않을 수 있다. 이는 숨은 동작이 아니라 명시적인 설계 선택이다. 다만 다음 모델은 현재 state만 보면 유효한 새 관측을 놓칠 수 있다.

현재 구조 안에서는 거부한 proposal에서 필요한 보고를 `artifact_ids`로 전달하고 승인한 작업 기준을 instruction에 적을 수 있다. 문구 검토만으로 행별 편집, 재평가 호출, 새로운 patch schema를 도입할 이유는 없다. 이 제약이 실제 누락을 반복해서 만들 때 별도 설계 문제로 검토한다.

## 4. 정보 경계에서 생기는 모호함

### H1. state를 승인해도 이번 context에는 이전 status가 들어간다

**확인된 계약:** [orchestrator.py:35](../../src/minpilot/prompts/orchestrator.py#L35)는 `state_rows`를 승인 전 입력 snapshot에서 해석한다고 정확히 적는다. [harness.py:228](../../src/minpilot/harness.py#L228)도 먼저 context를 만들고 그 뒤 state를 채택한다. 따라서 행 번호 오류를 막는 설명은 이미 있다.

**남은 위험:** 입력 0번 행이 supported이고 proposal이 같은 주장을 rejected로 바꿀 때, `accept_state=true, state_rows=[0]`이면 accepted state는 rejected가 되지만 worker context에는 supported가 들어간다. 대표 입력으로 이 조합을 확인했다. 이는 실제 모델 오류를 재현한 것이 아니라 코드의 snapshot 동작을 확인한 것이다.

**제안:** 이번에 무효화·수정한다고 판단한 이전 행은 그대로 넘기지 말고 수정 근거의 report/evaluation artifact를 선택하고 현재 적용할 판단을 instruction에 적도록 한다. 과거 판단을 비교 목적으로 넘기는 경우에는 그 목적과 더 이상 적용하지 않을 조건을 명시한다. 단순히 “새 state의 행을 고르라”라고 고치면 현재 runtime과 충돌한다.

Refiner의 `relevant_state`도 [harness.py:380](../../src/minpilot/harness.py#L380)에서 **선택된 context 안의 state**를 복사한 값이다. 최신 accepted state 전체나 최신 관련 행을 다시 뽑은 값이 아니다. [refiner.py:6](../../src/minpilot/prompts/refiner.py#L6)에 이 의미를 적으면 처음 읽는 모델이 이름만으로 최신 판단이라고 해석할 가능성을 줄일 수 있다.

### H2. 도구 원문 조회가 원 관측 전체를 제공하지는 않는다

[evaluator.py:37](../../src/minpilot/prompts/evaluator.py#L37)는 “check an original tool observation”을 위해 saved ID를 읽게 한다. 하지만 `tNNNNN`이 반환하는 정보는 도구마다 다르다.

| 경우 | 실제 조회 범위 | 오해할 수 있는 판단 |
|---|---|---|
| `read_url` | 원 페이지를 읽은 reader 모델의 답변 | 도구 원문이므로 source 원문을 직접 확인했다고 간주 |
| `view_image` | “이미지가 아래에 표시됨”이라는 tool 텍스트 | ID를 읽었으므로 이미지 속 내용을 재검토했다고 간주 |
| `run_python` | 실행 결과 텍스트; 호출 코드·args가 record에 자동 결합되지는 않음 | stdout 숫자만 보고 계산식·대상 집합까지 검증했다고 간주 |

**근거:** [tools.py:5](../../src/minpilot/prompts/tools.py#L5)는 read_url이 모델 답변임을 이미 worker에게 설명한다. 실제 출력에도 [web.py:250](../../src/minpilot/tools/web.py#L250)의 reader 답변 label이 있다. 따라서 이 구분이 시스템 전체에서 숨겨져 있다는 주장은 맞지 않는다. 다만 evaluator가 적용할 증거 기준에도 이를 명확히 연결할 수 있다.

이미지는 [agents/worker.py:83](../../src/minpilot/agents/worker.py#L83)의 별도 user image message로 worker에게 전달된다. Memory는 [memory.py:28](../../src/minpilot/memory.py#L28)에서 tool message만 저장해 조회 record를 만들므로 image payload는 이 인터페이스로 재전달되지 않는다. 도구 호출 args와 코드도 `tool_calls` trace에는 존재하지만 `Memory.read`가 자동으로 제공하지 않는다. **전체 trace에서 증거가 유실됐다는 지적은 아니다.**

**제안:** 도구 record가 보여주는 내용까지만 확인했다고 말하도록 한다. 이미지 조회 사실과 이미지 해석, reader 답변과 source 문구, 계산 stdout과 계산 절차를 구분한다. 결정적인 계산은 worker 보고에 입력·식·포함 기준을 남기게 한다. 원 관측이 필요하지만 현재 인터페이스로 볼 수 없다면 그 한계를 적고 답에 영향이 있는 경우에 필요한 확인을 맡긴다.

Code·이미지 payload를 controller 조회에 결합하려면 runtime 변경이다. 프롬프트만 바꾸어 evaluator가 직접 실행·시각 검토할 수 있다고 적어서는 안 된다. 모든 reader 답변을 자동으로 unverified 처리하거나 항상 추가 호출을 요구하는 것도 과도하다.

### H3. probe가 만든 파일은 executor에게 자동 이어지지 않는다

[probe.py:22](../../src/minpilot/prompts/probe.py#L22)와 [orchestrator.py:29](../../src/minpilot/prompts/orchestrator.py#L29)는 이전 대화의 가시성을 설명하지만 파일의 가시성은 설명하지 않는다. [harness.py:288](../../src/minpilot/harness.py#L288)는 probe를 scratch 복사본에서 실행하고 executor는 main workspace에서 실행한다.

Probe가 `probe-table.csv`를 만들고 report에 경로를 적었다면 그 report를 context로 넘기는 것만으로 executor가 파일을 열 수 있게 되지는 않는다. 처음 보는 모델은 “보고서에 나온 작업 경로”를 공유 파일로 이해할 수 있다.

**제안:** probe에서 새로 생성한 파일은 자동 전달되지 않는다고 명시하고, 재사용할 관측은 보고에 필요한 내용·출처·재현 방법으로 남기게 한다. 기존 main workspace에서 복사된 attachment까지 모두 없다고 설명해서는 안 된다. 파일 전송 시스템을 새로 만들 필요는 없다.

### H4. refiner의 memory read는 context 선택과 다르다

[refiner.py:18](../../src/minpilot/prompts/refiner.py#L18)은 특정 record를 읽어 승인 변경을 표현하게 한다. 실제 전달은 [harness.py:387](../../src/minpilot/harness.py#L387)의 수정 instruction과 `context_notes`뿐이다. Refiner가 읽은 record 본문은 executor context에 자동 추가되지 않는다.

**위험:** refiner가 “t00007의 계산을 따르라”라고만 쓰면 worker는 그 record를 못 볼 수 있다. 기존의 self-contained 규칙이 간접적으로 막지만, read와 전달의 차이는 직접 적지 않았다.

**제안:** 읽은 정보가 실행에 꼭 필요하면 승인 범위 안에서 필요한 내용과 출처를 instruction 또는 context_notes에 표현한다. 전체 record를 전달할지 새 판단이 필요하면 reconsider에서 orchestrator의 선택을 요청한다. 단순 ID 인용만으로 전달이 끝난다고 간주하지 않는다. 기록을 읽었다는 이유로 새 증거를 평가·확정할 권한이 생기는 것도 아니다.

## 5. AI Slop과 처음 읽을 때의 해석 부담

여기서 AI Slop은 단어가 길거나 전문 용어라는 뜻이 아니라, **그럴듯하지만 실행 조건이나 판단 범위를 좁혀주지 못하는 문구**로 본다. `scope`, `evidence`, `supported`는 이 시스템의 실제 개념이므로 전부 쉬운 동의어로 치환할 필요는 없다.

| 현재 문구 | 남는 질문 | 최소 보완 방향 |
|---|---|---|
| “Keep an adequate draft unchanged.” (`orchestrator.py:42`) | 무엇이 adequate인가? | 필요한 결과·범위·조건·확인 가능한 근거를 이미 지정했고 실제 수행을 바꾸는 누락이 없으면 유지한다고 연결 |
| “Use saved evidence when the distinction matters” (`evaluator.py:10`) | 무엇의 distinction이며 언제 중요한가? | 보고와 원 관측의 차이가 대상·수치·포함 기준·실패 원인 판정에 영향을 줄 때 조회한다는 예시 |
| “Preserve a supported inference when the original task's criteria permit it” (`evaluator.py:19`) | 어느 근거면 허용되는 추론인가? | 조건부 후보와 확정 답을 구분하는 matched example; 모든 대안 배제는 요구하지 않음 |
| “approved changes” (`orchestrator.py:42`, `refiner.py:8`) | 승인한 문체 수정인가, 조사 계획 변경인가? | 판단은 orchestrator, 표현은 refiner라는 현재 경계를 유지하고 변경 내용·이유를 brief에 적음 |
| “context assembled by the harness” (`orchestrator.py:29`) | 어떤 text가 실제 들어가는가? | 선택한 행 + 직접 refs record + 명시 선택 artifact이며 모든 과거 record가 자동 확장되는 것은 아니라고 설명 |

첫 번째 문구는 31행의 assignment 요건과 함께 읽으면 의미를 상당 부분 추론할 수 있다. 따라서 모호함을 없애려는 명목으로 체크리스트를 모든 절에 반복할 필요는 없다. 관련 기준으로 짧게 연결하면 된다.

`target, conditions and answer scope`처럼 가까운 명사의 나열은 조금 추상적이지만, 대상·조건·답 범위는 실제로 다른 오류를 막는다. 무작정 하나로 합치면 기준이 사라질 수 있다. 필요한 곳에 예시를 붙이는 쪽이 유리하다.

논문 p.29의 BAD/GOOD은 같은 작업에서 누락된 정보를 보여준다. 현재 prompt에 예시를 넣는다면 모든 역할에 긴 few-shot을 추가하기보다 **state의 조건부 판정**, **승인 전 행과 수정 판단의 전달**처럼 자주 추측해야 하는 경계에 한 쌍씩 넣는 것이 타당하다. 예시는 새 규칙이나 특정 과제 정답을 몰래 추가해서는 안 된다.

## 6. over engineering: 줄일 후보와 유지할 구조

### 네 필드 state 자체는 과설계라고 보기 어렵다

Type은 정보의 종류, status는 그 정보에 대한 현재 판단, refs는 원본으로 돌아가는 경로다. Progress의 complete와 result의 supported를 나누는 것은 “할 일은 끝났지만 답은 불확실함”을 표현하는 데 필요하다. 이를 하나의 done/undone으로 줄이면 실제 의미가 손실된다.

현재 문제를 해결하기 위해 confidence 점수, 별도 conflict field, 행의 영구 ID, dependency graph, 새 verifier 단계를 더할 근거는 없다. 필요한 조건·충돌을 content에 적는 현재 방식으로 먼저 해결할 수 있다.

### 중복·추가 신호의 이득은 점검할 수 있다

- `relevant_state`는 refiner context의 state를 중복 전달한다. 독립적인 최신 평가 정보가 아니다. 유지한다면 의미를 설명하고, 제거 여부는 입력 가독성과 비용을 보고 결정한다.
- `requires_decision`은 [evaluator.py:47](../../src/minpilot/prompts/evaluator.py#L47)에 advisory라고 명시되어 있고 harness의 별도 실행 분기를 만들지 않는다. 중요한 변경을 강조하는 모델 입력으로는 쓸 수 있지만, 자동 보호 장치로 설명하면 안 된다. 삭제는 출력 계약 변경이므로 단순 문장 정리와 구분한다.
- Orchestrator는 작업 선택·state 채택·executor 선택·refinement·memory read·종료를 하나의 system prompt에서 처리한다. 이는 실제 역할 범위이므로 길다는 이유만으로 역할을 더 나눌 필요는 없다. 분기별 필드 표는 처음 읽을 때의 부담을 줄이는 작은 개선이다.
- 현재 실행 경로가 참조하지 않는 `probe.followup_message`, `worker.context_with_additions`, `parse_probe`가 남아 있다. 저장소 검색상 정의·일부 export 외의 호출을 찾지 못했다. 이 문구를 현재 모델 입력의 일부로 분석하면 안 된다. 정리는 코드 유지보수 사안이고 현재 모델 동작을 바꾸는 prompt 개선은 아니다.

### 실제 길이는 원인 진단의 보조 자료다

기본 multi pool을 렌더링하고 Python의 `len(text.split())`으로 센 값이다. Token 수가 아니며 동적 task·state·catalog·schema·도구 schema는 제외했다.

| 입력 | 문자 수 | 공백 기준 단어 수 |
|---|---:|---:|
| Orchestrator system | 7,993 | 1,184 |
| Evaluator system | 6,297 | 974 |
| Refiner system | 3,175 | 482 |
| Worker system, 역할·도구 설명 포함 | 3,341 | 525 |
| Probe system + 예시 초안의 probe instruction | 3,187 | 503 |
| Reader template | 264 | 40 |

길이만으로 과설계를 판정할 수 없다. Orchestrator·evaluator는 의미가 가까운 보존·scope 문장을 다듬을 수 있으나, 먼저 줄일 대상은 실제 입력에서 중복되는 자료와 state의 오래된 세부 이력이다. “20% 짧게” 같은 목표로 운영 경계를 삭제하지 않는다.

## 7. 역할별 나머지 검토

### Orchestrator

구성은 실제 순서와 맞는다. `direct_execution`/`multi_worker_probe`와 `next_action`/`select_executor`/`refiner_reconsider`라는 조건·요청·action의 세 종류 이름이 함께 나오므로 처음 읽을 때 부담은 있다. 내부 이름을 감추면 JSON 계약을 따를 수 없으므로, 이름을 새로 만들기보다 마지막 출력 절을 request/action/필수 필드의 짧은 표로 정리하는 정도가 적절하다.

Unused는 null, 빈 선택은 [], 변경 없음은 빈 문자열이라는 차이는 의도된 계약이다. Action별 예시 하나가 도움될 수 있지만 모든 JSON을 매번 길게 반복할 필요는 없다. 강제 finish는 증거를 추가하지 않는다는 19행도 유지한다. 근거가 전혀 없는 강제 종료에서 어떤 답을 택할지는 scoring·런타임 정책 문제이므로 문구 검토에서 새로운 abstain 규칙을 만들지 않는다.

### Evaluator

핵심 판단은 좋지만 가장 설명이 밀집한 역할이다. 17–23행의 집계·조건부 결론·과도한 증명·기존 결과 보존·검색 실패는 서로 다른 검사다. 이를 “be rigorous”로 압축하면 품질이 떨어질 수 있다. 설명을 늘리기보다 state 예시에 이 기준이 어떻게 반영되는지 보여주는 것이 낫다.

`requires_decision`이 false여도 orchestrator의 채택 여부가 필요하고 true여도 자동 재검토를 시작하지 않는다. 문구는 이 사실을 이미 설명한다. 이름만 보고 controller 기능이 있다고 해석하지 않아야 한다.

### Refiner

현재 역할은 승인된 변경을 문장으로 쓰는 것으로 제한되어 있다. “새 판단은 reconsider”와 “반복 refinement 없음”도 구체적이다. “필요하면 추가 조사하라” 같은 문장을 넣으면 현재 아키텍처와 충돌한다. `context_notes`는 설명용 텍스트이며 조회한 도구 record를 자동으로 추가하는 필드가 아니라는 점을 명확히 하면 된다.

### Probe

Understanding/assumptions/risks/plan은 후보 executor를 비교하는 목적에 맞는다. Empty assumptions/risks를 허용하는 규칙도 형식 채우기를 막는다. 도구는 특정 가정·위험 확인에만 쓰게 하며 task 전체를 수행하지 말라는 경계도 있다.

다만 `Keep each item short`와 “whole subtask” 계획은 어느 정도 상세해야 하는지 판단을 남긴다. 핵심 방법·출처·실패 시 대안을 적되, 일반적인 위험을 늘리지 말라는 현재 기준이면 대체로 충분하다. 기계적 글자 수·단계 수를 추가할 필요는 없다. 생성 파일의 격리 설명을 우선 보완한다.

### Worker

Result/Evidence/Interpretation/Unfinished는 평가자에게 필요한 정보를 구분한다. 모든 section을 JSON으로 바꾸는 것은 현재 소비자 요구보다 크다. 어려운 작업에서는 실패한 검색과 계산 기준을 보고해야 하지만, 단순 조회에서도 빈 section을 장황하게 채울 필요는 없다. 현재 “없으면 짧게 쓰라”는 지침을 유지할 수 있다.

최종 응답 전 결론과 실제 관측·계산을 맞추라는 29행은 유용하다. 현재 작업이 변경 파일을 내는 경우에는 논문 p.32의 시간 원칙처럼 “마지막 수정 후 검사한 결과”라고 보고하게 할 여지가 있지만, 이 검토를 이유로 모든 GAIA 작업에 commit·build를 강제해서는 안 된다.

### Reader·task·tools

[reader.py:8](../../src/minpilot/prompts/reader.py#L8)의 `clearly refuse to answer`는 “이 source에 필요한 정보가 없다”보다 범위가 넓다. 부분 문서를 읽는 `PART_PROMPT`에서도 같은 문장이므로 한 part에서 못 찾은 것을 문서 전체의 부재로 과장할 수 있다. 관련 정보가 없으면 제공된 source/part에서 찾지 못했다고 쓰고, 부분 정보가 있으면 확인한 내용과 남은 공백을 보고하는 표현이 더 명확하다. 이는 verbatim으로 유지해온 도구 prompt이므로 실제 변경 시 tool version·cache 영향도 확인해야 한다.

`PROMPT`와 `PART_PROMPT`의 구분자 공백 차이나 “answer a following question” 같은 영어 어색함은 낮은 우선순위다. 현재 source 지위의 상세 설명이 없다는 점은 관찰할 수 있지만, delimiter를 하나 바꿔 완전한 신뢰 경계가 생긴다고 주장할 수는 없다.

Task의 run date와 문제 기준 시점을 구분하는 문구는 구체적이며 유지할 만하다. Tools 설명도 reader 답변/raw text/string search를 구분해 준다. 사용 조건은 실제 tool schema에도 있으므로 prompt 설명만 보고 제공되는 옵션을 모두 파악했다고 간주하지 않는다.

## 8. 수정 순서와 검증 범위

먼저 현재 역할·schema·호출 수를 보존하면서 다음을 보완하는 순서가 적절하다.

1. 도구 record로 확인 가능한 범위와 state supported의 적용 범위를 설명한다.
2. 무효화된 이전 state 행을 이번 context로 넘길 때의 처리와 관련 state의 snapshot 의미를 명확히 한다.
3. Probe 생성 파일과 refiner memory read의 전달 경계를 설명한다.
4. State에 남길 내용·artifact에 둘 이력의 기준을 적고 필요한 예시만 붙인다.
5. 그 뒤에 중복 문장과 request별 출력 설명을 정리한다.

이는 수정 제안이며 이 보고서에서 prompt를 재작성하지 않았다. Schema·state 필드·approval 방식을 바꾸는 안은 별도 설계 변경으로 구분해야 한다. 이후 실제 수정에서는 저장소 규칙에 따라 실행/probe/refiner/evaluator의 해당 버전과 실험 기록을 갱신한다. 문구를 바꿨다는 이유만으로 성능이 개선됐다고 보고하지 않는다.

검증은 기존 오프라인 계약 검사 4개 파일(`test_context.py`, `test_execution_prompts.py`, `test_orchestrator.py`, `test_review_pipeline.py`)을 실행했고 **24개가 통과**했다. 별도 임시 대표 입력으로 다음을 확인했다.

- 승인 전 context가 supported이고 승인 후 state는 rejected인 조합이 가능하다.
- 현재 state validator는 refs가 빈 목록인 행을 허용한다.
- 실제 strict schema는 unused worker_id의 null을 허용한다.
- Memory의 tool record에는 원 호출 args와 별도 image payload가 자동 포함되지 않는다.

이 검사는 코드 계약을 확인한다. 실제 모델의 모호함 해소, 오류 감소, 비용 절감은 검증하지 않았다. 기존 scripted walkthrough의 정해진 모델 출력도 prompt 효과의 증거로 취급하지 않았다.


## 9. 검토 후 적용한 변경

이 절은 원 검토 뒤 사용자 승인을 받아 적용한 구현 기록이다. 기존 진단의 위험을 실제 모델 실패로 바꾸어 서술하지 않는다.

| 지적 | 적용 | 범위·남은 한계 |
|---|---|---|
| H1: state 승인과 이전 context 판단의 불일치 | 채택 제안에서 변경·삭제된 이전 행을 선택하면 harness가 거부하고 기존 1회 수정 요청을 사용. Prompt는 수정 근거 기록과 현재 판단을 instruction에 전달하도록 설명 | 행 번호는 여전히 입력 snapshot 기준. 같은 행의 status뿐 아니라 content·refs 변경과 삭제도 검사. 의미가 다른데 문구가 같은 판단을 감지하는 검사는 아님 |
| H2: 도구 결과의 확인 범위 | 저장된 tool_call_id로 원 호출 이름·arguments를 연결. Evaluator에 reader 답변, 이미지 payload, 코드 조회와 재실행의 차이를 설명 | 이름·인자가 없는 호출은 없는 그대로 저장. 이미지 payload는 memory로 재전달하지 않음. 도구 결과 조회가 source 전문 확인이나 코드 재실행을 뜻하지 않음 |
| H3: probe 생성 파일 | Probe와 orchestrator에 새 파일이 executor에게 자동 전달되지 않는다고 명시 | 기존 attachment 복사는 유지. 파일 전달 기능은 추가하지 않음 |
| H4: refiner 조회와 전달 | 조회 내용은 자동으로 context에 추가되지 않으며 필요한 내용·출처를 instruction/context_notes에 써야 함을 명시. Relevant_state는 선택 context의 행 복사본이라고 설명 | 새 판단이나 context 선택이 필요하면 기존 reconsider 사용 |
| S1·S2: supported와 refs | 조건부 계산의 지지와 전제 확정을 분리한 일반 예시. 원 질문에서만 온 조건의 빈 refs 허용을 설명 | 새 증거 등급·독립 검증 의무·state 필드는 추가하지 않음 |
| S3: state 유지·정리 | 답·다음 행동·실패 경로 반복 방지에 필요한 내용 유지. 반복 이력은 요약하고 세부는 artifact에 보존 | 미해결 조건·반대 근거는 유지. 행 수·문자 수 제한은 추가하지 않음 |
| Reader의 답 없음 | 제공된 source/part에서 찾지 못한 범위와 부분적으로 답한 내용을 보고 | Reader 동작 변경을 tools v7, tools_v7.sqlite로 분리. 기존 cache는 수정하지 않음 |

실행 `v15`, probe/refiner `r17`, evaluator `e5`로 버전을 갱신했다. 역할 소개·절 구성·state 네 필드·전체 승인 방식·위임 순서는 유지했다. S4의 전체 승인 제약, advisory 필드·중복 입력·미사용 helper 정리는 별도 변경하지 않았다. 과제 이름·정답은 production prompt에 추가하지 않았다.

전체 오프라인 테스트 **147개가 통과**했다. 채택할 state에서 status·content·refs가 바뀌거나 삭제된 행 선택의 거부·수정 경로, 수정 실패 시 이전 state 보존, 제안 거부 시 기존 행 전달, 도구 호출 인자의 원문 보존·복원을 검사했다. 문서 링크와 `git diff --check`도 통과했다. 유료 호출과 새 live 실험은 수행하지 않았다. 테스트 통과는 계약 동작의 근거이며 실제 모델의 오류 감소를 입증하지 않는다.


## 10. 갱신 권한 재검토 후 적용한 변경

사용자 피드백에 따라 승인 절차 자체를 제거했다. 9절의 H1 대응은 기존 구조를 유지하기 위한 임시 보완이었으며, 아래 변경으로 대체한다. 검토한 Secret Santa·USDA·arXiv direct trace의 state 승인 10건은 모두 채택이었다. ArXiv에서는 승인 설명이 기준 불변을 말하면서도 후속 지시가 당시 가용성 증명을 요구했다. 이 표본은 승인 단계의 보호 효과를 입증하지 않으며, 전체 조건에서 무용함을 입증한 것도 아니다.

- Evaluator는 평가와 state 갱신을 담당한다. 출력 형식·참조가 유효하면 harness가 즉시 전체 목록을 저장한다.
- Orchestrator는 최신 state에서 다음 작업·executor·전달 기록·행을 선택한다. 평가 승인·거부·근거 상태 재판정은 맡지 않는다.
- 승인 필드와 `requires_decision`, 승인 전후 목록 충돌 검사를 제거했다. Context 행 번호는 갱신이 끝난 입력 snapshot 기준이다.
- Refiner의 별도 재검토 호출을 제거했다. 수정에 새 판단이 필요하면 `can_refine=false`와 이유를 반환하고 선택된 초안을 유지한다.
- Evaluator 실패 시 state는 그대로이며 새 보고와 실패 원문을 보존한다. 실패를 orchestrator가 대신 평가하도록 원 보고 전문을 자동 전달하지 않는다.
- Probe 평가 뒤 위임 전 예산이 소진되면 이전 state 행을 fallback context에서 제외하고 기존 근거 기록과 최신 평가 기록을 전달한다.

현재 실행 v16, probe/refiner r19, evaluator e6, tools v7이다. 네 필드 state·참조 ID·전체 교체 저장·probe 순서·예산과 독립 workspace는 유지한다. State 변경 전후와 evaluator 근거, 선택 snapshot, 실제 context·최종 지시는 계속 trace에 남긴다. 기존 snapshot·실험 결과는 바꾸지 않았다. 전체 오프라인 테스트 147개가 통과했다. 검사는 최신 state의 수정·삭제·참조 변경이 선택과 checkpoint에 반영되는지, orchestrator가 state를 덮어쓰지 못하는지, 평가 실패·refiner 수정 불가·예산 fallback을 확인한다. 후속 [실제 pilot 3개 진단](2026-10-12-evaluator-owned-state-live.ko.md)에서 갱신·선택·전달 계약을 확인했다. 2/3 정답, 총 $0.18047882였으며 Secret Santa의 답 보류는 남았다. 단일 조건·각 1회이므로 기준 강화·답 보류의 개선 효과를 입증하지 않는다.
