# MoNaCo instruction 합의 선택: 2문제 end-to-end 점검

### 목적

20문제 본 실행 전에 `monaco-instruction-selection-v1`의 전 단계(후보 작성 → probe → 선택 → 실행 → judge →
분석)를 실제 모델로 한 번 돌려 실행 경로와 문제점을 확인한다. **성능 비교가 아니다.** 일부러 쉬운 문제를 골랐다.

### 설정

- 문제: pool 540개 중 seed 20문제와 겹치지 않는 2개. 고를 때 gold와 문서는 출력하지 않고 질문만 봤다.
  - `monaco_805` "How many of the first ten winners of The Voice were female?" (단일 답, gold `[4]`)
  - `monaco_1250` "Which three EU countries have the highest number of Iranians living outside of Iran?"
    (목록 답, gold `['Germany', 'France', 'Sweden']`)
- 후보: 이 세션이 질문만 보고 직접 작성·자기 검토(session 모드, 추가 API 비용 0). 원문은
  `outputs/analysis/2026-10-14_monaco-e2e-candidates/candidates.reviewed.jsonl`.
- 모든 단계 sync. 실험 디렉터리 `outputs/experiments/2026-10-14_monaco-instruction-selection-e2e`.

### 결과

| 단계 | 호출 | 상태 | 기록 비용 |
|---|---:|---|---:|
| judge 검증 | 2 | 2/2 공개 GPT-4.1 점수와 일치 | $0.00014 |
| probe | 72 | ok 69, HTTP 429 실패 2, 답 형식 실패 1 | $0.2466 |
| 실행 | 24 | ok 24 | $0.0222 |
| judge | 24 | ok 24 | $0.0026 |

합계 기록 비용 약 $0.27. 비용 불명 16건은 모두 haiku의 HTTP 429 재시도이며 상한 계산에는 예약액 $0.27을
보수적으로 남겼다(429는 청구되지 않았을 가능성이 높지만 확인하지 않았다).

정책별 평균 점수(2문제, 실행 3회 평균): selected 1.00, naive 1.00, analogical 1.00, clarify 0.958,
local_check 0.958, random 0.979, best_in_hindsight 1.00. 두 문제 모두 naive가 이미 만점이라 headroom은 0이다.

### 확인한 문제

1. **일시적 오류가 선택을 바꿨다.** `monaco_805`에서 naive의 haiku probe 2개가 HTTP 429로 실패해 naive 합의가
   7/9가 됐고, 9/9인 analogical·clarify 중 analogical이 뽑혔다. 다른 7개 답은 모두 정답 4였다.
   현재 규칙은 client 재시도 후 실패한 slot을 기록된 실패로 두고 다시 하지 않는다.
   haiku 호출 48개(probe 24, 실행 24)에서 429가 16번 났다(재시도 포함). 실행 단계는 재시도로 모두 성공했다.
2. **답 형식이 합의를 깎는다.** 의미는 같은데 형식 때문에 다른 답으로 묶인 경우가 있다.
   - haiku가 목록을 한 겹 더 쌌다: `[["Germany", "Sweden", "France"]]`. 정규화에서 국가 3개짜리 한 행이 된다.
   - luna(clarify)가 수치를 붙였다: `[["Germany", 266000], ...]`. 형식 지시상 허용되지만 다른 답이 된다.
   - haiku(local_check)가 `ANSWER: 4`로 목록 없이 답해 답 없음 처리됐다.
   `monaco_1250`의 analogical·clarify가 8/9가 된 것은 모두 이 형식 차이 때문이다.
3. **instruction이 답을 해쳤다.** `monaco_805`의 local_check는 "이름으로 추정하지 말고 문서 근거로 확인하라"를
   담고 있다. 이 때문에 luna probe 2개가 "문서만으로는 판단 불가"로 답을 보류했고, haiku 실행 1회는 문서에
   성별 표현이 있는 3명만 세서 3이라고 답했다(Alisan Porter는 문서에 대명사가 없어 제외). clarify의
   "여성임을 무엇으로 확인하는지 밝혀라"도 haiku 실행 1회에서 같은 이유로 3을 냈다. 두 응답 모두 "외부 지식을
   쓰면 4"라고 덧붙였다. 공통 prompt의 "Use the documents below"와 근거 요구가 겹쳐 범위가 좁아진 것으로 보인다.
   GAIA에서 본 조건 강화·답 보류와 같은 유형이다. 이 문구는 이 세션이 작성한 후보이므로 작성 품질의 문제이기도 하다.
4. **채점이 숫자 셈에 부분 점수를 준다.** 셈 문제에서 3을 답하면 `1 − |4−3|/4 = 0.75`점이다. 공개 채점과
   같은 규칙이지만, 셈 문제의 오답이 0점이 아니라는 점은 결과를 읽을 때 고려해야 한다. judge 응답 하나는
   `precision: 0` 뒤에 `final precision: 0.75`를 썼고, 규칙대로 final precision을 썼다.
5. **쉬운 문제는 선택 실험에 정보가 없다.** 두 문제 모두 4개 후보가 9/9 또는 그에 가까워 동점이었고
   (최고 동점 후보 2개씩), 선택은 seed 무작위로 정해졌다.

### 데이터 쪽에서 확인한 사항

- pool 540개 중 2개(853, 1714)는 oracle 문서가 비어 있다(전체 oracle 1,287개 중 8개). seed 20문제에는 없다.
- 공개 채점 결함 두 가지(셈 gold 0/1의 Yes/No 표기 12문제, `###` 앞 빈 항목을 정답으로 셈)는 따르지 않는다.
  상세는 [운영 문서](../operations/monaco-instruction-selection.ko.md).

### 20문제 본 실행 전에 정할 것

이후 결정: 429는 sync 재시도(최대 3번, 동시 실행 4), 답 동치는 luna 묶기로 바꿨다(v2). 답 형식 지시와 정규화는 바꾸지 않았다. [결정 C40](../decisions.md),
[묶기 검증 보고서](2026-10-14-monaco-answer-clustering-validation.ko.md).

- 429 처리: 실패 slot을 pending으로 남겨 재실행 때 다시 하게 할지, haiku를 batch로 보낼지.
- 답 형식: 한 겹 더 싼 목록을 펴 줄지(값 하나짜리 행만 있는 목록을 같은 답으로), 맨숫자 `ANSWER: 4`를 `[4]`로
  받을지. 이 처리는 형식 차이만 흡수하고 의미가 다른 답은 그대로 둔다. 바꾸면 정규화 버전을 올린다.
- 문제 난이도: seed 20문제 그대로 갈지. 이번처럼 naive 만점 문제가 많으면 headroom을 볼 수 없다.
