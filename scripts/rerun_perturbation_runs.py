#!/usr/bin/env python
"""Rerun named fixed-worker runs of a perturbation-consistency experiment after a harness fix.

  python scripts/rerun_perturbation_runs.py EXPERIMENT linear_hard_21/fixed_luna-high_r2 ... --reason "..." \
      [--env-file .env]

Each old run directory moves to runs/<qid>/superseded/<run> (kept as evidence; the analysis reads only direct
children of runs/<qid>), the run is redone from scratch with the experiment's settings, and RERUNS.md and batch.jsonl
record the rerun with its reason and the current git commit. Only fixed runs: a routed run depends on its probes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.data import longcot  # noqa: E402
from perturbation_consistency.longcot_nodes import parse_chain  # noqa: E402
from perturbation_consistency.runner import Settings, run_pipeline  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", type=Path)
    ap.add_argument("runs", nargs="+", help="<question_id>/fixed_<worker>_r<rep>")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--env-file", type=Path, default=REPO / ".env")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(args.env_file)
    exp = args.experiment
    manifest = json.loads((exp / "manifest.json").read_text())
    prompts = {q.question_id: q.prompt for q in longcot.load_questions("math", manifest["dataset"]["difficulty"])}
    s = Settings(workers=tuple(manifest["workers"]), n_variants=manifest["n_variants"],
                 fixed_reps=manifest["fixed_reps"], run_cost_usd=manifest["run_cost_usd"],
                 probe_depth=manifest.get("probe_depth", 1))
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    for name in args.runs:
        qid, run = name.split("/")
        m = re.fullmatch(r"fixed_(.+)_r(\d+)", run)
        if not m or m.group(1) not in s.workers:
            sys.exit(f"{name}: only fixed_<worker>_r<rep> runs can be rerun")
        old = exp / "runs" / qid / run
        if not old.exists():
            sys.exit(f"{old} does not exist")
        dest = exp / "runs" / qid / "superseded" / run
        dest.parent.mkdir(exist_ok=True)
        if dest.exists():
            sys.exit(f"{dest} already exists")
        old.rename(dest)
        rec = run_pipeline(parse_chain(qid, prompts[qid]), m.group(1), old, s, arm=f"fixed_{m.group(1)}",
                           rep=int(m.group(2)))
        line = {"question_id": qid, "arm": f"fixed_{m.group(1)}", "worker": m.group(1), "rep": int(m.group(2)),
                "status": rec["status"], "cost_usd": rec["cost_usd"], "rerun": True, "reason": args.reason,
                "git_commit": commit}
        with (exp / "batch.jsonl").open("a") as f:
            f.write(json.dumps(line) + "\n")
        with (exp / "RERUNS.md").open("a") as f:
            f.write(f"- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {name}: {args.reason} "
                    f"(commit {commit[:7]}; old run in runs/{qid}/superseded/{run}; new status {rec['status']}, "
                    f"${rec['cost_usd']:.4f})\n")
        print(name, rec["status"], f"${rec['cost_usd']:.4f}", flush=True)


if __name__ == "__main__":
    main()
