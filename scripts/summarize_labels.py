#!/usr/bin/env python
"""Compile a session's trace labels (labels/<run>.json) into labels/labels.csv and a per-task overview.

  python scripts/summarize_labels.py <session-dir>

Reads only labels, outcomes and run.json files (no ground truth). Prints one line per task: outcomes over reps,
primary categories, delegation relatedness, whether a better instruction would plausibly help, the number of
delegations per rep, and contamination.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

FIELDS = ["run", "task", "outcome", "category", "secondary", "implementation_induced", "delegation_related",
          "would_a_better_instruction_help", "fmd_index", "fmd_is_d0", "fmd_flawed", "n_delegations",
          "contamination", "confidence", "first_error"]


def main(sess: Path) -> int:
    ldir = sess / "labels"
    outcomes = {}
    if (ldir / "outcomes.csv").exists():
        with open(ldir / "outcomes.csv") as f:
            outcomes = {r["run"]: r["outcome"] for r in csv.DictReader(f)}
    rows = []
    for p in sorted(ldir.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            print(f"invalid JSON: {p.name}: {e}", file=sys.stderr)
            continue
        fmd = d.get("first_meaningful_delegation") or {}
        fe = d.get("framework_events") or {}
        rows.append({
            "run": d.get("run", p.stem), "task": (d.get("task_id") or p.stem)[:8],
            "outcome": d.get("outcome") or outcomes.get(p.stem), "category": d.get("category"),
            "secondary": ";".join(d.get("secondary") or []), "implementation_induced": d.get("implementation_induced"),
            "delegation_related": d.get("delegation_related"),
            "would_a_better_instruction_help": d.get("would_a_better_instruction_help"),
            "fmd_index": fmd.get("index"), "fmd_is_d0": fmd.get("is_d0"), "fmd_flawed": fmd.get("flawed"),
            "n_delegations": fe.get("n_delegations"), "contamination": d.get("contamination"),
            "confidence": d.get("confidence"), "first_error": (d.get("first_error") or "")[:300]})
    with open(ldir / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    by = defaultdict(list)
    for r in rows:
        by[r["task"]].append(r)
    for t, rs in sorted(by.items()):
        rs.sort(key=lambda r: r["run"])
        oc = "".join("✓" if r["outcome"] == "correct" else "✗" for r in rs)
        print(f"{t} {oc:4s} cat={[r['category'] for r in rs]} deleg_rel={[r['delegation_related'] for r in rs]} "
              f"better_instr={[r['would_a_better_instruction_help'] for r in rs]} "
              f"n_deleg={[r['n_delegations'] for r in rs]} contam={[r['contamination'] for r in rs]}")
    print(f"{len(rows)} labels -> {ldir / 'labels.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
