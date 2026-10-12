#!/usr/bin/env python
"""Run many runs in parallel, each in its own process, into one session dir: fresh runs for a task list, or
restores of checkpoints under several conditions (paired comparisons).

  python scripts/run_batch.py --tasks data/splits/executor_selection_v1.csv --reps 3 --pool multi \
      --condition direct_execution --experiment outputs/experiments/<date>_baseline [--parallel 4] [--session-cost-usd 20]
  python scripts/run_batch.py --checkpoints cks.txt --conditions direct_execution adaptive_probe --reps 3 \
      --experiment outputs/experiments/<date>_probe-comparison          # cks.txt: one checkpoint dir per line

Session dir: planned.csv (every planned run with its arm: task_id, label, mode, pool, condition, checkpoint,
override_source; score_runs.py counts a planned run without a run.json as a failure **of that arm**, decision E3),
batch.jsonl (one line per finished run: exit code, run dir, status, answer, cost), runs/<task_id>/<stamp>_<label>/,
logs/. Labels: fresh <label-prefix>_r<rep>; restore <condition>_r<rep>. Order: rep-major (all of r0, then r1, ...),
so a stopped batch still covers whole reps; in restores the condition order rotates per (rep, checkpoint), so no
condition always runs first on a warm cache. New runs are not started once the session's spend reaches
--session-cost-usd.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.config import load_pool, load_condition  # noqa: E402
from minpilot import prompts
from minpilot.artifacts import experiment_manifest
from minpilot.harness import STATE_FORMAT

PLAN_COLUMNS = ["task_id", "label", "mode", "pool", "condition", "checkpoint", "override_source"]


def fresh_plan(a) -> list[dict]:
    with open(a.tasks) as f:
        tasks = [r["task_id"] for r in csv.DictReader(f)]
    if a.only:
        tasks = [t for t in tasks if any(t.startswith(p) for p in a.only)]
    pool, cond = load_pool(a.pool).name, load_condition(a.condition).name
    return [{"task_id": t, "label": f"{a.label_prefix}_r{r}", "mode": "fresh", "pool": pool, "condition": cond,
             "checkpoint": "", "override_source": "", "_condition": a.condition}
            for r in range(a.rep_offset, a.rep_offset + a.reps) for t in tasks]


def restore_plan(a) -> list[dict]:
    cks = [str(Path(x.strip()).resolve()) for x in Path(a.checkpoints).read_text().splitlines() if x.strip()]
    conditions = [(r, load_condition(r).name) for r in a.conditions]
    plan = []
    for rep in range(a.rep_offset, a.rep_offset + a.reps):
        for i, ck in enumerate(cks):
            state = json.loads((Path(ck) / "state.json").read_text())
            if state.get("format") != STATE_FORMAT:
                raise ValueError("historical checkpoint requires its code snapshot")
            if a.only and not any(state["task_id"].startswith(p) for p in a.only):
                continue
            k = (rep + i) % len(conditions)
            for ref, cond in conditions[k:] + conditions[:k]:
                plan.append({"task_id": state["task_id"], "label": f"{cond}_r{rep}", "mode": "restore",
                             "pool": state["config"]["pool"]["name"], "condition": cond, "checkpoint": ck,
                             "override_source": "", "_condition": ref})
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--tasks", help="fresh runs: CSV with a task_id column")
    src.add_argument("--checkpoints", help="restores: file with one checkpoint dir per line")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--rep-offset", type=int, default=0)
    ap.add_argument("--pool", default="multi", help="fresh runs only (restores keep the checkpoint's)")
    ap.add_argument("--condition", default="direct_execution", choices=["direct_execution", "adaptive_probe"], help="fresh runs")
    ap.add_argument("--conditions", nargs="+", default=None, choices=["direct_execution", "adaptive_probe"], help="restores: the conditions to compare")
    ap.add_argument("--label-prefix", default="base")
    ap.add_argument("--experiment", "--session", dest="session", default=None,
                    help="experiment directory (--session is the existing CLI spelling)")
    ap.add_argument("--purpose", default=None, help="plain-language description saved in manifest.json")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--session-cost-usd", type=float, default=20.0)
    ap.add_argument("--max-cost-usd", type=float, default=5.0, help="per run (fresh runs)")
    ap.add_argument("--max-wall-s", type=float, default=10800.0, help="per run (fresh runs)")
    ap.add_argument("--only", nargs="*", default=None, help="task id prefixes to keep")
    a = ap.parse_args()
    if a.checkpoints and not a.conditions:
        ap.error("--checkpoints needs --conditions")

    plan = fresh_plan(a) if a.tasks else restore_plan(a)
    conditions = sorted({item["condition"] for item in plan})
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M%S%fZ")
    purpose = a.purpose or f"{'Fresh runs' if a.tasks else 'Paired restores'}: {', '.join(conditions)}"
    slug = re.sub(r"[^\w-]+", "-", purpose.lower()).strip("-")[:100] or "experiment"
    session = Path(a.session or REPO / "outputs" / "experiments" / f"{stamp}_{slug}")
    manifest = experiment_manifest(
        purpose=purpose,
        run_roots=["runs"], created_at=stamp, conditions=conditions, planned_run_count=len(plan),
        execution_prompt_versions=[prompts.PROMPTS_VERSION],
        refiner_prompt_versions=[prompts.REFINER_PROMPTS_VERSION],
        evaluator_prompt_versions=[prompts.EVALUATOR_VERSION],
        arguments=vars(a), condition_configs={name: load_condition(name).to_dict()
                                          for name in (a.conditions or [a.condition])})
    manifest_path = session / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous.get("historical_records_immutable"):
            raise ValueError("retained historical evidence is immutable; use a new experiment directory")
        if (previous.get("condition_configs") != manifest["condition_configs"] or
                previous.get("execution_prompt_versions") != manifest["execution_prompt_versions"]):
            raise ValueError("experiment config changed; use a new experiment directory")
        manifest["created_at"] = previous["created_at"]
        manifest["planned_run_count"] += previous["planned_run_count"]
    else:
        previous = {}
    batch_dir = session / "batches" / stamp
    manifest["batches"] = previous.get("batches", []) + [{
        "created_at": stamp, "arguments": vars(a), "planned_run_count": len(plan),
        "snapshot": str((batch_dir / "code_snapshot.tar.gz").relative_to(session)),
    }]
    (session / "logs").mkdir(parents=True, exist_ok=True)
    planned = session / "planned.csv"
    if planned.exists() and planned.read_text().splitlines()[:1] != [",".join(PLAN_COLUMNS)]:
        print(f"{planned} has an older format; use a new session dir", file=sys.stderr)
        return 2
    with open(planned, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        if f.tell() == 0:
            w.writeheader()
        w.writerows(plan)
    (session / "batch_args.json").write_text(json.dumps(vars(a), indent=1))
    batch_dir.mkdir(parents=True, exist_ok=False)
    (batch_dir / "arguments.json").write_text(json.dumps(vars(a), indent=2) + "\n")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    # provenance in addition to run.json's git_commit (uncommitted changes): the code as it ran
    subprocess.run(["tar", "czf", str(batch_dir / "code_snapshot.tar.gz"), "--exclude=__pycache__", "src", "configs",
                    "scripts", "pyproject.toml"], cwd=REPO, check=False)

    lock = threading.Lock()
    spent = {"usd": 0.0}
    max_wall = a.max_wall_s

    def one(item: dict):
        task_id, label = item["task_id"], item["label"]
        with lock:
            if spent["usd"] >= a.session_cost_usd:
                rec = {"task_id": task_id, "label": label, "checkpoint": item["checkpoint"],
                       "skipped": "session_cost_cap"}
                with open(session / "batch.jsonl", "a") as f:
                    f.write(json.dumps(rec) + "\n")
                return rec
        script = [sys.executable, "-u", str(REPO / "scripts" / "run_task.py")]
        if item["mode"] == "fresh":
            cmd = script + ["fresh", "--task-id", task_id, "--pool", a.pool, "--condition", item["_condition"],
                            "--max-cost-usd", str(a.max_cost_usd), "--max-wall-s", str(a.max_wall_s)]
        else:  # budgets come from the checkpoint
            cmd = script + ["restore", "--checkpoint", item["checkpoint"], "--condition", item["_condition"]]
        cmd += ["--label", label, "--runs-root", str(session / "runs")]
        tag = f"{task_id[:8]}_{label}" + (f"_{Path(item['checkpoint']).parent.parent.name[:22]}" if item["checkpoint"]
                                           else "")
        log = session / "logs" / tag
        with open(f"{log}.out", "w") as out, open(f"{log}.err", "w") as err:
            try:  # run_task.py has its own hard deadline; this is the backstop if the process itself hangs
                rc = subprocess.run(cmd, stdout=out, stderr=err, cwd=REPO, timeout=max_wall + 600).returncode
            except subprocess.TimeoutExpired:
                rc = "killed_timeout"
        rec = {"task_id": task_id, "label": label, "checkpoint": item["checkpoint"], "exit": rc}
        try:
            rec.update(json.loads(Path(f"{log}.out").read_text().strip().splitlines()[-1]))
        except Exception:
            rec["note"] = "no result line (see logs)"
        with lock:
            spent["usd"] += float(rec.get("cost_usd") or 0.0)
            with open(session / "batch.jsonl", "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(json.dumps(rec, ensure_ascii=False)[:300], flush=True)
        return rec

    with ThreadPoolExecutor(a.parallel) as ex:
        recs = list(ex.map(one, plan))
    bad = [r for r in recs if r.get("exit") not in (0, None) or r.get("skipped")]
    print(f"session {session}: {len(recs)} planned, {len(bad)} not clean, spent ${spent['usd']:.4f}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
