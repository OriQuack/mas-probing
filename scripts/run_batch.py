#!/usr/bin/env python
"""Run fresh runs for a task list (several reps) in parallel, each in its own process, into one session dir.

  python scripts/run_batch.py --tasks data/splits/executor_selection_v1.csv --reps 2 --pool role_routing \
      --refiner A_none --session outputs/sessions/base-<stamp> [--parallel 4] [--session-cost-usd 20]

Session dir: planned.csv (task_id,label: every planned run, for scoring missing runs as wrong), batch.jsonl
(one line per finished run: exit code, run dir, status, answer, cost), runs/<task_id>/<stamp>_<label>/, logs/.
Labels are <label-prefix>_r<rep>. Order: rep-major (all tasks of r0, then r1, ...), so a stopped batch still
covers whole reps. New runs are not started once the session's spend reaches --session-cost-usd.
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True, help="CSV with a task_id column")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--rep-offset", type=int, default=0)
    ap.add_argument("--pool", default="role_routing")
    ap.add_argument("--refiner", default="A_none")
    ap.add_argument("--label-prefix", default="base")
    ap.add_argument("--session", default=None)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--session-cost-usd", type=float, default=20.0)
    ap.add_argument("--max-cost-usd", type=float, default=5.0, help="per run")
    ap.add_argument("--max-wall-s", type=float, default=3600.0, help="per run")
    ap.add_argument("--only", nargs="*", default=None, help="task id prefixes to keep")
    a = ap.parse_args()

    with open(a.tasks) as f:
        tasks = [r["task_id"] for r in csv.DictReader(f)]
    if a.only:
        tasks = [t for t in tasks if any(t.startswith(p) for p in a.only)]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session = Path(a.session or REPO / "outputs" / "sessions" / f"{a.label_prefix}-{stamp}")
    (session / "logs").mkdir(parents=True, exist_ok=True)
    plan = [(t, f"{a.label_prefix}_r{r}") for r in range(a.rep_offset, a.rep_offset + a.reps) for t in tasks]
    with open(session / "planned.csv", "a", newline="") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["task_id", "label"])
        w.writerows(plan)
    (session / "batch_args.json").write_text(json.dumps(vars(a), indent=1))
    # provenance while the repo has no commits (run.json's git_commit is then empty): the code as it ran
    subprocess.run(["tar", "czf", str(session / "code_snapshot.tar.gz"), "--exclude=__pycache__", "src", "configs",
                    "scripts", "pyproject.toml"], cwd=REPO, check=False)

    lock = threading.Lock()
    spent = {"usd": 0.0}

    def one(item):
        task_id, label = item
        with lock:
            if spent["usd"] >= a.session_cost_usd:
                rec = {"task_id": task_id, "label": label, "skipped": "session_cost_cap"}
                with open(session / "batch.jsonl", "a") as f:
                    f.write(json.dumps(rec) + "\n")
                return rec
        cmd = [sys.executable, "-u", str(REPO / "scripts" / "run_task.py"), "fresh", "--task-id", task_id,
               "--pool", a.pool, "--refiner", a.refiner, "--label", label, "--runs-root", str(session / "runs"),
               "--max-cost-usd", str(a.max_cost_usd), "--max-wall-s", str(a.max_wall_s)]
        log = session / "logs" / f"{task_id[:8]}_{label}"
        with open(f"{log}.out", "w") as out, open(f"{log}.err", "w") as err:
            try:  # run_task.py has its own hard deadline; this is the backstop if the process itself hangs
                rc = subprocess.run(cmd, stdout=out, stderr=err, cwd=REPO, timeout=a.max_wall_s + 600).returncode
            except subprocess.TimeoutExpired:
                rc = "killed_timeout"
        rec = {"task_id": task_id, "label": label, "exit": rc}
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
