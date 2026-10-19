# min_pilot

Orchestrator가 run 동안 대화 하나를 유지하며 worker 보고를 직접 읽고 다음 작업·context·executor를 고르는 최소
orchestrator–worker 프레임워크입니다. `direct_execution`과 `adaptive_probe` 두 조건을 지원합니다.
기본 pool의 Luna와 Haiku 모두 executor가 될 수 있습니다. 행동은 tool call `probe`/`execute`/`finish`이며, probe 뒤 바로 답을 제출할 수 있습니다.

## 어디부터 읽나

| 목적 | 문서 |
|---|---|
| 시스템과 모듈 경계 이해 | [Framework](docs/framework.md) |
| 실제 프롬프트 읽기·수정 | [Prompt 안내](src/minpilot/prompts/README.md) |
| 조건·버전·실험 용어 이해 | [실험 안내](docs/experiments.md) |
| Pilot 결론과 교훈 | [Pilot Studies 정리 (2026-10-19)](docs/reports/2026-10-19-pilot-wrap-up.ko.md), 아래 Key Lessons |
| 지금까지의 결과 확인 | [보고서 목록](docs/reports/index.md) → 실험별 발표용 보고서 |
| 유효한 구현 결정 확인 | [현재 결정](docs/decisions.md) |
| 구성 설계·도입 범위 | [Executor 선택·작업 기록·실행 후 평가 설계안](docs/design/shared-state-evaluation-and-routing.ko.md) |
| 실행 환경·GPU 운영 | [Slurm 운영](docs/operations/slurm.md) |

현재 프롬프트는 실행 `v24`, probe `r24`이며 도구는 `v7`입니다. Orchestrator와 worker 모두 run 동안 대화를 유지하며 evaluator와 refiner는 없습니다(C42).
이 구성의 GAIA non-web 비교(34문제 × 2조건 × 2반복)는 [GAIA (non-web) Probing](docs/reports/2026-10-15-gaia-nonweb-v23-34tasks.ko.md)에 있고, pilot 전체의 결론은 아래 Key Lessons와 [Pilot Studies 정리](docs/reports/2026-10-19-pilot-wrap-up.ko.md)에 있습니다.
과거 결과의 한계와 정정은 최신 종합 보고서를 기준으로 읽습니다.

## Pilot 정리와 Key Lessons (2026-10-19)

질문: 실행 전 exploration(perturbation, probing first)으로 얻은 신호로 routing과 instruction을 정해 성능을 높일 수 있는가?
원칙: test time에 얻을 수 있는 정보와 신호만 쓰고, 정답을 보면서 routing이나 instruction을 고치지 않는다.
LongCoT linear 41문제, MoNaCo 50문제, GAIA non-web 34문제에서 다섯 실험을 했다. 설계·수치·예시는 [Pilot Studies 정리](docs/reports/2026-10-19-pilot-wrap-up.ko.md)에 있다.

| 실험 | 신호 → 결정 | 결과 |
|---|---|---|
| LongCoT Subagent Selection | 첫 subtask 일관성 → subagent 배정 | `무작위`보다 +6.8%p, 가장 강한 subagent 고정과 같음(+0.5%p). 일관성은 subtask 정답(AUROC 0.84–0.88)만 예측하고 전체 성공(0.56–0.67)은 약하게 예측. 변형(`instruction`, `surface`)은 `repeat`보다 낫지 않음 |
| LongCoT Instruction Selection | 첫 subtask 합의율 → instruction 선택 | `naive`보다 −12.2%p. instruction 자체가 긴 사슬에서 오류를 누적시키고(고정 세 축 −9~−10%p), 합의율은 어느 후보가 맞을지 예측하지 못함(AUROC 0.56, 0.47) |
| MoNaCo Instruction Selection | 문제 전체 합의율 → instruction 선택 | `naive`와 차이 없음(+0.002). 주된 실패인 항목 빠뜨림에 instruction이 닿지 않음. `naive` 답 9개 합집합은 +0.104 |
| GAIA Instruction Selection | (선택 없이 4후보 전부 실행) | 고정 후보 +2~+5 run(CI 0 포함), `사후 최고` +9.8%p(선택 편향). 같은 instruction이 문제에 따라 정답·오답 양쪽으로 작용 |
| GAIA Probing | probe 응답 → orchestrator가 실행 지시 조정 | `adaptive` 73.5% vs `direct` 83.8%(−10.3%p, CI [−20.6, −1.5]). probe 뒤 해석이 좁혀져 subagent가 대안 해석을 시도하지 않음 |

**Key lesson: 추가 호출이 이득이 되려면 결과가 서로 달라야 한다 (diversification).**

- Random forest가 잘 되는 이유는 트리마다 데이터와 feature를 다르게 뽑아 트리끼리 오류를 다르게 만들기 때문이다. 그래서 투표하면 오류가 상쇄된다.
- 이번 pilot에서는 추가 호출이 비슷한 답을 냈다. instruction을 바꿔도 답이 거의 같았고, 틀릴 때도 같은 쪽으로 틀렸다. instruction과 probing은 오히려 해석을 한 방향으로 모았다.
- 결과가 다양했던 곳에서는 이득이 보였다. subagent를 바꾸면 instruction을 바꿀 때보다 답이 더 달라졌고, MoNaCo `naive` 답 9개를 합집합으로 합치면 +0.104였다. instruction을 붙인 답들은 서로 비슷해 합쳐도 +0.03에 그쳤다.

**관측한 사실**

1. 답의 다양성에는 instruction보다 subagent 차이가 더 크게 작용했다. MoNaCo sample 답 쌍의 F1은 같은 subagent·다른 instruction 0.846, 다른 subagent·같은 instruction 0.759다. LongCoT는 41문제 중 29문제에서 네 instruction의 최빈 답이 같다. 단, GAIA에서는 해석이 갈리는 11문제에서 instruction도 경로를 바꿨다.
2. 합의율은 정답과 공통 오류를 구별하지 못했다. 같은 문제 안 AUROC는 LongCoT 0.56, MoNaCo 0.54로 우연 수준이다. MoNaCo `structured`는 합의율을 0.655 → 0.741로 올렸지만 점수는 같았다. 수렴 자체가 아니라 어느 쪽으로 수렴했는지를 합의율이 알려 주지 못하는 것이 문제다.
3. 앞 subtask의 좋은 신호가 전체 작업의 성공으로 이어지지 않았다. LongCoT 일관성 AUROC는 subtask 0.84–0.88, 전체 성공 0.56–0.67이다. instruction의 손해는 뒤 node에서 누적되는데, 앞에서 잰 합의로는 보이지 않는다.
4. 해석을 명확히 하려는 개입이 탐색을 일찍 닫았다. GAIA probing은 정답률을 10.3%p 낮췄다. subagent 보고에 정답이 있었는데 최종 답에 못 간 run도 `adaptive`가 더 많았다(후보·대안 포함 10개 대 6개).
5. 현재 후보에서는 문제별 instruction 선택의 이득이 분명하지 않았다. `사후 최고` − `naive`는 LongCoT +6.5%p, MoNaCo +0.054로 잡음 기준선(+11.3%p, +0.047)과 구분되지 않는다. GAIA는 +9.8%p지만 선택과 평가의 반복을 분리하면 +2.9%p [+0.0, +7.8]로 줄어든다. 더 좋은 instruction의 가능성을 부정하지는 않는다.

**다음 실험**

1. subagent / tool 배분 / 분해 방식을 바꿔 후보를 만들고, 그 후보들이 서로의 실패를 실제로 보완하는지 확인한다.
2. 그다음 선택과 통합 방법을 비교한다. 합의율로 고르기보다, 한 후보가 놓친 정답을 다른 후보의 근거로 보완하는 통합이 우선한다.
3. probe를 계속 쓴다면 해석을 좁히는 데가 아니라 해석 후보를 넓혀 모두 실행하는 데 써야 한다. 아직 시험하지 않았다.

## 구조

```text
src/minpilot/
  agents/              orchestrator 대화(tool call)와 worker 실행·도구 호출
  prompts/             역할별 프롬프트 본문·입력 처리, 행동 tool schema
  records.py           보고·instruction·도구 결과 원본과 보고 ID로 만드는 context
  harness.py           위임 루프, checkpoint, restore
  artifacts.py         실험 manifest와 원본 실행 탐색
  tools/, llm/         도구와 모델 호출
configs/
  pools/               등록된 executor 후보 전체
  conditions/          direct_execution / adaptive_probe
  refiners/            지원이 종료된 과거 설정; 당시 snapshot에서만 사용
docs/                  현재 설계·실험 안내·보고서
outputs/experiments/   목적별 원본 실행, manifest, 당시 코드 snapshot
outputs/analysis/      보조 trace 묶음
outputs/runs/          단건 실행
outputs/cache/         도구 cache
```

## 실행

```bash
bash envs/doh_minpilot/setup.sh
conda activate doh_minpilot
cp .env.example .env
bash scripts/crawl4ai/ensure.sh
python -m pytest
python scripts/run_task.py fresh --task-id <id> --pool multi --condition direct_execution
```

`.env`에 `OPENROUTER_API_KEY`, `SERPER_API_KEY`를 설정합니다.
GAIA validation 위치는 `~/data2/datasets/GAIA/2023/validation/`입니다.
평가 집합은 평가 전 튜닝에 사용하지 않습니다.

```bash
python scripts/show_prompts.py --component probe
python scripts/experiments.py list
python scripts/experiments.py verify
```

배치 실행·짝지은 비교·과거 경로 찾기는 [실험 안내](docs/experiments.md)를 봅니다.
