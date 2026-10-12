"""Run a current condition fresh or restore a current-version checkpoint."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")

from minpilot.config import RunConfig, load_pool, load_condition  # noqa: E402
from minpilot.data.gaia import load_task  # noqa: E402
from minpilot.harness import Run, new_run_dir, STATE_FORMAT  # noqa: E402
from minpilot.runtime.trace import Limits  # noqa: E402
from minpilot.tools.backends import crawl4ai_status  # noqa: E402
from minpilot.tools.config import ToolConfig  # noqa: E402


def eval_task_ids() -> set[str]:
    import csv

    with open(REPO / "data" / "splits" / "eval_v1.csv") as f:
        return {r["task_id"] for r in csv.DictReader(f)}


HARD_DEADLINE_GRACE_S = 120


def start_watchdog(run: Run, wall_s: float | None) -> None:
    """Hard deadline: the wall budget is checked before every model and tool call, but a call stuck inside a
    library can overrun it. At budget + grace the process records `budget_exceeded` and exits."""
    if not wall_s:
        return

    def fire():
        try:
            run.trace.event("budget_exceeded", scope="run", what="hard_deadline")
            run._finish("budget_exceeded", error=f"hard deadline: wall budget + {HARD_DEADLINE_GRACE_S} s")
            print(json.dumps({"run_dir": str(run.run_dir), "status": "budget_exceeded", "final_answer": None,
                              "cost_usd": run.trace.run_scope.cost_usd}), flush=True)
        finally:
            os._exit(0)

    t = threading.Timer(max(wall_s, 0) + HARD_DEADLINE_GRACE_S, fire)
    t.daemon = True
    t.start()


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    f = sub.add_parser("fresh")
    f.add_argument("--task-id", required=True)
    f.add_argument("--pool", default="multi")
    f.add_argument("--condition", default="direct_execution", choices=["direct_execution", "adaptive_probe"])
    f.add_argument("--orchestrator-model", default="luna-high", choices=["luna-high"])
    f.add_argument("--refiner-model", default="luna-high", choices=["luna-high"],
                   help="Instruction rewrite after each valid probe evaluation, before next action selection")
    f.add_argument("--max-delegations", type=int, default=12)
    f.add_argument("--max-cost-usd", type=float, default=5.0)
    f.add_argument("--max-wall-s", type=float, default=3 * 3600)
    f.add_argument("--max-llm-calls", type=int, default=400)
    f.add_argument("--max-tool-calls", type=int, default=400)
    f.add_argument("--no-checkpoint", action="store_true")
    f.add_argument("--reader-chain", default="crawl4ai,direct,playwright",
                   help="page readers in fallback order; without crawl4ai the service is not required (recorded "
                        "in the run's tool settings; restores use the checkpoint's chain)")
    r = sub.add_parser("restore")
    r.add_argument("--checkpoint", required=True)
    r.add_argument("--condition", default=None, choices=["direct_execution", "adaptive_probe"])
    for p in (f, r):
        p.add_argument("--label", default=None)
        p.add_argument("--runs-root", default=str(REPO / "outputs" / "runs"))
        p.add_argument("--allow-eval", action="store_true", help="Exp 2 only")
    a = ap.parse_args()
    if a.mode == "restore":
        state = json.loads((Path(a.checkpoint) / "state.json").read_text())
        if state.get("format") != STATE_FORMAT:
            ap.error("historical checkpoint requires its code snapshot; no conversion supported")

    if a.mode == "fresh":
        chain = tuple(x.strip() for x in a.reader_chain.split(",") if x.strip())
    else:  # a restore must use the checkpoint's reader chain (restores refuse other tool settings)
        chain = tuple(json.loads((Path(a.checkpoint) / "state.json").read_text())["tools"]["reader_chain"])
    tool_cfg = ToolConfig(reader_chain=chain)
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
        condition = load_condition(a.condition)
        cfg = RunConfig(pool=load_pool(a.pool), condition=condition, orchestrator_model=a.orchestrator_model,
                        refiner_model=a.refiner_model, max_delegations=a.max_delegations,
                        budget=Limits(max_llm_calls=a.max_llm_calls, max_tool_calls=a.max_tool_calls,
                                      max_cost_usd=a.max_cost_usd, max_wall_s=a.max_wall_s),
                        checkpoint=not a.no_checkpoint, label=a.label or condition.name)
        run_dir = new_run_dir(task_id, cfg.label, a.runs_root)
        run = Run(cfg, load_task(task_id), run_dir, tool_cfg=tool_cfg, reader_identity=reader)
        start_watchdog(run, run.trace.run_scope.remaining_wall_s())
        info = run.run_fresh()
    else:
        condition = load_condition(a.condition) if a.condition else None
        label = a.label or (condition.name if condition else "restore")
        run_dir = new_run_dir(task_id, label, a.runs_root)
        run = Run.restore(a.checkpoint, run_dir, condition=condition, label=label,
                          tool_cfg=tool_cfg, reader_identity=reader)
        start_watchdog(run, run.trace.run_scope.remaining_wall_s())
        info = run.run_restored()
    print(json.dumps({"run_dir": str(run_dir), "status": info["status"], "final_answer": info.get("final_answer"),
                      "cost_usd": info.get("counters", {}).get("cost_usd")}))
    return 5 if info["status"] == "error_infra" else 0


if __name__ == "__main__":
    sys.exit(main())
