#!/usr/bin/env python
"""Run one GAIA task fresh, or continue a checkpoint under a condition.

  python scripts/run_task.py fresh --task-id <id> [--pool role_routing] [--refiner A_none] [--refine-at first]
  python scripts/run_task.py restore --checkpoint <run>/checkpoints/d0 --refiner C_probe [--label C_r0]
  python scripts/run_task.py restore --checkpoint ... --query-file q.txt --source post_hoc   # Exp 1 override

Exit codes: 0 run finished (any status recorded in run.json), 3 eval task without --allow-eval,
4 page-reader service not running, 5 error_infra.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")

from minpilot.config import RunConfig, load_pool, load_refiner  # noqa: E402
from minpilot.data.gaia import load_task  # noqa: E402
from minpilot.harness import Run, new_run_dir  # noqa: E402
from minpilot.runtime.trace import Limits  # noqa: E402
from minpilot.tools.backends import crawl4ai_status  # noqa: E402
from minpilot.tools.config import ToolConfig  # noqa: E402


def eval_task_ids() -> set[str]:
    import csv

    with open(REPO / "data" / "splits" / "eval_v1.csv") as f:
        return {r["task_id"] for r in csv.DictReader(f)}


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    f = sub.add_parser("fresh")
    f.add_argument("--task-id", required=True)
    f.add_argument("--pool", default="role_routing")
    f.add_argument("--refiner", default="A_none")
    f.add_argument("--refine-at", default="first", choices=["first", "all", "none"])
    f.add_argument("--orchestrator-model", default="luna-high")
    f.add_argument("--refiner-model", default="luna-high")
    f.add_argument("--max-delegations", type=int, default=12)
    f.add_argument("--max-cost-usd", type=float, default=5.0)
    f.add_argument("--max-wall-s", type=float, default=3 * 3600)
    f.add_argument("--max-llm-calls", type=int, default=400)
    f.add_argument("--no-checkpoint", action="store_true")
    r = sub.add_parser("restore")
    r.add_argument("--checkpoint", required=True)
    r.add_argument("--refiner", default=None, help="condition; default: the checkpoint's")
    r.add_argument("--refine-at", default=None, choices=["first", "all", "none"])
    r.add_argument("--query-file", default=None, help="instruction override for the restored delegation")
    r.add_argument("--source", default=None, help="override provenance, e.g. post_hoc")
    for p in (f, r):
        p.add_argument("--label", default=None)
        p.add_argument("--runs-root", default=str(REPO / "outputs" / "runs"))
        p.add_argument("--allow-eval", action="store_true", help="Exp 2 only")
    a = ap.parse_args()

    tool_cfg = ToolConfig()
    reader = crawl4ai_status(tool_cfg.crawl4ai_endpoint) if "crawl4ai" in tool_cfg.reader_chain else None
    if "crawl4ai" in tool_cfg.reader_chain and reader is None:
        print("page-reader service is not running or not the pinned one: bash scripts/crawl4ai/ensure.sh "
              "(or set CRAWL4AI_ENDPOINT to a running instance)", file=sys.stderr)
        return 4

    if a.mode == "fresh":
        task_id = a.task_id
    else:
        task_id = json.loads((Path(a.checkpoint) / "state.json").read_text())["task_id"]
    if task_id in eval_task_ids() and not a.allow_eval:
        print(f"{task_id} is an eval task (data/splits/eval_v1.csv); refused without --allow-eval", file=sys.stderr)
        return 3

    if a.mode == "fresh":
        refiner = load_refiner(a.refiner)
        cfg = RunConfig(pool=load_pool(a.pool), refiner=refiner, orchestrator_model=a.orchestrator_model,
                        refiner_model=a.refiner_model, refine_at=a.refine_at, max_delegations=a.max_delegations,
                        budget=Limits(max_llm_calls=a.max_llm_calls, max_tool_calls=a.max_llm_calls,
                                      max_cost_usd=a.max_cost_usd, max_wall_s=a.max_wall_s),
                        checkpoint=not a.no_checkpoint, label=a.label or refiner.name)
        run_dir = new_run_dir(task_id, cfg.label, a.runs_root)
        info = Run(cfg, load_task(task_id), run_dir, tool_cfg=tool_cfg, reader_identity=reader).run_fresh()
    else:
        override = Path(a.query_file).read_text().strip() if a.query_file else None
        if override is not None and not a.source:
            print("--query-file needs --source (e.g. post_hoc)", file=sys.stderr)
            return 2
        refiner = load_refiner(a.refiner) if a.refiner else None
        label = a.label or (f"override_{a.source}" if override else (refiner.name if refiner else "restore"))
        run_dir = new_run_dir(task_id, label, a.runs_root)
        run = Run.restore(a.checkpoint, run_dir, refiner=refiner, refine_at=a.refine_at, label=label,
                          override=override, override_source=a.source, tool_cfg=tool_cfg, reader_identity=reader)
        info = run.run_restored()
    print(json.dumps({"run_dir": str(run_dir), "status": info["status"], "final_answer": info.get("final_answer"),
                      "cost_usd": info.get("counters", {}).get("cost_usd")}))
    return 5 if info["status"] == "error_infra" else 0


if __name__ == "__main__":
    sys.exit(main())
