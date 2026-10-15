# MoNaCo 문제별 instruction 합의 선택 실험

`monaco-instruction-selection-v7`는 orchestrator 밖 별도 실험이다. LongCoT의 `instruction-selection-v3`를
MoNaCo oracle 설정으로 옮긴 것이다. node 분할과 gold decomposition은 쓰지 않고 문제 전체를 한 번에 푼다.

**이 문서가 현재 설계의 정본이다.** 결정 이유와 변경 이력은 [decisions C40](../decisions.md)에, 실행별로 적용된
값(version, 모델 identity, seed, 대상, 비용 상한, 코드 hash)은 각 실험의 `manifest.json`에 있다. 구현은
`src/perturbation_consistency/monaco_instruction_selection.py`이며, 이 문서와 코드가 다르면 둘 중 하나를 고친다.
v7 50문제 결과는 [v7 보고서](../reports/2026-10-15-monaco-instruction-selection-v7.ko.md)에 있다.

| version | 바뀐 것 |
|---|---|
| v1 | 규칙 정규화 완전 일치 합의, judge `luna`(effort none) |
| v2 | 답 전체를 luna 한 번 호출로 묶는 합의, 실패 slot 재시도, sync 동시 4 |
| v3 | judge·묶기 `luna-low` |
| v4 | 마지막 `ANSWER:` 뒤 JSON 파싱, 항목 단위 묶기와 항목 F1 합의 |
| v5 | judge `luna-high`, judge에는 파싱한 최종 답 한 줄만 |
| v6 | 목록 점수 recall 상한. v5와 하나로 합쳐 분석한다 |
| v7 | 답 형식을 자유 서술 + 마지막 `Answers:` 줄로, 항목 나누기 단계와 코드 확인 추가, 대상은 층화 50문제, 후보는 decompose·clarify·structured(가져오기만). v6 이전과 합치지 않는다 |

## 설계

- 입력: 질문과 oracle 문서(공개된 gpt-4o oracle 실행의 `input_documents`, 논문 oracle 설정과 같은 문서)와
  후보 instruction, 공통 답 형식. gold·decomposition·judge 내용은 모델에 주지 않는다.
- 답 형식(`ANSWER_FORMAT`): 자유 서술 뒤 마지막 줄 `Answers: <최종 답>`. 그 줄에는 설명 없이 답만 쓰고, 해당하는
  것이 없으면 `Answers: none`. 숫자·yes/no 표기나 항목 구분자는 정하지 않는다. 공개 실행 출력도 자유 서술 뒤
  `Answers:` 줄이다(1,287개 중 1,258개). v6까지의 JSON 목록 형식은 합의를 규칙으로 비교하려고 우리가 넣은 것이었고,
  yes/no 질문에 항목 이름을 내거나 개수 질문에 목록을 내는 부작용이 있었다.
- 답 줄 읽기(`answer_line`): 줄 머리의 마지막 `Answers:`(`Answer:`, `Final answer:`, 굵게 표시 포함) 뒤 같은 줄의
  글자. 같은 줄이 비면 다음 줄부터 빈 줄 전까지를 글머리표를 떼고 "; "로 잇는다. 표시가 없거나 비면 `no_answer`.
- 대상 pool: oracle 문서가 있고, 시간 비의존으로 표시돼 있고, 문서 합계 4만 글자 이하인 540문제.
- 대상 선정(기본, 층화 50문제): 공개 GPT-4o·Llama-3.1-405B oracle 실행의 GPT-4.1 judge 점수 평균이 0이거나 1인
  문제를 뺀다. 목록 문제는 평균 점수 구간 [0, 0.2)·[0.2, 0.4)·[0.4, 0.6)·[0.6, 0.8)·[0.8, 1)에서 6개씩(gold 값
  100개 초과는 제외), 단일 답 문제는 두 실행 중 하나만 맞힘(점수 1과 0)과 부분 점수에서 10개씩 뽑는다. 층마다 정렬한
  문제 목록에서 `random.Random(0).sample`. 이전 실험에서 쓰거나 점검한 문제도 포함한다. 공개 점수와 gold의 형태(유형,
  값 개수)를 읽는 분석 측 선택이고 모델에는 보이지 않는다. headroom 측정용 대상이라 pool 전체의 추정이 아니다.
  층별 문제 수와 표본은 `target_selection.json`, 문제별 층은 `targets.jsonl`의 `stratum`. `--ex-nums`로 pool 안의
  문제를 직접 지정할 수 있다.
- 후보(v7): naive(지시 없음), decompose, clarify, structured. 문제마다 질문만 보고 작성한 지시를 `import-candidates`로
  가져온다(생성 모델 호출 없음, 추가 API 비용 0). 작성 기록은
  `outputs/analysis/2026-10-14_monaco-method-instruction-candidates/`(`authoring_rules.md`, `rules_amendment_1.md`,
  `rules_amendment_2.md`, `review_checklist.md`, `drafts/`, `assemble.py`, `apply_amendment_2.py`, 최종
  `candidates.reviewed.jsonl`). 축마다 공통 틀 문장이 같고, 문제별 부분은 decompose·clarify에서 한 문장, structured에서는
  표 머리줄과 행 단위다.
  - decompose(Least-to-Most, Zhou et al., ICLR 2023): 풀이자가 직접 하위 질문을 세워 앞 답을 뒤에 쓰는 순서로 풀고,
    마지막 결합(세기·합치기·비교·정렬)을 마지막 하위 질문으로 둔다. 조회 답은 문서 인용, 뒤 질문은 "We know that"으로
    앞 답을 밝힌다. 작성자는 하위 질문 목록을 쓰지 않고 마지막 결합과 그것이 기대는 질문 부분만 질문의 말로 적는다.
  - clarify(Metacognitive Prompting, Wang & Zhao, NAACL 2024, 해석만): 답하기 전에 범위·속성·시간 장소 단위·지시어·결합
    방식에 대한 이해를 밝히고 질문 문구와 대조해 다시 확인한다. 용어는 엄격하거나 기술적인 뜻이 아니라 보통의 뜻으로 읽고,
    문구보다 범위를 좁히지 않는다. 정말 애매하면 질문자가 의도했을 가장 그럴듯한 해석을 고르고 근거 단어를 댄다. 답 자체의
    재검증은 시키지 않는다. 작성자는 이 질문에서 짚어야 할 구절만 적고 해석을 정하지 않는다.
  - structured(Tab-CoT, Jin & Lu, Findings ACL 2023; 항목 × 속성 표는 우리 변형): 답하기 전에 지정한 머리줄의 markdown 표를
    쓰고, 문서에 나온 후보마다 한 행(단일 대상 문제는 필요한 사실마다 한 행)을 빠짐없이 채운 뒤 표에서 답을 낸다. 질문이
    범위로 삼는 범주 명사(kingdom 등)나 조건 묶음("Meets all conditions?")으로 행을 거르는 판정 열은 두지 않는다. 판정 열은
    질문의 명시적 임계값·비교와, 대체할 서술이 없는 질문 자체의 제한 조건에만 둔다. 나머지 조건은 문서 서술을 적는 열이다.
    목록·절·표의 맥락이 조건을 보여 주면 그 조건은 충족된 것으로 본다.
  - 공통: 1–180단어, 서로 다름, 답·힌트·질문에 없는 사실 금지, 조건·범위·답 형식 변경 금지, 끝은 "give the final answer
    in the required format". 가져올 때 코드 검사(`validate_candidates`)는 key 세 개, 1–180단어, 서로 다름, 검토 기록
    (`accepted`, `notes`)뿐이다. 50개 지시에 gold 값 문자열과 질문에 없는 숫자가 없음은 분석 측에서 따로 확인했다.
  - 작성자와 검토자는 질문만 봤다. amendment 2(보통 뜻 읽기, 범주·묶음 판정 열 제거, 맥락 규칙)는 이전 결과를 보고 정한
    데이터셋 수준 규칙이고, 층 표를 본 세션이 50문제에 같은 규칙으로 적용했다(문제별 결과로 고친 것이 아니다).
  - `authoring_rules.md`는 답 형식을 v6의 `ANSWER: <JSON list>`로 적고 있다. 지시문은 답 형식을 다시 쓰지 않아 v7의
    `Answers:` 줄과 충돌하지 않는다.
  - v6까지의 세 축(analogical, clarify, local_check)은 LongCoT `instruction-selection-v3`에서 옮긴 것이었고 sonnet-high가
    질문만 보고 생성했다. v7에서는 생성 모드를 없앴다.
- Probe: haiku-medium, luna-medium, flash-lite-high가 후보마다 3회. 답은 `answer_line`으로 읽은 답 줄이다.
- 항목 나누기(v7): 문제당 `luna-low` 한 번 호출로 그 문제의 probe 답 줄(서로 다른 것)을 항목으로 나눈다. 입력은 질문과
  답 줄뿐이고(문서·추론·gold 없음), 순서는 seed로 섞고 worker·후보는 표시하지 않는다. 항목은 줄에 적힌 그대로의
  연속 구간이고, 괄호 부연은 그 항목 안에 둔다. 줄마다 상태는 `answer`, `empty`(해당 없음), `no_answer`(답 거부·정보
  없음)다. 코드 확인(`items_cover`): 항목이 줄 안에 순서대로 그대로 있고, 항목이 덮지 않은 나머지는 구두점과
  "and"·"or"뿐이어야 한다. 바꿔 쓴 항목, 만든 항목, 빠뜨린 부분, 순서가 틀린 경우를 잡는다. 형식이 틀린 응답이나 확인에
  실패한 줄이 있으면 다시 묻고(한 호출 안에서 최대 4번), 그래도 실패한 줄은 `invalid`로 남겨 그 slot을 실패로 센다(`split_line_statuses`).
  "X and Y"가 항목 하나인지 둘인지, `empty`와 `no_answer`의 구분은 코드로 확인하지 않는다.
- 항목 묶기: 문제당 `luna-low` 한 번 호출로 그 문제의 probe 답 36개를 나눈 항목(서로 다른 것)을 같은 대상끼리
  묶는다. 입력은 질문과 항목 문자열뿐이다(문서·추론·gold 없음). 순서는 seed로 섞고 worker·후보는 표시하지
  않는다. 표기·부연 차이는 같은 항목, 범위가 넓거나 좁은 항목(범주와 그 하나)이나 다른 값은 다른 항목이다.
  답이 아닌 항목("unknown" 등)은 `no_answer`로 빼고, 그런 항목뿐인 답은 실패 slot이다. 응답이 id를 정확히 한
  번씩 나누지 않으면 다시 묻는다(한 호출 안에서 최대 4번).
- 합의와 선택: 두 답의 합의는 항목 묶음 집합의 F1이다(`empty` 답끼리 1, 실패 slot 0). 후보 점수는 9개 답 중 가장
  중심인 답이 9개 slot(자신 포함)과 갖는 평균 F1이다. 답이 항목 하나뿐이면 LongCoT의 최대 묶음/9와 같다.
  최고 점수 후보를 고르고 동점은 seed 0 균등 무작위, 교차 worker 쌍의 평균 F1은 보조 지표다.
  나눈 항목의 규칙 정규화 완전 일치 합의는 `rule_scores`로 진단용만 남긴다.
- 묶기 검증(v2의 답 전체 묶기, effort none)은
  [묶기 검증 보고서](../reports/2026-10-14-monaco-answer-clustering-validation.ko.md).
- 실행: probe와 별도로 haiku-medium이 후보마다 3회 새로 푼다. 선택(probe 답)과 평가(새 실행)를 분리한다.
  선택에 쓴 probe 답으로 채점하면 잡음이 좋게 나와 뽑힌 몫이 점수에 남는다.
- 채점: 공개 데이터의 judge prompt 두 종류를 원문 그대로 쓰고 judge는 `luna-high`다. judge에는 실행 응답 원문 대신 답 줄을 `Answers: ...` 한 줄로 넘기고, 답 줄이 없는 응답만
  원문을 넘긴다. 실행 답은 나누지 않는다(항목 수는 judge가 센다). 원문을 넘기면 judge가 근거·제외 절의 항목까지 답으로 셌다. judge 검증(공개 GPT-4o 답)은 원문 그대로다.
  gold가 목록이 아닌 값 하나이면 단일 prompt(점수 = final precision, 숫자는 정규화 유사도),
  그 외는 목록 prompt(F1; precision = 겹친 수 / max(판정 답 수, 겹친 수), recall = min(겹친 수, gold 값 평탄화 개수) / gold 값 평탄화 개수).
  recall 상한은 v6부터다. 그 전에는 judge가 gold보다 많은 겹친 항목을 내면 recall과 점수가 1을 넘었다.
  처음 20문제(v4 실행)의 실행 점수는 v5 재채점(`2026-10-14_monaco-instruction-selection-rejudge`)의 것을 쓴다.
  공개 GPT-4o oracle 1,287문제에서 prompt는 1,275개가 문자 단위로 같고, 공개 judge 응답에서 점수를
  단일 676/676, 목록 607/611 재현한다. 다른 경우는 공개 채점의 두 결함이다:
  "How many" 문제의 gold 0/1을 `['No']`/`['Yes']`로 넣은 12개, `###` 앞의 빈 항목을 정답으로 센 경우.
  우리는 둘 다 따르지 않는다. 행이 여러 값인 gold는 recall 분모가 값 개수라 완전 정답도 1이 되지 않는다.
- Judge 검증: 대상 문제의 공개 GPT-4o 답을 우리 judge로 재채점해 GPT-4.1 점수와 비교한다.

## 실행

`doh_minpilot` 환경에서 실행한다. 유료 단계에는 단계 누적 상한 `--session-cost-usd`와
호출당 상한 `--run-cost-usd`가 필수다. 호출당 상한은 가장 큰 예약액(flash-lite-high 약 $0.083)보다 커야 한다.

```bash
S=scripts/run_monaco_instruction_selection.py
E=outputs/experiments/<date>_monaco-instruction-selection
python $S prepare --experiment $E --dry-run            # 대상·호출 수·prompt 확인, 쓰기 없음
python $S prepare --experiment $E [--ex-nums N ...]
python $S validate-judge --experiment $E --session-cost-usd "$B" --run-cost-usd "$R"
python $S import-candidates --experiment $E --candidate-file <reviewed.jsonl> --author "<author>" \
  --review-type "<how the candidates were reviewed>"
python $S probe --experiment $E --session-cost-usd "$B" --run-cost-usd "$R"   # 재실행으로 실패 slot 재시도
python $S split --experiment $E --session-cost-usd "$B" --run-cost-usd "$R"
python $S cluster --experiment $E --session-cost-usd "$B" --run-cost-usd "$R"
python $S select --experiment $E
python $S execute --experiment $E --session-cost-usd "$B" --run-cost-usd "$R"
python $S judge --experiment $E --session-cost-usd "$B" --run-cost-usd "$R"
python $S analyze --experiment $E
```

sync 동시 실행 기본값은 4다(`--concurrency`). 재실행은 끝난 slot을 건너뛴다. 재시도(v7):
- probe: client 재시도 후에도 실패한 호출(`error`, 예: HTTP 429, 문맥 초과), 길이 제한으로 끊긴 응답(`length`),
  답 줄이 없는 응답(`no_answer`)을 한 번 다시 한다(slot당 2번까지).
- judge 검증·나누기·묶기·judge: 실패한 호출은 재실행 때 slot당 4번까지, 형식이 틀린 응답은 한 호출 안에서 4번까지
  다시 묻는다.
- 실행: 실패한 호출만 slot당 4번까지 다시 한다. `length`와 `no_answer`는 결과로 두고 0점이다. 평가 표본에서 실패만
  다시 뽑으면 점수가 좋게 나오기 때문이다.
- 예산 상한으로 멈춘 slot은 항상 다시 한다. 기록은
덧붙이기만 하고 slot의 마지막 기록을 쓴다. `split`은 재시도할 probe slot이 남아 있으면 멈추고, 나누기가
시작되면 probe는 닫힌다. `cluster`는 모든 문제의 나누기가 끝나야 시작한다.
후보·prompt·계획은 가져오기 직후 해시로 고정되고, 바꾸려면 새 실험을 만든다.

## 산출물

`manifest.json`, `targets.jsonl`, `inputs.jsonl`, `candidates.jsonl`, `prompts.jsonl`, `planned.csv`,
`target_selection.json`(층화 대상), `judge_validation*.json(l)`, `results.jsonl`(probe), `splits.jsonl`, `clusters.jsonl`,
`selection.jsonl`,
`executions.jsonl`, `judgements.jsonl`,
단계별 `*_jobs.jsonl`과 trace, `analysis/summary.json`. 정책은 문제마다 고른 후보의 실행 3회 평균 점수로 잰다.
`selected`(합의 점수 최고, 동점은 seed), `cross_selected`(교차 worker 합의 최고), 축별 고정 4개, `random`(후보 4개
평균), `best_in_hindsight`(실행 점수 최고 후보, gold 사용), `tie_average`(합의 최고 동점 후보들의 평균). probe 답 채점의
`probe_oracle`(probe 점수 최고 후보들의 실행 평균)도 gold를 읽는 진단값이며 선택 규칙이 아니다. 문제 동일 가중, 누락·실패·미채점 실행은 0점,
paired bootstrap CI, judge prompt 유형별·층별(`by_stratum`) 분리 결과를 함께 낸다. 층별 결과는 층 안의 문제 동일
가중이고, 대상이 층마다 같은 수라 전체 평균은 pool 비율을 반영하지 않는다. `hindsight_null`은 문제마다 실행 점수를 후보 구분 없이
섞어 다시 나눴을 때(2000회, seed 0)의 best_in_hindsight − naive 분포다. headroom은 0이 아니라 이 분포와 비교한다.

끝난 실험의 실행을 현재 judge로 다시 채점(원본은 읽기만, targets·inputs·executions·selection을 복사):

```bash
J=scripts/rejudge_monaco_instruction_selection.py
python $J prepare --experiment <new dir> --source <finished experiment>
python $J validate-judge --experiment <new dir> --session-cost-usd "$B" --run-cost-usd "$R"
python $J judge --experiment <new dir> --session-cost-usd "$B" --run-cost-usd "$R"
python $J analyze --experiment <new dir>   # 원래 judge 점수와 함께 기록
```

probe 답을 같은 judge로 채점(분석 전용, gold를 읽으므로 선택에 쓰지 않음). `--judged`는 실행이 현재 judge로 채점된
실험이다(원본 자신 또는 그 재채점). 원본의 targets·inputs·results·selection과 judged의 executions·judgements를 복사하고
`probe_judgements.jsonl`, `analysis/summary.json`(합의·probe 점수·실행 점수의 순서 일치, `probe_oracle`)을 쓴다:

```bash
P=scripts/judge_monaco_probes.py
python $P prepare --experiment <new dir> --source <finished experiment> --judged <judged experiment>
python $P judge --experiment <new dir> --session-cost-usd "$B" --run-cost-usd "$R"
python $P analyze --experiment <new dir>
```

현재 judge로 채점된 실험 여러 개를 문제 동일 가중으로 합쳐 분석(호출 없음, v5·v6는 하나로 합치고 v7은 그 이전과 합치지 않는다):

```bash
python scripts/analyze_monaco_pooled.py --out <new dir> --parts <judged experiment> ... \
  [--probe-judged <probe judging> ...]
```

묶기 검증(공개 답, seed 20문제 제외):

```bash
V=scripts/validate_monaco_answer_clustering.py
python $V prepare --experiment <dir> [--dry-run]
python $V cluster --experiment <dir> --session-cost-usd "$B" --run-cost-usd "$R"
python $V analyze --experiment <dir>
```

```bash
python -m pytest tests/test_monaco_instruction_selection.py tests/test_datasets.py
```
