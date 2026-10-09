#!/usr/bin/env python
"""Run many runs in parallel, each in its own process, into one session dir: fresh runs for a task list, or
restores of checkpoints under several conditions (paired comparisons).

  python scripts/run_batch.py --tasks data/splits/executor_selection_v1.csv --reps 3 --pool single \
      --refiner A_none --session outputs/sessions/base-<stamp> [--parallel 4] [--session-cost-usd 20]
  python scripts/run_batch.py --checkpoints cks.txt --refiners A_none B_self_review C_probe --reps 3 \
      --session outputs/sessions/exp-<stamp>          # cks.txt: one checkpoint dir per line

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
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.config import load_pool, load_refiner  # noqa: E402

PLAN_COLUMNS = ["task_id", "label", "mode", "pool", "condition", "checkpoint", "override_source"]


def fresh_plan(a) -> list[dict]:
    with open(a.tasks) as f:
        tasks = [r["task_id"] for r in csv.DictReader(f)]
    if a.only:
        tasks = [t for t in tasks if any(t.startswith(p) for p in a.only)]
    pool, cond = load_pool(a.pool).name, load_refiner(a.refiner).name
    return [{"task_id": t, "label": f"{a.label_prefix}_r{r}", "mode": "fresh", "pool": pool, "condition": cond,
             "checkpoint": "", "override_source": "", "_refiner": a.refiner}
            for r in range(a.rep_offset, a.rep_offset + a.reps) for t in tasks]


def restore_plan(a) -> list[dict]:
    cks = [str(Path(x.strip()).resolve()) for x in Path(a.checkpoints).read_text().splitlines() if x.strip()]
    refiners = [(r, load_refiner(r).name) for r in a.refiners]
    plan = []
    for rep in range(a.rep_offset, a.rep_offset + a.reps):
        for i, ck in enumerate(cks):
            state = json.loads((Path(ck) / "state.json").read_text())
            if a.only and not any(state["task_id"].startswith(p) for p in a.only):
                continue
            k = (rep + i) % len(refiners)
            for ref, cond in refiners[k:] + refiners[:k]:
                plan.append({"task_id": state["task_id"], "label": f"{cond}_r{rep}", "mode": "restore",
                             "pool": state["config"]["pool"]["name"], "condition": cond, "checkpoint": ck,
                             "override_source": "", "_refiner": ref})
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--tasks", help="fresh runs: CSV with a task_id column")
    src.add_argument("--checkpoints", help="restores: file with one checkpoint dir per line")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--rep-offset", type=int, default=0)
    ap.add_argument("--pool", default="single", help="fresh runs only (restores keep the checkpoint's)")
    ap.add_argument("--refiner", default="A_none", help="fresh runs")
    ap.add_argument("--refiners", nargs="+", default=None, help="restores: the conditions to compare")
    ap.add_argument("--label-prefix", default="base")
    ap.add_argument("--session", default=None)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--session-cost-usd", type=float, default=20.0)
    ap.add_argument("--max-cost-usd", type=float, default=5.0, help="per run (fresh runs)")
    ap.add_argument("--max-wall-s", type=float, default=3600.0, help="per run (fresh runs)")
    ap.add_argument("--only", nargs="*", default=None, help="task id prefixes to keep")
    a = ap.parse_args()
    if a.checkpoints and not a.refiners:
        ap.error("--checkpoints needs --refiners")

    plan = fresh_plan(a) if a.tasks else restore_plan(a)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session = Path(a.session or REPO / "outputs" / "sessions" / f"{a.label_prefix}-{stamp}")
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
    # provenance in addition to run.json's git_commit (uncommitted changes): the code as it ran
    subprocess.run(["tar", "czf", str(session / "code_snapshot.tar.gz"), "--exclude=__pycache__", "src", "configs",
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
            cmd = script + ["fresh", "--task-id", task_id, "--pool", a.pool, "--refiner", item["_refiner"],
                            "--max-cost-usd", str(a.max_cost_usd), "--max-wall-s", str(a.max_wall_s)]
        else:  # budgets come from the checkpoint
            cmd = script + ["restore", "--checkpoint", item["checkpoint"], "--refiner", item["_refiner"]]
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
