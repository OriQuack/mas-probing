#!/usr/bin/env python
"""Score run directories against GAIA ground truth (a separate step: ground truth never enters a run dir).

  python scripts/score_runs.py [RUN_DIR_OR_ROOT ...] [--out outputs/scores/scores.csv] [--expected planned.csv]

Primary metric: `correct` on the extracted answer (eval/answer.py, version recorded); `correct_raw` alongside.
Runs with status other than ok count as wrong; `--expected` (task_id[,label] rows) adds planned runs that have no
run.json as `missing` (also wrong). Aggregation per task over reps, then the equal-weight mean over tasks.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]

from minpilot.data.gaia import GAIA_ROOT  # noqa: E402
from minpilot.eval.answer import EXTRACTION_VERSION, extract_final_answer  # noqa: E402
from minpilot.eval.gaia_scorer import question_scorer  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=[str(REPO / "outputs" / "runs")])
    ap.add_argument("--out", default=str(REPO / "outputs" / "scores" / "scores.csv"))
    ap.add_argument("--expected", default=None)
    a = ap.parse_args()

    truth = pd.read_parquet(GAIA_ROOT / "validation" / "metadata.parquet",
                            columns=["task_id", "Final answer"]).set_index("task_id")["Final answer"].to_dict()
    rows = []
    for p in map(Path, a.paths):
        for rj in ([p / "run.json"] if (p / "run.json").exists() else sorted(p.rglob("run.json"))):
            info = json.loads(rj.read_text())
            raw = info.get("final_answer")
            ans = extract_final_answer(raw)
            ok = info.get("status") == "ok"
            gt = truth[info["task_id"]]
            rows.append({"run_dir": str(rj.parent), "task_id": info["task_id"], "level": info.get("level"),
                         "mode": info.get("mode"), "label": info.get("label"), "condition": info.get("condition"),
                         "restored_from": info.get("restored_from"), "status": info.get("status"),
                         "final_answer_raw": raw, "answer": ans, "extraction": EXTRACTION_VERSION,
                         "correct": bool(ok and question_scorer(ans, gt)),
                         "correct_raw": bool(ok and question_scorer(raw, gt)),
                         "cost_usd": (info.get("counters") or {}).get("cost_usd"),
                         "n_delegations": info.get("n_delegations")})
    if a.expected:
        have = {(r["task_id"], r["label"]) for r in rows}
        with open(a.expected) as f:
            for e in csv.DictReader(f):
                key = (e["task_id"], e.get("label"))
                if key not in have:
                    rows.append({"task_id": e["task_id"], "label": e.get("label"), "status": "missing",
                                 "correct": False, "correct_raw": False})
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r.get("label")][r["task_id"]].append(r["correct"])
    for label, tasks in sorted(by.items(), key=lambda x: str(x[0])):
        per_task = [sum(v) / len(v) for v in tasks.values()]
        print(f"{label}: tasks={len(tasks)} runs={sum(map(len, tasks.values()))} "
              f"acc={sum(per_task) / len(per_task):.3f}")
    print(f"{len(rows)} runs -> {out}")


if __name__ == "__main__":
    main()
