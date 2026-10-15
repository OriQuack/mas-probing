# Project working instructions

Read [README.md](README.md) first. Current design: [docs/framework.md](docs/framework.md).
Experiment definitions and version vocabulary: [docs/experiments.md](docs/experiments.md).
Latest findings: [docs/reports/index.md](docs/reports/index.md).

## Scope and code

- Keep the framework small and portable: one orchestrator selecting among registered workers, one conversation
  and one workspace per worker for the run, and one orchestrator conversation that reads reports and acts through
  `probe`/`execute`/`finish` tool calls; no evaluator, no refiner (v24/r24, C42). Do not introduce OWL's planner/coordinator/answerer split,
  structured `TaskResult`, OWL prompts/tool names, or automatic dependency passing.
- Read the original study design before changing experiment logic:
  `../pilot/docs/design/2026-10-05-GAIA-Probe-Query-Pilot-Study.md`.
- Record choices not fixed by the framework in [docs/decisions.md](docs/decisions.md).
  Historical decision IDs live in [docs/history/decisions-before-cleanup.md](docs/history/decisions-before-cleanup.md).
- Keep complete prompt bodies as readable multiline strings in `src/minpilot/prompts/` role modules.
  Share short policies/helpers where useful; avoid splitting prose across template files. The orchestrator's
  action tool schemas stay in `schemas.py`. See the package README. Runtime supports the current prompt set only.
- Bump `PROMPTS_VERSION` when orchestrator/worker text changes (restore requires an exact version).
  Bump `PROBE_PROMPTS_VERSION` when probe text changes.
  Layout-only changes that preserve rendered text need no prompt version bump.
- Tool behavior changes require a `ToolConfig.tools_version` bump and a separate cache.
- Use semantic names for experiment purposes and conditions. Do not add new stage/phase abbreviations.
  A trace's `stage` is a runtime component tag, defined in the experiment guide.

## Experiment invariants

Current runtime supports direct_execution and adaptive_probe only. The fixed-executor/refiner and paired-restore
comparison rules below describe historical experiments; new full-system comparisons use fresh runs with a separately
fixed repetition count, total spend and condition order. Historical presets/checkpoints require their snapshots.

- Never expose GAIA answers or Annotator Metadata to models. Only scoring reads answers. Keep the sandbox's
  data restrictions and blocklist on every path that sends web content to a model.
- `data/splits/eval_v1.csv` is evaluation-only. Do not inspect, run or tune on it before evaluation.
  Preselected splits must not be redrawn.
- A worker's probe and execution requests share that worker's conversation and workspace. Another worker's
  findings reach it only through reports the orchestrator selects as context; the orchestrator's conversation,
  gold answers and failure traces never reach workers.
- Compare conditions restored from the same checkpoint. A restored baseline is optional: the recording run's
  continuation after the checkpoint can serve as the baseline when restores follow it in the same tool and
  search environment. Restore a baseline when checkpoints are reused later or that environment changed.
  `score_runs.py --compare` pairs restore arms only. Hold executor, common pipeline and configured review
  budgets fixed; record actual cost.
- Report every preselected task. Non-ok or missing planned runs count as failures in their own arm.
  Aggregate reps within task, then equal-weight tasks; use paired task-level comparisons.
- Preserved historical runs, checkpoints, snapshots and recorded JSON/CSV are immutable evidence.
  Stored old paths can be resolved with `scripts/experiments.py resolve`. Do not recursively glob `run.json`;
  use `minpilot.artifacts.find_run_records` to avoid counting workspace copies.
- New batch experiments belong under `outputs/experiments/` with a manifest. Single runs use `outputs/runs/`.
  Model/tool output stays under `outputs/`, not source or documentation. Reports are curated into `docs/reports/`.

## Environment and verification

- Conda environment: `doh_minpilot`, Python 3.11; environment names follow `doh_<purpose>`.
  Shared base is read-only. Dependencies are pinned under `envs/doh_minpilot/`.
- Use `conda activate doh_minpilot` for Playwright (activation sets Chromium library paths).
- Tests are offline; use scripted models and fake web. Tests must not write to the real tool cache.
  Run `python -m pytest`; Landlock/GAIA-dependent tests may skip where those facilities are unavailable.
- Models and providers are pinned in `llm/specs.py`; API keys stay in `.env` and must not enter artifacts.
- Data and weights go under `/data2`; use `HF_HOME=/data2/dohyun/hf`, never `~/.cache/huggingface`.
- API and CPU-only work can run in the shell. CUDA workloads must go through Slurm with `--gres=gpu:N`.
  Never work around the GPU-use block. See [Slurm operations](docs/operations/slurm.md).
- Slurm scripts set job name, time, memory and `logs/%x-%j.out`; create `logs/` before submission.
  Source `/home/compu/anaconda3/etc/profile.d/conda.sh`, activate the environment, then enable `set -e`/`-u`.
  Use unbuffered Python, inspect partition limits before long jobs, and stop servers when planned work ends.
