#!/usr/bin/env python
"""Render readable prompt examples using the runtime functions; no model or tool calls."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot import prompts
from minpilot.config import load_pool
from minpilot.data.gaia import ANSWER_FORMAT
from minpilot.prompts.reader import PROMPT

COMPONENTS = ("orchestrator", "worker", "probe", "self-review", "analysis", "verification", "rewrite", "reader")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("all", *COMPONENTS), default="all")
    parser.add_argument("--pool", default="multi")
    parser.add_argument("--role", help="role ID; default: the first configured role")
    parser.add_argument("--task", default="How many unique orders were placed in 2025?")
    parser.add_argument("--instruction", default="Count unique order IDs in attachments/orders.csv for 2025.")
    parser.add_argument("--context", default="")
    parser.add_argument("--probe-tools", action="store_true")
    parser.add_argument("--source", choices=("probe", "self_review"), default="probe")
    args = parser.parse_args()
    pool = load_pool(args.pool)
    role = pool.roles[args.role] if args.role else next(iter(pool.roles.values()))
    worker = pool.workers[role.executor]
    roles = [{"id": r.id, "description": r.description, "tools": list(pool.role_tools(r.id))}
             for r in pool.roles.values()]
    target = {"role": "the worker" if len(roles) == 1 else role.id,
              "description": role.description, "tools": list(worker.tools), "system_prompt": worker.system_prompt}
    probe = prompts.probe_instruction(args.instruction, args.probe_tools, 3)
    responses = [{"id": "r1", "who": "respondent 1",
                  "text": "understanding: Count unique orders in 2025.\nassumptions:\nrisks:\nplan:\n- Read and count."}]
    examples = {
        "orchestrator": [("System", prompts.orchestrator_system(roles, 12, ANSWER_FORMAT)),
                         ("Task", prompts.orchestrator_task_message(args.task))],
        "worker": [("System", prompts.worker_system(worker.system_prompt, worker.tools)),
                   ("Request", prompts.worker_request(args.task, args.instruction, context=args.context,
                                                      tool_limit=worker.max_tool_calls))],
        "probe": [("System", prompts.probe_system(worker.system_prompt, worker.tools)),
                  ("Request", prompts.worker_request(args.task, probe, context=args.context, kind="probe"))],
        "self-review": [("Review turn", prompts.simulate_request(args.task, args.instruction, target, args.context))],
        "analysis": [("Review turn", prompts.analyze_request(target, responses, args.source, 2, roles, 0,
                                                            bool(args.context.strip()), args.probe_tools))],
        "verification": [("Instruction", prompts.verify_instruction("Check whether order IDs repeat across rows."))],
        "rewrite": [("Review turn", prompts.rewrite_request([], target, bool(args.context.strip())))],
        "reader": [("Request", PROMPT.format(source="Example page content.", question="What does it say?"))],
    }
    print(f"Example inputs only; execution prompts {prompts.PROMPTS_VERSION}, refiner prompts "
          f"{prompts.REFINER_PROMPTS_VERSION}. Review turns follow a private copy of the orchestrator conversation.")
    for component in COMPONENTS if args.component == "all" else [args.component]:
        for label, value in examples[component]:
            print(f"\n## {component}: {label}\n\n{value}")


if __name__ == "__main__":
    main()
