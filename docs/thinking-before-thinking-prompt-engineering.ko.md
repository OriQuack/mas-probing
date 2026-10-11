# Thinking Before Thinking: Appendix 프롬프트의 prompt engineering 분석

검토 대상은 `Thinking Before Thinking- Scaling Agentic Inference Through Meta-Reasoning.pdf`(arXiv:2609.38147v1)의 Appendix B–I 프롬프트 원문이다. 쪽수는 PDF 쪽수이며 인쇄 쪽수와 같다.

기존 문서와 역할을 나눈다.

- [작성 기법 분석](thinking-before-thinking-prompt-writing.ko.md): 문장, heading, tag, 예시 같은 표현 기법
- [구조·memory·trace 분석](thinking-before-thinking-analysis.ko.md): 입출력 조립, memory pool, artifact graph

이 문서는 프롬프트를 행동을 지정하는 정책으로 정리한다. 다음 세 질문을 본다.

1. 각 프롬프트는 어떤 행동을 지시하거나 금지하는가. 어떤 수단을 쓰는가.
2. 한 단계 프롬프트가 참조하는 정보가 공개된 입력 명세에 있는가.
3. 비교 조건(Meta-Reasoning과 Direct Control)의 프롬프트 내용은 어떻게 다른가.

**근거의 범위.** 이 문서는 공개된 프롬프트 문면만 분석했다. 실제 trace는 보지 않았으므로 모델이 각 문구를 어떻게 따랐는지는 알 수 없다. 논문에는 프롬프트 문구 단위 ablation이 없다. 따라서 이 문서는 프롬프트 문구와 실험 결과 사이의 인과를 주장하지 않는다. 문구와 결과를 나란히 놓은 곳은 검증되지 않은 대조로만 읽어야 한다. 원문 관찰, 논문 저자의 설명, 분석자의 해석·제안을 구분해 적는다.

## 요약

1. **입력 구성도 단계마다 다르게 설계되어 있다.** Propose는 budget을 받지 않는다. 논문은 그 이유를 비싼 대안도 후보에 들어가게 하려는 것이라고 설명한다 (p.5). worker는 controller의 deliberation을 보지 않는다. worker가 받는 memory 블록에는 기본적으로 ID가 없다. Propose 사례 외의 은닉 효과는 측정되지 않았다.
2. **Meta-Reasoning(MR)의 종료 문구는 모든 단계에서 계속하는 쪽을 기본값으로 둔다.** Direct Control(DC) 프롬프트에는 이런 기본값이 없다. 두 조건의 예산 사용률은 크게 다르다(ProgramBench 1200 calls에서 MR 89–101%, DC GPT-5.5 약 18%). 그러나 두 조건은 단계 구조, state, memory 접근, 프롬프트 문구를 함께 바꾼다. 그래서 문구가 이 차이에 기여했는지는 알 수 없다.
3. **text 프롬프트에는 재검토와 변경을 요구하는 문구가 여러 단계에 있다.** 반면 맞는 답을 유지하거나 재현해도 된다는 명시 문구는 없다. 논문은 chess subset에서 재검토가 맞는 답을 흔드는 사례를 예비 관찰로 보고한다. 하지만 이를 프롬프트와 연결하지 않았다. worker 프롬프트는 두 조건에서 동일하므로 worker 문구만으로 두 조건의 차이를 설명할 수도 없다.
4. **공개된 입력 명세만으로는 확인되지 않는 참조가 있다.** text Dispatch의 입력에는 Propose 출력이 없는데도 worker 지시를 작성하라고 한다. Evaluate의 STOP 조건은 Assess의 verdict와 미해결 질문을 참조하지만, 그 정보가 Evaluate 입력에 들어가는지 불명확하다. 구현이 보완했을 수 있으므로 결함 확정이 아니라 재현 시 확인할 항목이다.
5. **ProgramBench 버전은 STOP 조건을 상태 원장과 별도 검증 여부로 정의한다.** text 버전은 "stake the run"이라는 확신 표현으로 정의한다.
6. **monitoring 분석의 두 신호는 프롬프트가 만든다.** Assess verdict의 label 정의에는 후속 행동 권고가 함께 들어 있고, 새 후보에 대해서만 요청된다. 이 label을 정답 판단으로만 해석할 때는 주의가 필요하다.
7. **두 조건은 의사결정 휴리스틱 문구도 다르다.** 차이는 양방향이며, 병렬 worker 다양성 안내는 DC 쪽이 더 명시적이다. 논문은 설계 전체의 효과만 주장하고 구성요소별 귀속은 하지 않는다고 밝힌다 (p.20). 문구 차이도 그 설계 전체에 포함되는 요소로 읽어야 한다.
8. **RLM appendix에는 규칙과 거부만으로 의도한 행동이 나오지 않은 사례가 있다.** 저자들은 grammar 제한으로 능력을 제거하고, 프롬프트로 제약을 미리 알렸다. 그 뒤에도 한 모델은 계속 계산을 시도했다.

## 1. 단계별 프롬프트가 지정하는 정책

| 지정 대상 | 프롬프트 수단 | 위치 |
|---|---|---|
| 무엇을 보는가 | 단계별 입력 블록, 제외한 정보 | 각 user message, Appendix E |
| 어떤 작업을 하는가 | 평가·제안·가치 판단·변환을 단계별로 분리 | B.1–B.4 첫 단락 |
| 언제 멈추는가 | 두 단계 판단, ALL 조건, 기본값 | Assess `<stop_recommended>`, Evaluate STOP |
| 얼마나 쓰는가 | 비용 서술, 종료 질문의 표현 | Evaluate 첫 단락, STOP 마지막 문장 |
| 무엇을 믿는가 | 알려진 실패 경고, 증거 기준 | Assess, Evaluate, git tool |
| 무엇을 넘기는가 | self-contained steering, BAD/GOOD 예시 | ProgramBench Evaluate·Dispatch |

### 1.1 단계별 입력 구성

| 단계 | 받는 것 | 받지 않는 것 | 원문의 설명 또는 관찰 |
|---|---|---|---|
| Assess | task, index, 이전 state, **새 artifact 전문** | 과거 artifact 본문(필요하면 read) | 논문은 Assess의 read가 거의 없는 것을 이 입력 구성으로 설명한다 (p.13) |
| Propose | task, index, 이번 state | **budget** | 비싼 대안도 후보에 들어가게 한다 (p.5) |
| Evaluate | 위 + proposals, **budget** | 새 artifact 전문 | "This is the only stage given the budget" (p.25) |
| Dispatch | task, index, Evaluate 출력 | proposals, state | 선택된 행동을 tool call로 바꾼다 (p.5, 28) |
| Worker | task, steering, 선택된 artifact body | controller state·deliberation, 기본 렌더링의 artifact ID | 지시와 artifact context는 controller가 정한다 (p.31, 33). ProgramBench worker는 공유 filesystem도 볼 수 있다 (p.4) |

Propose의 budget 제외는 입력과 문장 두 곳에서 지정된다. 입력에서 budget을 빼고, 문장으로 "do not self-filter or limit to a few safe options"라고 한다 (p.24). 논문이 밝힌 목적은 대안 생성과 비용 판단을 분리하는 것이다 (p.5). 이 분리가 실제로 후보 집합을 바꿨는지는 측정되지 않았다.

**재사용 시 고려 (분석자 제안, 효과 미검증):** 어떤 단계가 고려하지 않기를 바라는 정보는 지시로 금지하는 대신 입력에서 뺄 수 있다. 이 방식과 지시 방식의 효과 차이는 이 논문에서 검증되지 않았다.

### 1.2 발산 지시와 하류의 grouping 지시

Propose는 가능한 행동을 넓게 생성하라고 지시받는다.

> Think broadly and generate all plausible next actions --- do not self-filter or limit to a few safe options. (p.24)

action 예시 목록 끝에는 "these are starting points, not a fixed menu"를 붙인다.

ProgramBench Evaluate는 Propose 출력이 잘게 나뉠 수 있다고 전제하고 grouping을 지시한다.

> Propose may emit very fine-grained actions. Before rating, group coherent actions together [...] and evaluate the group as a single unit. (p.26)

추천 블록도 "one worker per group, not per atomic action"이라고 적는다 (p.27). 공개된 프롬프트에서 action 크기에 대한 조정은 Propose가 아니라 Evaluate에 있다. 잘게 나뉜 출력이 Propose의 넓게 생성하라는 지시 때문인지, ProgramBench 과제 성격 때문인지는 원문에 없다.

**재사용 시 고려:** 다단계 프롬프트에서 한 단계의 출력 지시를 바꾸면 하류 단계가 받는 입력의 형태(예: action 크기)도 함께 확인한다.

### 1.3 종료에 두 단계의 판단을 거치게 한다

Assess의 STOP은 높은 문턱을 가진 hint다.

> STOP <id> ONLY if you would stake the run on the candidate being a correct and correctly formatted solution, having read every step and found no unjustified leap, missing case, or hidden assumption. (p.22)

Evaluate는 그 hint를 그대로 받지 말라고 지시받는다.

> You make the final stop/continue decision --- do not rubber-stamp the assess stage's stop_recommended signal. (p.26)

이어서 hint가 틀릴 수 있는 경로를 적는다. worker가 미묘한 오류가 있는 후보에도 HIGH를 매기고, Assess가 그 과신을 물려받을 수 있다는 것이다. STOP은 (a) Assess의 LIKELY_CORRECT와 관련 미해결 질문 없음, (b) 나머지 행동이 모두 LOW_VALUE, (c) "stake the run" 수준의 확신을 **모두** 충족해야 한다.

두 단계가 같은 모델이고 (a)가 Assess의 판단을 전제한다. 따라서 "independently weigh"라는 문구가 판단의 통계적 독립성을 보장하지는 않는다. 이 이중 판단이 premature STOP을 얼마나 줄였는지도 측정되지 않았다.

### 1.4 특정 실패를 명명하는 경고

다음 문구들은 특정 실패를 명명하고, 대신 할 행동을 함께 지시한다.

| 명명된 실패 | 원문 | 위치 | 함께 지시하는 행동 |
|---|---|---|---|
| worker 과신 | "workers tend to self-rate HIGH on candidates that contain a subtle error" | Assess p.22, Evaluate p.26 | CONTINUE 기본값, Evaluate의 별도 STOP 판단 |
| 판단 전파 | "assess may inherit that overconfidence" | Evaluate p.26 | hint를 rubber-stamp하지 않는다 |
| 공유 가정에 기반한 합의 | "whether that convergence reflects independently sound work rather than a shared assumption" | Assess p.22 | outstanding_questions에 공유 가정을 남긴다 |
| 근거 없는 worker 서술 | "Worker prose claims without a corresponding commit or trace are not facts" | ProgramBench Assess p.22 | citation 없는 항목은 쓰지 않는다 |
| 서술과 코드의 괴리 | "Worker prose can be optimistic or hallucinated; the commits are the ground truth" | git tool p.37 | read-only git으로 실제 코드를 본다 |
| 사전지식으로 대체 | "Pull from the binary's own self-description, not pretrained knowledge" | ProgramBench Assess p.23 | `--help`, README, 문서에서 worklist를 만든다 |
| 미검증을 완료로 간주 | "Untested != done" | ProgramBench Evaluate p.27 | 검증 dispatch를 STOP보다 먼저 한다 |
| 이전 build 상태 추정 | "don't infer build status from an earlier turn" | ProgramBench worker p.32 | 마지막 수정 후 다시 build한다 |

worker 과신 경고는 Assess와 Evaluate 두 곳에 있다. 이 경고들의 효과는 따로 측정되지 않았다. 논문은 controller verdict가 worker confidence보다 정답을 더 잘 구분한 설정이 여럿이라고 보고한다 (p.12). 그러나 이를 경고 문구에 귀속하지 않는다.

### 1.5 채점 기준에 맞춘 가치 정의

ProgramBench Evaluate는 action의 가치를 채점 기준으로 정의한다.

> Scoring is by test cases passed. Rate actions on their likely effect on test coverage, not on code quality. A refactor of code that already passes is LOW_VALUE [...] Ugly, hardcoded, or narrow implementations are fine as long as they pass. (p.26)

text 쪽은 기대 이득을 "a correct, correctly formatted answer"에 가까워지는 정도로 정의한다 (p.25). worker와 DC 프롬프트도 형식이 정답의 일부라고 적는다 (p.30, 32).

ProgramBench 문구는 코드 품질을 명시적으로 낮게 평가한다. 채점 기준이 다른 환경에 그대로 옮기기에는 적절하지 않다.

### 1.6 의사코드로 쓴 결정적 규칙

Dispatch는 분기와 계산을 의사코드에 가깝게 적는다 (p.28).

```text
If recommendations[0].action_id == "STOP": call finish(memory_id=...)
num_repeats = sum of parallel_workers across all recommendations
len(subagent_prompts) == len(memory_blocks) == num_repeats
```

STOP도 별도 출력 형식이 아니라 같은 YAML 안의 `action_id: STOP`으로 표현한다. 입력이 비거나 깨지면 context 없는 worker 하나를 실행하라는 fallback이 있고, 그 이유를 "do not stall the dispatch step"이라고 적는다. 프롬프트는 잘못된 ID를 쓰면 최신 후보로 fallback된다는 결과도 알린다.

text Dispatch의 작업 중 YAML 파싱, worker 수 합산, ID 목록 복제는 결정적 변환이다. 결정적이지 않은 작업은 worker 지시 작성, 지시 변형, 선택적 memory 읽기·쓰기다. Dispatch는 controller 단계이므로 매 cycle 호출 비용이 든다.

**분석자 제안 (논문에서 실험하지 않음):** 결정적 변환과 ID 검증은 코드로 하고, 지시 작성만 LLM에 맡기는 구성을 고려할 수 있다.

## 2. 종료 기본값과 예산 관련 문구

MR의 종료 관련 문구는 단계마다 계속하는 쪽을 기본값으로 둔다.

| 위치 | 원문 |
|---|---|
| Assess (p.22) | "Default to CONTINUE. The risk of premature STOP is high [...] If you have ANY doubt, output CONTINUE." |
| Evaluate text (p.26) | "Otherwise --- including when in doubt --- output the normal action recommendation block above. Spending more budget on refinement is generally safer than premature STOP when budget remains." |
| Evaluate ProgramBench (p.27) | "While budget remains, the question is not "are we done?" but "would one more worker dispatch add more than nothing?" --- if yes, CONTINUE." |
| DC (p.30) | "[...] or call `finish` with the candidate you trust most." |
| DC budget (p.31) | 10%마다 `BUDGET` 메시지, 90%에 `FINISH NOW` |

ProgramBench 문장은 종료 판단의 질문을 "끝났는가"에서 "한 번 더 보내면 0보다 나은가"로 바꿔 적는다. 문면상 계속하는 쪽의 기준이 낮다. STOP 문단은 premature STOP의 위험만 언급한다. 행동별 비용은 따로 evaluation 블록에서 기대 이득과 비교하도록 지시한다 (p.25–26).

논문이 보고한 관련 결과는 다음과 같다.

- ProgramBench 1200-call 설정에서 MR은 모델에 따라 예산의 약 89–101%를 썼다. DC는 GPT-5.5에서 약 18%를 썼다 (p.10).
- 논문은 조기 종료만으로 차이가 설명되지 않는다고 적는다. Opus 4.8 DC는 호출을 376에서 768로 늘렸지만 점수는 62.7%에서 65.3%로 올랐고, 중간 예산에서 정점이었다 (p.11).
- 작은 예산에서는 MR이 낮다. Opus 4.8 ProgramBench 400 calls에서 56.6% 대 62.7%다. 논문은 이를 staged control의 비용이 회수되는 데 시간이 걸린다는 것과 일관된다고 설명한다 (p.11).
- 논문은 DC의 긴 history가 예산 증가에도 성능이 오르지 않는 이유의 일부일 수 있다고 따로 언급한다. 다만 직접 검증하지 않았다고 밝힌다 (p.13).

이 결과로 종료 문구의 기여를 추정할 수는 없다. 두 조건 사이에는 종료 문구뿐 아니라 단계 구조, state 압축, memory 접근, history 길이가 함께 다르다. 논문은 이를 분리하지 않았다 (p.20). 종료 문구는 사용률 차이와 관련될 수 있는 여러 요인 중 하나로만 기록해 둔다.

프롬프트가 제시하는 비용 서술도 본문 설명과 다르다. Evaluate 프롬프트는 "Each deliberation turn [...] also costs 4 LLM calls"라고 하지만, 본문은 각 단계가 tool 호출 때문에 여러 번 호출될 수 있다고 설명한다 (p.5, 20). 실제 소비량은 `{budget}` 입력으로 전달된다.

**분석자 제안:** 종료 기본값은 과제의 비용 구조에 따라 정할 정책이다. 일찍 멈추는 비용과 오래 계속하는 비용을 함께 서술하고, 기본값을 바꾸면 실험 조건으로 기록한다.

## 3. 재검토 문구의 방향

text 프롬프트에서 재검토나 변경을 요구하는 문구는 다음과 같다.

| 위치 | 원문 |
|---|---|
| worker 요건 (p.32) | "Re-check your work before committing: a subtle slip early on invalidates everything downstream." |
| worker의 이전 시도 블록 (p.32) | "They are NOT necessarily correct [...] Read them critically: use what is sound, identify what is flawed, and improve on them rather than copying them." |
| Assess (p.22) | "If you have ANY doubt, output CONTINUE." |
| Evaluate (p.26) | "including when in doubt" |

보존 쪽 문구도 일부 있다. worker는 "use what is sound"라는 지시를 받는다. ProgramBench에서는 Assess가 여전히 참인 항목을 carry forward하고, Evaluate는 이미 통과하는 코드의 refactor를 LOW_VALUE로 둔다 (p.23, 26). 반면 text 프롬프트에는 다음과 같은 명시 문구가 없다.

- 구체적 오류를 찾지 못하면 기존 답을 유지하라.
- 검증 작업에서 같은 답을 재현하는 것도 정당한 결과다.

worker의 "improve on them rather than copying them"은 검증·재계산 지시와 함께 놓일 때 해석이 갈릴 수 있다. steering이 "검증하라"고 해도 고정 문구는 개선을 요구하기 때문이다. 실제 worker가 이를 어떻게 따랐는지는 공개되지 않았다.

논문은 LongCoT-mini chess subset에서 MR이 DC보다 낮았다고 보고하며, 예비 표본 분석을 다음과 같이 적는다.

> unproductive reconsideration, in which additional checking or elaboration destabilizes an answer that was already correct. (p.15)

논문은 이 관찰을 프롬프트 문구와 연결하지 않았다. 이 문서도 연결할 근거를 갖고 있지 않다. worker 프롬프트는 MR과 DC에서 동일하므로(p.31) worker 문구만으로는 두 조건의 차이를 설명할 수 없다. controller 쪽 문구, 단계 구조 같은 다른 요인도 분리되지 않았다.

**분석자 예시 (논문 원문 아님, 효과 미검증):** 재검토 문구와 함께 보존 조건을 명시하는 방식이다.

```text
Change a prior answer only when you can point to a specific step that is wrong.
If your re-check finds no error, keep the answer and state what you checked.
For a verification task, reproducing the same answer is a valid outcome.
```

## 4. 공개 명세만으로 확인되지 않는 단계 간 참조

각 프롬프트가 참조하는 정보가 공개된 입력 명세에 있는지 대조했다. 공개되지 않은 구현(state 조립 코드, parser 등)이 이를 보완했을 수 있다. 아래는 결함을 확정한 것이 아니라 재현 시 확인할 항목이다.

| # | 참조하는 쪽 | 참조 대상 | 공개된 입력 명세 | 재현 시 확인할 점 |
|---|---|---|---|---|
| 1 | text Dispatch: "include its action's instruction" (p.28) | Propose의 action 본문 | task, index, Evaluate 출력 (p.27–28). Evaluate의 `<action>`은 gain·cost·rating을 쓰라고 지시한다 | Evaluate 출력이 action 내용을 다시 서술하지 않으면 Dispatch가 지시 내용을 얻을 곳이 명시되어 있지 않다 |
| 2 | Evaluate STOP (a): "rated LIKELY_CORRECT by assess AND has no unresolved outstanding_questions" (p.26) | Assess의 verdict, outstanding_questions, stop hint | `{state}`. Assess 프롬프트는 overall_assessment를 compressed state라고 부른다 (p.21, 25) | state에 어떤 블록이 들어가는지 확인한다. overall_assessment만이라면 STOP 조건의 근거가 입력에 없다 |
| 3 | Assess verdict: "For each NEW candidate" (p.21) | 과거 후보에 대한 갱신된 판단 | 다음 턴 Assess는 이전 state와 새 후보를 받는다 | 후보별 verdict는 새 후보에만 요청된다. 이후 판단 변화는 overall_assessment 서술에만 반영될 수 있다 (§6) |
| 4 | Dispatch GOOD 예시: "from worker 1_0", "2_0's report" (p.29) | pool ID | worker 기본 렌더링에는 ID가 없다 (p.33) | worker가 ID와 블록을 대응시킬 표지가 없다. 다만 GOOD 예시는 파일명(main.go)과 구체 동작도 적어 내용으로 특정할 수 있다 |
| 5 | run_workers schema: memory_blocks "Mandatory after the first round" (p.34) | — | Evaluate는 `memory: []`를 허용하고, Dispatch fallback은 "no memory_blocks"다 (p.26, 28) | 빈 목록이 허용되는지 확인한다 |
| 6 | 공통 run_workers 설명: "Each prompt tells one sub-agent what approach to try" + `['Try a DP approach', ...]` (p.34) | — | ProgramBench Dispatch는 action ID만 넘기는 것을 BAD 예시로 든다 (p.29) | PDF는 benchmark별 schema 차이를 밝히지 않는다. ProgramBench에서 쓴 schema 설명을 확인한다 |
| 7 | Evaluate: "costs 4 LLM calls" (p.25) | deliberation overhead | 본문은 단계마다 여러 번 호출될 수 있다고 설명한다 (p.5) | 프롬프트의 비용 서술과 실제 호출 수가 다를 수 있다 |
| 8 | text `finish`: 본문을 그대로 제출 (p.28) | 채점 대상 | worker 형식은 title과 confidence 줄을 본문에 넣는다 (p.32) | 원문은 grader가 본문에서 답을 추출한다고 적는다. 문제가 되는지는 grader 구현에 달렸다 |
| 9 | ProgramBench STOP `memory_id` (p.27) | 제출 대상 | `finish`는 workspace 상태를 제출한다 (p.28) | 필수 인자이지만 제출 내용에는 영향이 없는 것으로 보인다 |

1번과 관련된 ProgramBench Dispatch 문구는 다음과 같다.

> Do NOT pass the action_id alone [...] Action IDs are deliberation shorthand; workers receiving them have no idea what to do and will guess. This is the single biggest failure mode of the dispatch step. (p.29)

ProgramBench 버전에서는 proposals를 입력으로 받는 Evaluate가 `subagent_prompt`를 쓴다. Dispatch는 이를 "paraphrase or compress"하지 말라고 지시받는다 (p.29). 이 필드가 없는 경우를 "older format or omitted"라고 부르므로, 필드 없는 형식이 이전에 있었던 것으로 보인다. 하지만 ProgramBench 문구가 지목한 실패(action ID만 전달)가 1번 항목과 같은 원인인지는 원문에서 알 수 없다. text 버전 Evaluate 출력 형식에 `subagent_prompt`가 없는 이유도 원문에 없다.

**재사용 시 점검 항목 (분석자 제안):**

- 각 프롬프트가 언급하는 필드, label, ID가 실제 입력 조립에 있는가.
- 수신자가 해석할 수 없는 참조(보이지 않는 ID, 보지 못한 대화)가 전달 텍스트에 있는가.
- tool schema의 설명·예시가 system prompt의 규칙과 충돌하는가.

## 5. text 버전과 ProgramBench 버전의 차이

| 항목 | text | ProgramBench |
|---|---|---|
| Assess 출력 | 후보별 verdict + 서술형 state | 다섯 섹션 상태 원장. 항목마다 memory ID 또는 commit citation (p.22–23) |
| 판단 근거 | 후보의 reasoning | commit, test, diff. worker 서술은 사실로 치지 않는다 |
| STOP 근거 | "stake the run"이라는 확신 표현 (p.22, 26) | 원장 섹션이 비었는가 + 별도 검증 + 모든 action이 LOW_VALUE (p.27) |
| 검증 주체 | 따로 요구하지 않는다 | "a worker dispatch separate from the one that wrote the code ran the relevant test" (p.27) |
| 병렬 실행 | 같은 action을 N번 실행해 성공 가능성을 높인다 (p.25) | coding은 1, read-only는 fan-out 허용 (p.26) |
| steering 작성자 | Dispatch | Evaluate가 `subagent_prompt` 작성, Dispatch는 그대로 전달 (p.27, 29) |
| 가치 기준 | 정답과 형식 | 통과하는 test 수. 코드 품질은 낮게 평가 (p.26) |
| 사고 대비 | — | `executable_orig` 보호와 `recover_executable` (p.36), 언어 전환 경고 (p.35) |

ProgramBench 버전은 판단 근거를 commit·test·diff 같은 관찰 가능한 증거로 제한한다. Assess에는 "No verdicts. No scoring. No stop signal."이라고 적어 판단을 Evaluate에 넘긴다 (p.23). STOP 조건은 원장 섹션의 상태로 정의되므로 원장과 대조해 사후 점검할 수 있는 형식이다. text 버전의 worker는 도구 없는 단일 호출이고 (p.8), STOP 조건은 확신 표현으로 정의된다.

**분석자 제안 (효과 미검증):** text 과제에도 두 요소를 옮겨 볼 수 있다.

- 작성자와 검증자 분리: 별도 worker가 독립적으로 재계산한 후보만 STOP 대상으로 삼는다.
- 후보별 원장: 확인된 단계, 미확인 단계, 반례 검사 여부를 citation과 함께 기록한다.

ProgramBench 문구 일부는 구체적 사고를 언급한다. 예를 들면 "frequently destroy `./executable` or `./executable_orig`"(p.26), "single biggest failure mode"(p.29), 언어 전환 경고(p.35)가 있다. 이 문구들이 어떤 관찰에서 나왔는지는 원문에 설명이 없다.

## 6. 프롬프트가 만드는 측정 신호

논문의 monitoring 분석은 프롬프트가 만든 두 신호를 쓴다 (p.7, 12).

| 신호 | 생성 위치 | 문면상 특성 | 해석 시 고려할 점 |
|---|---|---|---|
| worker confidence | worker prompt (p.32) | HIGH/MEDIUM/LOW. 용도를 알려준다: "consumed by the orchestrator to decide whether to refine, verify, or submit [...] marking HIGH on work you have not verified wastes downstream compute" | 용도 설명이 응답에 영향을 줄 수 있지만 측정되지 않았다. 3단계 척도라 동률이 생길 수 있고, AUC는 동률에 절반 점수를 준다 (p.7) |
| Assess verdict | Assess prompt (p.21–22) | LIKELY_CORRECT/HAS_GAPS/FUNDAMENTALLY_FLAWED. label 정의에 후속 행동이 들어 있다: "downstream stages should consider stopping and submitting" | label 정의가 행동 권고를 함께 언급하므로 정답 판단만으로 해석할 때 주의가 필요하다. 새 후보에 대해서만 요청된다 |

논문은 여러 설정에서 controller verdict가 worker confidence보다 정답을 더 잘 구분했다고 보고한다. 예를 들어 Gemini 3.1 Pro IMO ProofBench에서는 0.88 대 0.55였다. 차이는 GPT-5.5와 Opus 4.8에서 더 작았고, GPT-5.5 LongCoT-mini에서는 거의 없었다 (p.12).

두 신호는 입력 정보가 다르다. Assess는 새 후보 전문과 이전 state를 보고 다른 후보를 읽을 수 있다. worker는 자기 작업과 받은 context만 본다. 논문은 이를 controller 수준 평가와 worker 자기 평가의 비교로 제시하며, 같은 입력에서 판단 능력을 비교했다고 주장하지 않는다.

**측정 설계 시 고려 (분석자 제안):**

- 분석에 쓸 label은 정답 판단과 행동 권고를 분리한다.
- 판단 갱신을 허용하고 시점을 기록한다.
- 필요하면 더 세밀한 척도를 쓴다.
- 한 신호에만 용도 설명 같은 문구를 넣었다면 비교할 때 그 차이를 함께 기록한다.

## 7. Direct Control과의 프롬프트 내용 차이

DC 프롬프트(C.1–C.2)와 MR 프롬프트를 지침 단위로 대조했다.

| 지침 | Meta-Reasoning | Direct Control |
|---|---|---|
| 종료 조건과 기본값 | ALL 조건, 의심하면 CONTINUE (p.22, 26–27) | "call `finish` with the candidate you trust most" (p.30). 기본값 없음 |
| 예산 관련 문구 | "add more than nothing" (p.27), "refinement is generally safer" (p.26) | 10%마다 `BUDGET`, 90%에 `FINISH NOW` (p.31) |
| worker 과신 경고 | 있음 (p.22, 26) | 없음 |
| 합의·부분 증거·형식 함정 | Assess 점검 항목 | "Common pitfalls" 세 줄 (p.30) |
| steering 작성 안내 | ProgramBench: self-contained, BAD/GOOD 예시, 200–500자 (p.27, 29) | tool 설명의 예시는 짧은 명령구다: "implement the CLI parser" (p.30) |
| 병렬 worker 다양성 | tie-break (c)가 다양성. 같은 지시를 N번 또는 약간 변형 (p.25, 28) | "If you give all workers the same prompt they will produce similar outputs; give different prompts to explore different angles." (p.29) |
| ProgramBench 병렬 안전 | coding은 1, read-only는 fan-out 허용 (p.26) | "prefer 1 worker at a time unless they work on independent modules/branches" (p.30) |
| 채점 기준에 맞춘 가치 | test 수, 코드 품질은 낮게 평가 (p.26) | "ALL functionality must be reproduced" (p.30) |
| 증거 기준 | citation-only 원장 + git 안내 | git 안내 (p.36–37) |

정리하면 다음과 같다.

- 두 조건은 구조(단계, state, memory)뿐 아니라 의사결정 휴리스틱 문구도 다르다. 따라서 §2의 사용률 차이나 점수 차이를 구조 차이로만 귀속할 수도, 문구 차이로 귀속할 수도 없다.
- 지침이 한쪽에만 있는 것은 아니다. 병렬 worker 다양성 안내는 DC 쪽이 더 명시적이다.
- 논문은 설계 전체의 효과만 주장한다고 밝힌다 (p.20). Appendix A가 열거한 state, stage, memory 접근에 의사결정 문구는 명시되어 있지 않다. 결과를 단계 구조의 효과로만 읽지 않도록 주의가 필요하다.
- 두 조건의 실제 steering 길이와 구체성은 보고되지 않았다.

**분석자 제안:** 구조 효과와 문구 효과를 분리하려면 두 조건 중 하나가 필요하다. 하나는 DC에 MR의 종료·예산·steering 문구를 추가한 조건이다. 다른 하나는 MR에서 해당 문구를 제거한 조건이다.

## 8. Appendix H·G: 제약을 프롬프트와 runtime에 나눠 둔 사례

RLM 비교를 위해 저자들은 REPL에서 직접 계산하지 못하게 해야 했다. 그 과정은 다음과 같다 (p.37–38).

1. **첫 시도:** 모든 code block이 sub-model을 호출하도록 요구하고 위반 block을 거부했다. 결과는 다음과 같았다.
   > dummy sub-calls which satisfied the requirement while the model still solved the task inline. (p.37)

   요구의 형식은 충족했지만 의도는 충족하지 않은 사례다.
2. **두 번째 시도:** AST allowlist로 계산 능력 자체를 제거했다. 거부 메시지는 대신 쓸 함수를 알려준다.
3. **프롬프트의 역할:** 제약을 미리 기술했다. 저자들이 밝힌 목적은 "so the model knows the limits before it starts rather than discovering them by hitting the validator"이다 (p.37).
4. **덧붙이는 프롬프트의 우선순위:** heading에 "## RESTRICTED WORKSPACE (this OVERRIDES the REPL description above)"라고 적어, 기존 프롬프트를 고치지 않고 덧붙일 때의 충돌 해소 방식을 명시했다.
5. **허용·금지 목록:** YOU CAN과 YOU CANNOT을 실제 코드 예와 함께 적고, "the grammar makes that impossible, so don't try"라고 덧붙였다.
6. **남은 문제:** 그래도 Opus 4.8은 LongCoT-mini에서 workspace 안에서 계산을 계속 시도했다. 저자들은 그 셀만 full-Python 결과로 보고했다 (p.38).

ProgramBench task prompt(G.1)도 비슷하게 구성되어 있다. 금지 범주와 구체 사례를 나열하고, 허용 행동을 따로 적고, 위반 결과("automated judge [...] disqualification")를 밝힌다. 사고 시 복구 경로(`recover_executable`)도 준다 (p.35–36).

이 사례에서 규칙과 거부만으로는 의도한 행동이 나오지 않았다. 능력을 제거한 뒤에도 한 모델은 계속 계산을 시도했다. 하나의 사례이므로 일반화에는 한계가 있다.

**재사용 시 고려:** 반드시 지켜야 할 제약은 runtime에서 강제하고, 프롬프트로는 그 제약과 허용 대안을 미리 알리는 방식을 고려할 수 있다.

## 9. min_pilot에 대한 시사점 (제안)

아래는 논문 사실이 아니라 현재 프롬프트(실행 v10, refiner r12)와 대조한 분석자의 제안이다. 이 문서 작성 과정에서 코드와 프롬프트는 변경하지 않았다.

1. **정적 지침과 refiner의 관계.** ProgramBench Dispatch 프롬프트는 action ID만 넘기는 것을 dispatch 단계의 가장 큰 실패 양상이라고 적는다. 그 버전에는 self-contained 지침, BAD/GOOD 예시, proposals를 보는 Evaluate가 지시를 작성하는 구성이 있다. min_pilot orchestrator에도 위임 지시를 자기완결적으로 쓰라는 정적 지침이 있다. "It does not see earlier reports or instructions, so each delegation must be understandable on its own"과 instruction·context 필드 설명이 그것이다 (`src/minpilot/prompts/orchestrator.py`). BAD/GOOD 예시는 없다. 따라서 refiner 효과는 이 정적 지침이 있는 baseline 대비로 측정된다. 정적 지침만 강화한 조건을 비교 대상으로 둘지는 별도 결정이며, 둔다면 [decisions.md](decisions.md)에 기록할 대상이다.
2. **변경하지 않는 결과와 지지된 답에 대한 문구.** r12 analysis에는 "leaving an adequate instruction unchanged is a valid outcome"과 "Do not require extra proof that would exclude an answer supported by the original task's criteria"가 있다. rewrite에는 "Allow a supported inference [...]"와 "Do not tell the worker to withhold a supported answer because an extra check you introduced is unavailable"가 있다 (`src/minpilot/prompts/refiner.py`). 논문 text 프롬프트에는 이에 해당하는 명시 문구가 없다. 이 차이가 결과에 주는 영향은 이 문서에서 판단하지 않는다.
3. **종료 정책의 방향.** min_pilot orchestrator는 "Finish when the available evidence supports the requested answer"와 "Do not repeat completed work merely to obtain another opinion"으로 증거 충분성을 기준으로 한다. 논문 MR의 "의심되면 계속" 기본값과 방향이 다르다. 지속 기본값을 도입한다면 refiner와 별개의 개입이므로 별도 조건으로 다뤄야 한다. 논문 결과는 이 기본값 자체의 효과를 분리하지 않았다.
4. **단계 간 참조.** min_pilot에서는 analysis와 rewrite가 같은 비공개 대화 사본을 이어 쓴다 (`src/minpilot/refine/review.py`의 `self.conv`). 그래서 rewrite가 언급하는 "accepted issues"가 같은 대화 안에 있다. 단계를 fresh context로 분리하거나 요약만 넘기도록 바꾼다면 §4의 점검 항목을 적용한다.
5. **측정 신호.** confidence나 verdict 필드를 추가한다면 정답 판단과 행동 결정을 분리하고, 갱신 시점을 기록한다(§6).
6. **비교 조건의 문구.** 개입 arm에만 일반 휴리스틱 문구를 넣지 않는다. CLAUDE.md의 "Hold executor, common pipeline [...] fixed"를 프롬프트 내용에도 적용한 것이다. §7에서 보듯 조건 간 문구 차이는 구조 차이와 분리하기 어렵다.

## 10. 이 분석의 한계

- 공개된 프롬프트 문면만 분석했다. 실제 trace를 보지 않았으므로 모델이 각 문구를 어떻게 따랐는지 알 수 없다.
- 논문에 문구 단위 ablation이 없다. 이 문서는 문구와 결과 사이의 인과를 주장하지 않는다.
- text 세 benchmark 사이의 문구 차이는 공개되지 않았고, 공개된 것은 한 변형이다. worker 첫 문장("Individual steps may be tractable; the difficulty is staying correct across the whole chain")은 LongCoT 설명(p.8)과 거의 같으므로 LongCoT 변형일 가능성이 있다.
- 프롬프트의 개발 이력은 원문에 없다. "older format" 같은 표현에서 짐작할 수 있는 범위는 제한적이다.
- state 조립 코드와 parser는 공개되지 않았다. §4의 항목 일부는 구현에서 보완되었을 수 있다.
