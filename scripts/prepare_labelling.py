#!/usr/bin/env python
"""Prepare a session for trace labelling: transcripts, an index, and outcomes (no ground-truth content).

  python scripts/prepare_labelling.py <session-dir> [--scores <session>/scores.csv]

Writes:
  <session>/transcripts/<run>.md   from render_trace.py; <run> = <task8>_<label> (e.g. 4d51c4bf_base_r0)
  <session>/transcripts/index.txt  <run> <tab> <run dir>
  <session>/labels/outcomes.csv    run, task_id, label, status, outcome (correct | wrong | <status>)
The outcome comes from the scores file (run `score_runs.py` first). Labellers get only these files and the run
dirs, never the scores file or the dataset.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from render_trace import render  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--scores", default=None)
    a = ap.parse_args()
    sess = Path(a.session)
    scores = {}
    with open(a.scores or sess / "scores.csv") as f:
        for r in csv.DictReader(f):
            if r.get("run_dir"):
                scores[str(Path(r["run_dir"]).resolve())] = r
    tdir, ldir = sess / "transcripts", sess / "labels"
    tdir.mkdir(exist_ok=True)
    ldir.mkdir(exist_ok=True)
    index, rows = [], []
    for rj in sorted((sess / "runs").glob("*/*/run.json")):
        rd = rj.parent
        info = json.loads(rj.read_text())
        name = f"{info['task_id'][:8]}_{info.get('label')}"
        (tdir / f"{name}.md").write_text(render(rd, 60000))
        index.append(f"{name}\t{rd.resolve()}")
        s = scores.get(str(rd.resolve()), {})
        status = info.get("status")
        outcome = ("correct" if s.get("correct") == "True" else "wrong") if status == "ok" else status
        rows.append({"run": name, "task_id": info["task_id"], "label": info.get("label"), "status": status,
                     "outcome": outcome})
    (tdir / "index.txt").write_text("\n".join(index) + "\n")
    with open(ldir / "outcomes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run", "task_id", "label", "status", "outcome"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} runs -> {tdir}, {ldir / 'outcomes.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
