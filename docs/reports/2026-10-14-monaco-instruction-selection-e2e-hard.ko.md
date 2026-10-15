# MoNaCo instruction 합의 선택: 중간 난이도 2문제 end-to-end 점검

### 목적

`monaco-instruction-selection-v3`(judge·답 묶기 `luna-low`, 429 재시도, 동시 실행 4)의 전 단계를 쉬운 문제보다
어려운 문제로 다시 돌려 문제점을 확인한다. **성능 비교가 아니다.**

### 설정

- 문제: pool 540개 중 seed 20문제, 묶기 검증 100문제, 이전 점검 문제(805, 1250, 486, 415)를 뺐다. 행에 값이 여러 개인
  gold는 제외했고 문서는 5천–4만 글자로 제한했다. 공개 GPT-4o·Llama-405B oracle 점수 평균이 0.4–0.8이고 최고가 0.6
  이상인 문제(단일 31개, 목록 19개) 중 seed 0으로 하나씩 골랐다. 고를 때 gold는 출력하지 않았다.
  - `monaco_1707` "Which Habsburg Emperor ruled over Austria for the shortest amount of time?"
    (단일 답, 공개 점수 GPT-4o 0, Llama 1)
  - `monaco_910` "Besides the Spanish Flu, what other diseases reached a pandemic like state in the 1900s?"
    (목록 답 6개, 공개 점수 GPT-4o 0.73, Llama 0.60)
- 후보: sonnet-high가 질문만 보고 생성(본 실행과 같은 경로). 모든 단계 sync, 동시 실행 4.
- 실험 디렉터리 `outputs/experiments/2026-10-14_monaco-instruction-selection-e2e-hard`.

### 결과

| 단계 | 호출 | 상태 | 기록 비용 |
|---|---:|---|---:|
| judge 검증 | 2 | 2/2 공개 GPT-4.1 점수와 일치 | $0.0003 |
| 후보 생성 | 2 | ok 2 | $0.0147 |
| probe | 72 | ok 71, 답 형식 실패 1, 오류 0 | $0.5302 |
| 묶기 | 2 | ok 2 | $0.0008 |
| 실행 | 24 | ok 24 | $0.0613 |
| judge | 24 | ok 24 | $0.0046 |

합계 약 $0.61. probe는 72회에 4분 14초가 걸렸고 HTTP 429는 없었다. 비용 불명 호출도 없다.

정책별 평균 점수(2문제, 실행 3회 평균): selected 0.309, naive 0.302, analogical 0.279, clarify 0.316,
local_check 0.309, random 0.302, best_in_hindsight 0.316.

### 확인한 문제

1. **여러 줄 JSON 답을 읽지 못한다.** flash-lite 응답 하나가 `ANSWER: [` 뒤에 목록을 여러 줄로 썼다. 지금
   파싱은 `ANSWER:` 줄 하나만 읽어 답 없음이 됐고, 묶기에는 `[`만 넘어가 `no_answer`로 처리됐다. 코드 결함이다.
2. **목록 답에서는 완전 일치 합의가 무너진다.** 910에서 서로 다른 답 문구가 36개 중 21개였다. 각 답은 같은
   질병을 다른 단위로 적었다(`Cholera` 대 `Sixth cholera pandemic`·`Seventh cholera pandemic`, `Influenza` 대
   H1N1·H2N2·H3N2 각각). 포함한 항목도 한두 개씩 달랐다. 그래서 네 후보 모두 2/9로 동점이었고 선택은 seed
   무작위였다. gold가 6개인 목록에서도 이렇게 됐으므로, seed 20문제의 큰 목록(19개, 30개)에서는 합의 신호가
   거의 없을 것으로 본다.
3. **luna-low가 다른 목록을 한 묶음에 넣었다.** 910의 한 묶음에 8개 목록 둘과, 그중 `Encephalitis lethargica`가
   빠진 7개 목록이 함께 들어갔다. 다른 묶음 3개를 확인했는데 거기서는 같은 답만 묶었다.
4. **"중간 난이도"로 고른 두 문제 모두 gold 쪽 문제가 섞여 있다.**
   - 910의 gold 6개에 질문이 제외한 `Spanish flu`가 들어 있다. 질문대로 답하면 recall이 최대 5/6이다.
     실행 점수는 0.53–0.67이었다.
   - 1707의 gold는 `Leopold II`인데, probe 9개 중 8개와 실행 12개가 모두 `Charles I`이라고 답해 0점을 받았다.
     실행 응답은 Charles I(1916–1918)이 Leopold II(1790–1792)보다 약 2–3주 짧다고 설명했다. 문서에는 두 사람의
     문서가 모두 있다. gold가 다른 해석을 따른 것인지는 확인하지 않았다.
   - 공개 점수로 난이도를 고르면 gold 결함 문제가 함께 걸린다는 뜻이다.
5. **1707은 합의가 높은데 gold 기준으로는 틀렸다.** naive·analogical·local_check가 9/9였다. 합의 선택은 이런
   문제에서 점수를 바꾸지 못한다.

### 잘 동작한 것

- 429 없이 끝났다. 동시 실행 4에서 72회에 약 4분이 걸렸다.
- luna-low judge는 judge 검증 2개에서 공개 점수와 같았다.
- 묶기는 `Charles I`과 `Charles I of Austria`를 같은 답으로 묶었다. 규칙 정규화였다면 나뉘었을 것이다.
  910에서도 순서·연도 부연·괄호 설명만 다른 목록들은 같은 묶음에 넣었다.

### 본 실행 비용 추정

seed 20문제의 문서는 합계 24.9만 글자로 이번 2문제(6.2만)의 약 4배다. probe 비용이 문서 길이에 비례한다고 보면
probe 약 $2.1, 전체 약 $2.5다. 추정이며 실제 값은 답 길이에 따라 달라진다.

### 후속

1번은 v4에서 고쳤다. 2·3번은 v4에서 합의를 항목 단위 F1로 바꿔 대응했다. 이번 probe 답을 고친 파서와
문자열 일치 항목(luna 묶기 없이, 하한)으로 다시 계산하면 910의 후보 점수는 0.45–0.58로 갈려 동점이 아니다.
항목 다수결 답 비교 정책은 넣었다가 실행 전에 뺐다. [결정 C40](../decisions.md).
