### **동기**

[실패 유형 분석](2026-10-15-gaia-nonweb-failure-modes.ko.md)에서 v21 오답의 대부분은 evaluator 판단이 최종 답을 정했다.
그래서 C42(v22/r24)로 다음을 바꿨다.

- evaluator를 runtime에서 뺐다.
- subtask를 만든 orchestrator가 run 동안 대화 하나를 유지한다. orchestrator는 보고 원문을 직접 읽고 `probe`·`execute`·`finish` tool call로 행동한다.
- 답은 항상 값 하나로 낸다.

이 문서는 v21에서 어느 조건이든 틀렸던 11문제를 v22로 다시 돌린 결과다. 사용자 요청에 따른 표적 재실행이며, 36문제 비교를 대신하지 않는다.

### **설정**

- 문제: v21 재실행(`2026-10-15_gaia-nonweb-conversation-comparison-rerun`)에서 보정 채점으로 `direct` 또는 `adaptive`가 틀린 11문제.
  - 0bb3b44a, 305ac316, 3cef3a44, 5a0c1adf, 65afbc8a, 9318445f, cca530fc, cf106601, cffe0e32, e142056d, ec09fa32
- 조건·pool·한도·runner는 v21과 같다.
  - worker `gen_luna`, `gen_haiku`, 도구 `read_file`·`view_image`·`run_python`
  - run당 $0.20, execute 12회, 반복 1회
- 실행 묶음
  - `2026-10-15_gaia-nonweb-v22-failed-rerun`: 7 run 완료.
    - haiku 요청 두 개가 upstream rate limit(HTTP 429)을 받았다. client는 재시도에 성공했지만 이를 과금 불명 호출로 셌다.
    - 그래서 runner의 안전 규칙이 나머지 접수를 멈췄다. OpenRouter는 429를 과금하지 않는다.
  - `2026-10-15_gaia-nonweb-v22-failed-rerun-cont`: 건너뛴 15 run을 같은 코드와 같은 순서로 실행했다.
  - 22 run 모두 `ok`로 끝났다.
- 사전 smoke check(`2026-10-15_gaia-nonweb-v22-smoke`): cffe0e32 × 2조건, 둘 다 정답, $0.026. 합산에 넣지 않는다.
- 채점
  - 공식 채점: GAIA scorer.
  - 보정 채점: 2026-10-13·10-15 보고서와 같은 규칙. 판정 파일은 첫 묶음의 `analysis/adjudicated_scores.csv`다.

### **관측**

**1. 같은 11문제에서 정답 수가 늘었다. 다만 표본이 작고 오답으로 고른 문제다**

| 실행 | `direct` 공식 | `direct` 보정 | `adaptive` 공식 | `adaptive` 보정 | `direct` 비용 | `adaptive` 비용 | `adaptive` probe / execute |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v19 r0 | 1 | – | 1 | – | | | |
| v19 rep1 | 1 | 2 | 0 | 2 | | | |
| v21 | 1 | 1 | 0 | 0 | $0.271 | $0.383 | 22 / 19 |
| **v22** | **2** | **2** | **4** | **5** | $0.242 | $0.229 | 11 / 22 |

- 새로 맞힌 문제
  - `adaptive`: 9318445f, cf106601(이전 실행들에서 한 번도 못 맞힘), 3cef3a44(v19 r0에서 한 번), 65afbc8a(v19 rep1 보정에서 한 번), cffe0e32(단서 붙은 정답).
  - `direct`: 0bb3b44a(처음).
- 문제를 v21 오답으로 골랐다. 그래서 다시 돌리기만 해도 일부는 맞을 수 있다(평균 회귀).
  - 같은 11문제에서 이전 네 실행의 조건별 정답은 0–2개였다. `adaptive` 4–5개는 그 범위를 넘는다.
  - 하지만 문제 11개에 반복 1회라 효과 크기를 말할 수 없다.
- `adaptive` 비용은 v21보다 40% 낮다. probe 라운드가 문제당 1회로 줄었다(v21은 2회).

**2. 맞힌 경로: orchestrator가 해석을 직접 고르고 끝까지 밀었다**

- 65afbc8a `adaptive`
  - haiku가 "한 턴은 한 칸씩 두 번, 그 사이에 방향 전환 가능"이라는 해석으로 11턴 경로를 찾았다.
  - orchestrator는 luna에게 그 경로를 독립 확인하게 한 뒤 F478A7로 끝냈다.
  - v21에서는 같은 문제에서 evaluator가 "해석을 확정하지 말라"고 썼고, 답은 "경로 없음"이었다.
- 3cef3a44 `adaptive`
  - orchestrator가 basil 판정을 쟁점으로 짚었다. 두 worker 모두 "질문에는 과일·채소 두 heading만 있고 basil은 잎이므로 채소"라고 답했다.
  - v21의 오답 원인(orchestrator가 지시문에 "허브 제외"를 넣음)은 두 조건 모두 재현되지 않았다.
- 9318445f `adaptive`
  - v21에서는 evaluator가 "그림 label까지 넣으라"고 범위를 넓혔다. 이번에는 범위를 넓히는 단계가 없었다.
  - 실행 worker가 케이크 그림의 label과 가로선 분수를 스스로 제외했고, 결과가 정답과 일치한다.
  - `direct`는 worker가 label을 넣은 쪽을 "illustration labels included"로 내세웠고, orchestrator가 그 판독을 골라 틀렸다.
- cf106601 `adaptive`
  - 출처 접근이 막혔다고 보고되자 orchestrator가 "기억 기반 추정"이라는 다른 방법을 지시했다.
  - Cuba·Panama가 1명으로 동률이고, 알파벳순 규칙에 따라 CUB를 골랐다.
- 0bb3b44a `direct`: 두 worker가 8·60+56으로 읽었고, orchestrator가 536으로 끝냈다.

**3. 새로 보인 실패: 값 하나 규칙이 틀린 해석을 확정하기도 한다**

- ec09fa32(두 조건): 두 조건의 worker 모두 ball 3과 ball 100을 계산했다. orchestrator는 "자연스러운 해석"이라며 100을 골랐다(정답 3). v21 `direct`의 evaluator가 한 판단과 같다.
- cca530fc(두 조건): 두 조건 모두 Qxc3를 냈다.
  - v21 haiku는 이 수가 2.Bh7+로 반박된다는 것을 보였다(정답 Rd5).
  - 이번 run의 worker들은 그 수순을 찾지 못했고, orchestrator는 "결정적인 material 이득"을 근거로 확정했다.
- 0bb3b44a `adaptive`
  - orchestrator의 첫 실행 지시가 "GESH2 이름의 부호를 자리값 숫자로 가정하지 말라"였다. worker는 덧셈 판독(890)으로 갔다.
  - 지시를 쓴 orchestrator 자신이 해석을 한쪽으로 몰았다. evaluator가 없으니 이 지시를 원 질문과 대조할 단계도 없다.
- 3cef3a44 `direct`
  - worker 보고는 정답 순서였다(`broccoli, celery, fresh basil, lettuce, sweet potatoes`).
  - orchestrator가 `finish`에 옮기면서 "fresh basil"을 맨 앞에 두었다. 질문이 요구한 알파벳 순서가 깨져 오답이다.
- 값 하나 규칙 위반: 22 run 중 3개.
  - 5a0c1adf `adaptive` `Unable to determine`
  - 65afbc8a `direct` `No valid 11th landing`
  - cffe0e32 `adaptive` `Fred (assuming …; otherwise Micah)`. 보정 채점에서는 정답이다.
- 외부 지식이 필요한 3문제는 여전히 맞힐 수 없다. 이번에는 대부분 기억 기반 추정을 값으로 냈다. 맞은 것은 cf106601 `adaptive` 하나다.
  - 305ac316 `adaptive`의 `Wojtek`은 정답 Wojciech의 애칭이지만 오답으로 판정했다.

**4. orchestrator의 해석이 맞다는 전제: e142056d**

v21과 v22에서 같은 신호가 나왔는데, 판단하는 쪽이 바뀌어도 두 번 다 무시됐다.

- 원 질문의 조건: "one box must contain at least 2 coins".
- v21: haiku probe가 이 조건이 "never binds"라고 보고했다. evaluator는 "다른 해석 검토는 불필요하다"고 썼다.
- v22 `adaptive`
  - orchestrator가 probe 지시에 "at least one box has at least 2 coins"로 해석을 직접 적었다.
  - haiku probe가 동전 30개를 세 상자에 나누는 66가지 배치를 모두 세어 보고, 이 조건이 항상 만족되므로 결과에 영향이 없다("looks redundant")고 보고했다.
  - orchestrator는 실행 지시에 같은 해석을 다시 적었고 12000으로 끝냈다.
  - 정답 16000은 "모든 상자에 2개 이상"으로 읽어야 나온다.
- v22 `direct`도 orchestrator가 첫 지시에 같은 해석을 적었고 12000으로 끝냈다.

이것은 prompt 문구보다 구조의 전제에서 나온다. 지금 구조에서는 원 질문의 해석을 orchestrator가 정하고, 그 해석을 맞다고 전제한다.

- orchestrator prompt는 probe 응답에서 worker의 이해를 "orchestrator가 뜻한 바"와 비교하게 하고, 다르면 지시를 고쳐 worker를 그쪽으로 맞추게 한다. 비교의 방향이 한쪽뿐이다.
- worker는 orchestrator가 만든 assignment만 받는다. 원 질문 자체의 해석을 함께 분석하는 단계가 없다.
- worker가 해석이 틀렸다는 근거를 보고해도, 그 근거로 orchestrator의 해석을 바꾸는 경로가 없다.

같은 구조로 설명되는 사례가 더 있다.
- 0bb3b44a `adaptive`: orchestrator가 원 질문이 지정한 60진법과 다른 덧셈식 해석을 실행 지시에 넣었고, 그 해석으로 끝냈다.
- ec09fa32 `adaptive`: orchestrator가 두 종료 규칙을 비교하게 한 뒤 "natural continuation"에 집중하라고 지시했고, 그 해석의 답(100)으로 끝냈다.

**5. 상호작용 지표**

- orchestrator 메시지 85개
  - 한 메시지에 tool call 2개: 6개. 대부분 두 worker에게 같은 실행을 동시에 보내려는 시도였다. 첫 call만 실행됐고, 다음 메시지에서 나머지를 다시 호출했다.
  - 잘못된 인자 오류: 0개.
  - tool call과 함께 쓴 text: 0개. probe·execute의 선택 이유는 기록되지 않는다. finish만 `rationale`이 있다.
- probe 지시 11개 중 7개가 "any ambiguity를 설명하라" 류의 문구를 포함했다. v21은 47개 중 11개였다.
  - "실행용처럼 쓰라"는 문장이 실행 지시의 관행(모호함 보고 요청)을 함께 끌어온 것으로 보인다.
- 실행 지시 하나(65afbc8a `adaptive`)가 문장 중간에서 끊긴 채 전달됐다. worker는 이를 알아채고 진행했다.
- 비정상 보고 2개
  - cca530fc `direct`: worker의 빈 보고 1개, 도구 한도 1개.

**Takeaway:** evaluator를 빼고 orchestrator가 직접 해석을 정하자, 이전에 "확정하지 말라"로 막히던 답(65afbc8a, 3cef3a44)이 나왔다. 그 대신 orchestrator가 그럴듯하지만 틀린 해석이나 수를 확정하는 경우(ec09fa32, cca530fc)와 자기 지시로 해석을 모는 경우(0bb3b44a `adaptive`)가 새로 보였다.

### **결론**

v21 오답 11문제에서 v22는 `adaptive` 0 → 4(공식)·5(보정), `direct` 1 → 2를 맞혔다. `adaptive` 비용은 40% 줄었다.
오답으로 고른 11문제에 반복 1회라 개선 폭은 추정할 수 없다. 36문제 전체를 고정된 반복 횟수로 다시 돌려야 비교가 된다.
새로 생긴 실패는 확정의 반대편에 있다. 틀린 해석을 그럴듯하다는 이유로 확정한다.
그 바탕에는 orchestrator의 원 질문 해석이 맞다는 구조 전제가 있다(관측 4). worker가 해석이 틀렸다는 근거를 보고해도 그 근거가 해석을 바꾸지 못한다. prompt에 자기 점검 문장을 더하는 것보다, worker와 함께 원 질문을 분석하는 단계를 둘지 같은 설계 결정에 가깝다.

다음에 확인할 것:

- 원 질문 해석의 구조 전제(관측 4): orchestrator 혼자 정할지, worker와 함께 분석하는 단계를 둘지. 사용자 결정이 필요하다.
- 36문제 전체 v22 재실행: 이번에 맞던 25문제에서 손실이 있는지 확인한다.
- probe 지시의 모호함 질문(7/11): "실행용처럼 쓰라"는 문장의 부작용 여부.
- `finish`의 답 옮겨 쓰기 오류(3cef3a44 `direct`)와 값 하나 규칙 위반(3/22).
- probe·execute의 선택 이유가 기록되지 않음: 분석을 위해 짧은 text를 요구할지.

자료
- 실행 묶음: `outputs/experiments/2026-10-15_gaia-nonweb-v22-failed-rerun/`, `…-cont/`
- 보정 채점: 첫 묶음 `analysis/adjudicated_scores.csv`(22 run)
- 각 run: `runs/<task_id>/<run>/run.json`, `orchestrator.jsonl`(orchestrator 대화 전문), `artifacts/`, `llm_calls.jsonl`
