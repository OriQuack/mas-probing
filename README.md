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
| 지금까지의 결과 확인 | [보고서 목록](docs/reports/index.md) → 최신 종합 보고서 |
| 유효한 구현 결정 확인 | [현재 결정](docs/decisions.md) |
| 구성 설계·도입 범위 | [Executor 선택·작업 기록·실행 후 평가 설계안](docs/design/shared-state-evaluation-and-routing.ko.md) |
| 실행 환경·GPU 운영 | [Slurm 운영](docs/operations/slurm.md) |

현재 프롬프트는 실행 `v24`, probe `r24`이며 도구는 `v7`입니다. Orchestrator와 worker 모두 run 동안 대화를 유지하며 evaluator와 refiner는 없습니다(C42). 최신 구성의 전체 비교 결과는 아직 없습니다.
과거 결과의 한계와 정정은 최신 종합 보고서를 기준으로 읽습니다.

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
