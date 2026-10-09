# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

min_pilot is the second GAIA pilot of the mas-uncertainty project. It replaces OWL with a **minimal
orchestrator–worker framework written from scratch**, so the method can be tested without OWL's own failure
modes, by varying one component at a time, and later ported to other frameworks.
- The framework spec (Korean) is `minimal framework.md` at the repo root.
- The study design (RQ1–RQ3, conditions A/B/C, invariants) is the previous pilot's
  `../pilot/docs/design/2026-10-05-GAIA-Probe-Query-Pilot-Study.md`. The goal is the same; read it before
  changing experiment logic.
- **`docs/decisions.md` lists every implementation choice the spec does not fix.** When you make a new choice of
  that kind, add it there (ID, choice, alternative, where).
- `docs/reuse_from_pilot.md` lists what was copied from `../pilot` and the OWL-specific choices left out.

Stage (2026-10-09): the 2026-10-08 baseline (tools v2, prompts v1, refiner prompts r2;
`outputs/sessions/pilot-base-v2-20261008T160736Z/`, report `outputs/sessions/REPORT_20261008.md`) is
**superseded** by the user's revisions of 2026-10-09: refiner prompts r4 (R14), prompts v2 (F16, answer rules from
the benchmark), tools v3 (K17: AOrchestra's question-based reader in `read_url`; `read_url_text`, `find_in_url`).
Old checkpoints cannot be restored under them. Next (E5): inspect the validation pass `outputs/sessions/v3-check-*`,
freeze, record the new baseline on `data/splits/baseline_v1.csv` (50 tasks, L1:L2:L3 = 8:25:17, contains the 12 dev
tasks; E6) × 1 rep with checkpoints, on the `single` pool (P6, prompts v4); open items in `docs/decisions.md` (F14, K8–K14, R3);
more exploration tasks for Exp 1 headroom.

## Do not bring OWL back

The previous pilot (`../pilot`) ran on OWL. Do **not** copy OWL-framework choices into min_pilot: roles split into
Planner, Coordinator and answerer; replanning; `TaskResult` structured worker output; OWL prompts and tool names;
`browse_url`; dependency-result passing. Framework-independent components (web backends, cache, blocklist, sandbox,
scorer, splits) may be copied; record the copy in `docs/reuse_from_pilot.md`.

## Layout

```
minimal framework.md     framework spec (user's; authoritative for the framework)
configs/pools/           worker pools: single (default, P6), role_routing, redundant (workers + roles)
configs/refiners/        conditions: A_none, B_self_review, C_probe (main contrast: same steps after collection);
                         variants C_probe_followup, C_probe_tools, C_probe_connected, C_probe_connected_norewrite,
                         C_probe_x2 / B_self_review_x2
src/minpilot/
  harness.py             orchestrator loop, call_worker, checkpoints, restores (one Run per task run)
  config.py              WorkerSpec, RoleSpec, PoolConfig, RefinerConfig, RunConfig (+ YAML loading)
  agents/                orchestrator.py, worker.py, prompts.py (all prompts, PROMPTS_VERSION)
  refine/                base.py (InstructionRefiner interface, NoRefiner), review.py (B and C)
  llm/                   specs.py (model keys), client.py (OpenRouter over HTTP, budget, validation)
  runtime/trace.py       records (llm/tool/events), stage tags, budget scopes
  tools/                 toolbox.py (worker tools), web.py, reader.py (read_url's page reader, from AOrchestra),
                         sandbox.py, backends/cache/blocklist/antibot/documents
  data/gaia.py, eval/    GAIA loading (no answers), GAIA's answer rules (ANSWER_FORMAT), scorer, extraction rule
scripts/                 run_task.py, score_runs.py, crawl4ai/, slurm/
data/splits/             pre-registered task lists (copied from the previous pilot, + baseline_v1; never redraw)
docs/                    decisions.md, reuse_from_pilot.md, failure_codebook.md, labelling_protocol.md,
                         review_2026-10-09.md (implementation review and responses), cluster/slurm.md
envs/doh_minpilot/       requirements.txt, setup.sh, requirements.lock
tests/                   pytest, offline (scripted models, fake web)
outputs/, logs/          gitignored run artifacts
```

## Framework in one paragraph

One orchestrator (`luna-high`: no tools, JSON actions) runs a dynamic loop: each turn it either delegates one
subtask (an instruction) to a **role**, or finishes with the answer (the benchmark's answer rules are passed in; the
answer is stored as given, with no re-output step). A role maps to a fixed **executor** worker and to its
**probe workers**. The default pool `single` has one role (a generalist worker with all tools), so the orchestrator
only writes instructions and chooses no role (P6); `role_routing` (web / file roles) is kept for a robustness check. `call_worker(worker_id, original_task, instruction) -> report` is the only way work gets done.
A worker (`luna-high`, effort high, with tools) gets the original task and the instruction only, runs a tool loop and
returns a free-text report; it keeps no state between calls. Web workers read pages through `read_url(url,
question)` (a fixed `luna-high` page reader that sees only the page and the question; its calls count toward the
budgets), with `read_url_text` and `find_in_url` for raw text. Before a selected delegation (`refine_at:
first|all|none`), the harness passes the draft to the **InstructionRefiner** (the method module).
- A: none.
- B: the orchestrator-side model predicts the probe answers itself.
- C: real probe workers answer.

In B and C, analysis, follow-ups (C only), verification delegated to workers, and one rewrite follow. Probes and
verifications run on scratch copies of the workspace and in conversations that never reach the orchestrator or the
execution (except in the "connected" condition). Every delegation point is checkpointed. A restore resumes it under
any condition, or with a post-hoc override (Exp 1).

## Commands

```bash
conda activate doh_minpilot                      # build: bash envs/doh_minpilot/setup.sh
python -m pytest                                 # offline suite (needs Landlock + GAIA data for zero skips)
bash scripts/crawl4ai/ensure.sh                  # page reader; or reuse a running one:
export CRAWL4AI_ENDPOINT=/home/dohyun/mas-uncertainty/pilot/outputs/servers/crawl4ai.json
python scripts/run_task.py fresh --task-id <exploration id> --pool single --refiner A_none --label base_r0
python scripts/run_task.py restore --checkpoint outputs/runs/<t>/<run>/checkpoints/d0 --refiner C_probe --label C_r0
python scripts/run_task.py restore --checkpoint ... --query-file q.txt --source post_hoc    # Exp 1 override
python scripts/score_runs.py [outputs/runs/...]                                             # -> outputs/scores/
python scripts/run_batch.py --tasks data/splits/executor_selection_v1.csv --reps 3 --session outputs/sessions/<name>
python scripts/run_batch.py --checkpoints cks.txt --refiners A_none B_self_review C_probe --reps 3 \
    --session outputs/sessions/<name>              # paired restores; planned.csv records every run's arm
python scripts/score_runs.py <session>/runs --out <session>/scores.csv --expected <session>/planned.csv \
    [--compare A_none C_probe] [--exclude contaminated.txt]   # arms by condition; paired bootstrap on checkpoints
python scripts/audit_contamination.py <session>                                             # current blocklist
python scripts/prepare_labelling.py <session>     # transcripts/ (render_trace.py) + labels/outcomes.csv
```
Labelling: `docs/failure_codebook.md` (min_pilot's own categories and actors) and `docs/labelling_protocol.md`
(blind to the ground truth; one JSON + one short rationale per run in `<session>/labels/`).
Run dirs: `outputs/runs/<task_id>/<stamp>_<label>/`, which hold:
- `run.json`;
- `events.jsonl`, `llm_calls.jsonl`, `messages.jsonl`, `tool_calls.jsonl`;
- `work/`;
- `checkpoints/d<k>/`: `state.json`, `fingerprint.json`, `request.json` (the refiner's input), `work/`;
- `refine/d<k>.json`;
- `scratch/`.

Every record carries a `stage` tag (`orchestrator`, `execution`, `refine.review|probe|followup|analyze|verify|rewrite`);
page-reader calls inside `read_url` also carry `component: reader` and the `tool_call` number.

## Invariants (from the study design; easy to break)

- **No answer leakage:** GAIA `Final answer` and `Annotator Metadata` never reach any model. `data/gaia.py` drops
  them; only `scripts/score_runs.py` reads answers. The sandbox cannot read `/data2`. The blocklist filters every
  path where web text reaches a model.
- **Eval set** (`data/splits/eval_v1.csv`, 24 tasks) is for Exp 2 only. Never run, inspect or tune on it before
  then (`run_task.py` refuses it without `--allow-eval`). Exploration: `exploration_v1.csv`.
- **The refiner sees only its `RefineRequest`** (original task, draft, target, probe workers) and the worker
  profiles. It never sees the continuation, failure traces or the answer. Post-hoc rewrites written by a human or
  by Claude after reading traces are Exp 1 only: run them with `--source post_hoc` and keep them out of probe-effect
  claims.
- **Probe isolation:** probe and verification conversations and files never reach the execution, except what the
  rewritten instruction states (and the explicit `connect_probe_to_execution` condition).
- **Equal budgets for B and C** (`RefinerConfig.budget`, `max_verifications`, samples), and **the same steps after
  collecting answers** (no follow-ups in the main contrast; `C_probe_followup` is a separate variant). The executor
  is fixed across A/B/C. A `refine_error` (unusable refiner reply) executes the draft and is reported separately.
- **Paired comparison:** every condition, A included, restores the same checkpoint. The recording run's own
  continuation is not an A rep. Reps: about 3 per condition; interleave condition order.
- **Report all pre-selected tasks;** non-`ok` runs count as failures. Aggregation: per-task success over reps, then
  the equal-weight mean over tasks; paired task-level bootstrap for differences.
- Version bumps:
  - Orchestrator or worker prompts: bump `PROMPTS_VERSION` (restores refuse a mismatch).
  - Probe, review, analysis or rewrite prompts: bump `REFINER_PROMPTS_VERSION` (recorded; restores may use a newer
    one, since refinement happens after the checkpoint).
  - Tool behaviour: bump `ToolConfig.tools_version` (a new cache file; restores refuse a mismatch).

## Models

Keys are in `llm/specs.py`. Each key pins the model id, one provider (no fallbacks), `require_parameters`,
`data_collection: deny`, the generation cap, sampling and reasoning effort.
- Defaults (2026-10-09, M1): **every role uses `luna-high`** (GPT-6 Luna, effort high): orchestrator, refiner,
  workers (with tools) and the page reader. Tools at effort high work through OpenRouter's Chat Completions
  (OpenAI's own Chat Completions would refuse them; M4); runs flag stages without reasoning tokens (`warnings`).
  `luna` (effort none) is kept for comparisons.
- `gemini` is the second candidate in the `redundant` pool. Which Gemini model to use is still open.
- `gpt4o` is available.
- Every call is cost-reserved before sending, validated (provider, served model, cost) and recorded. Paid tool
  calls are priced in `runtime/costs.py` and count toward `cost_usd` and budgets (`llm_usd`, `tool_usd`,
  `tool_usd_cold`).
- Secrets live in `.env`: `OPENROUTER_API_KEY`, `SERPER_API_KEY`.

## Environment

- Conda env **`doh_minpilot`** (lab rule: every env is named `doh_<purpose>`; envs live in `~/.conda/envs`; the
  shared base env is read-only). Python 3.11, current packages, no camel/OWL.
- Chromium libs come from conda-forge and are put on `LD_LIBRARY_PATH` by an activation hook. **The Playwright
  reader works only after `conda activate`**, not when you call the env's python by path.
- Containers: Apptainer, rootless; images in `/data2/dohyun/containers/`. The Crawl4AI image is pinned in
  `scripts/crawl4ai/IMAGE`.
- Data: GAIA at `~/data2/datasets/GAIA/2023/{validation,test}/`. All weights and datasets go on `/data2`, with
  `HF_HOME=/data2/dohyun/hf`; never write to `~/.cache/huggingface`.

## Compute: GPU work must go through Slurm (lab policy)

Full guide: `docs/cluster/slurm.md`.
- **Never run CUDA workloads directly in the shell.** Any GPU work goes through Slurm (`sbatch`, `srun` or
  `salloc` with `--gres=gpu:N`). GPU use outside Slurm is soft-blocked; do not work around the block.
- API-only work, like this framework's runs on OpenRouter, and CPU-only scripts may run directly in the shell.
- Cluster: one node `gpu01`, partition `main`, 2× RTX PRO 6000 Blackwell, shared with users whose jobs need both
  GPUs. Check the partition time limit with `sinfo` before requesting a long `--time`; the default is 2 h.
- Template (submit from the repo root):
  ```bash
  mkdir -p logs   # Slurm will not create it; the job fails without it
  sbatch scripts/slurm/gpu_job.sbatch python -u <script.py> [args]      # CONDA_ENV=<env> to override doh_base
  srun --gres=gpu:1 --mem=16G --time=00:30:00 --pty bash                 # quick interactive test
  ```
  Monitor jobs with `squeue -u $USER` and `sacct -j <id> --format=JobID,State,Elapsed,MaxRSS`. Cancel with
  `scancel <id>`.
- Every job script sets `--job-name`, `--time`, `--mem` and `--output=logs/%x-%j.out`.
- Slurm jobs do not source `~/.bashrc`: run `source /home/compu/anaconda3/etc/profile.d/conda.sh` before
  `conda activate`. Enable `set -e`/`-u` only **after** `conda activate`; otherwise the job dies silently in about
  1 s (a bash 5.2 issue). Run Python with `-u` or `PYTHONUNBUFFERED=1` so logs stream.
- Start servers only for planned sessions and `scancel` them as soon as the work ends. Never leave a GPU idle.

## Conventions

- Run outputs go under `outputs/` (gitignored), never into `src/` or `docs/`. Tests never write to the real tool
  cache (a session fixture checks this).
- Tests are offline. `tests/fakes.py` provides `ScriptedLLM` (a fake OpenRouter that routes by request kind and
  model) and a fake web.
- Keep the code small and framework-agnostic. The refiner talks to the harness only through `RefineContext`;
  porting it to another framework means implementing that context.
