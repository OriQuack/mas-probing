# min_pilot

Does it help an orchestrator to **probe its workers before delegating** (ask how they read the instruction,
what they assume, what could fail, and how they plan to work) and then rewrite the delegation instruction?

This is the second GAIA pilot of the mas-uncertainty project. It uses a **minimal orchestrator–worker framework
written from scratch** (no OWL), so the method can be tested without framework side effects, compared across
pool designs and conditions, and later ported to other frameworks.

| | Question | How |
|---|---|---|
| RQ1 | Is there headroom in fixing a delegation instruction? | Restore the pre-delegation checkpoint; run the original vs a revised instruction |
| RQ2 | Do real worker answers beat orchestrator-only review at the same budget? | A (none) vs B (self-review) vs C (probe), paired from the same checkpoint |
| RQ3 | What does the extra interaction cost? | Per-stage tokens, cost and latency |

Framework spec: [`minimal framework.md`](minimal%20framework.md). Implementation choices to revisit:
[`docs/decisions.md`](docs/decisions.md).

## Framework

```
orchestrator (no tools) ── delegate(role, instruction) ──► [checkpoint] ──► InstructionRefiner ──► call_worker
        ▲                                                                   (A / B / C)          (executor)
        └────────────────────────────── report ◄───────────────────────────────────────────────────┘
```

- `call_worker(worker_id, original_task, instruction) -> report` is the only interface to workers.
- `InstructionRefiner.refine(original_task, draft, target worker, probe workers) -> instruction` is the method
  module: probe → compare → decide/verify issues → rewrite.
- Worker pools: `role_routing` (each role's own worker is probed), `redundant` (several candidate workers are
  probed, the executor is fixed), `single`.

## Setup

```bash
bash envs/doh_minpilot/setup.sh && conda activate doh_minpilot
cp .env.example .env                     # OPENROUTER_API_KEY, SERPER_API_KEY
bash scripts/crawl4ai/ensure.sh          # local page reader (pinned Crawl4AI image, Apptainer)
python -m pytest
python scripts/run_task.py fresh --task-id <id> --pool role_routing --refiner A_none
```

GAIA 2023 validation is expected at `~/data2/datasets/GAIA/2023/validation/`.
