# min_pilot

Worker에게 작업을 위임하기 전에 이해·가정·위험·계획을 물으면, 더 나은 지시문을 만들 수 있는지
검증하는 최소 orchestrator–worker 프레임워크입니다. GAIA를 사용하며 실행 worker를 고정해
지시문 변경 효과를 비교합니다.

## 어디부터 읽나

| 목적 | 문서 |
|---|---|
| 시스템과 모듈 경계 이해 | [Framework](docs/framework.md) |
| 실제 프롬프트 읽기·수정 | [Prompt 안내](src/minpilot/prompts/README.md) |
| 조건·버전·실험 용어 이해 | [실험 안내](docs/experiments.md) |
| 지금까지의 결과 확인 | [보고서 목록](docs/reports/index.md) → 최신 종합 보고서 |
| 유효한 구현 결정 확인 | [현재 결정](docs/decisions.md) |
| 실행 환경·GPU 운영 | [Slurm 운영](docs/operations/slurm.md) |

현재 프롬프트 식별자는 실행 `v10`, refiner `r12`입니다. 최신 구성의 전체 비교 결과는 아직 없습니다.
과거 결과의 한계와 정정은 최신 종합 보고서를 기준으로 읽습니다.

## 구조

```text
src/minpilot/
  agents/              orchestrator와 worker 실행
  prompts/             역할별 프롬프트 본문·입력 처리, 응답 스키마
  refine/              probe → analysis → verification → rewrite
  harness.py           위임 루프, checkpoint, restore
  artifacts.py         실험 manifest와 원본 실행 탐색
  tools/, llm/         도구와 모델 호출
configs/
  pools/               역할·실행 worker·probe worker 구성
  refiners/            현재 비교 조건; variants/는 선택적 기능
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
python scripts/run_task.py fresh --task-id <id> --pool multi --refiner baseline
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
