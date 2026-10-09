#!/usr/bin/env python
"""Score run directories against GAIA ground truth (a separate step: ground truth never enters a run dir).

  python scripts/score_runs.py [RUN_DIR_OR_ROOT ...] [--out outputs/scores/scores.csv] [--expected planned.csv]
                               [--exclude runs.txt] [--compare A_none C_probe [--compare A_none B_self_review]]

Primary metric: `correct` on the extracted answer (eval/answer.py, version recorded); `correct_raw` alongside.
Runs with status other than ok count as wrong; `--expected` (task_id,label rows) adds planned runs that have no
run.json as `missing` (also wrong). `--exclude` lists run dirs to drop (e.g. contaminated runs), one per line.

Grouping (review 2026-10-09, F6): runs are grouped by **arm** = (mode, pool, condition, override source), not
by label, so reps labelled C_r0, C_r1, ... count as one condition. Within an arm: per-task success rate over
reps, then the equal-weight mean over tasks.
- `mode=fresh` runs (recording runs) and `mode=restore` runs are separate arms: a recording run's own
  continuation is never an A rep (CLAUDE.md).
- Post-hoc overrides (Exp 1) form their own arms (`override=<source>`), never mixed with B/C.
`--compare X Y`: paired comparison of restore arms X and Y on the same checkpoints (same pool, no override):
per checkpoint the success rate over reps, per task the mean over its checkpoints, then the mean difference
Y - X over tasks with a paired task-level bootstrap 95% CI (10,000 resamples, seed 0).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]

from minpilot.data.gaia import GAIA_ROOT  # noqa: E402
from minpilot.eval.answer import EXTRACTION_VERSION, extract_final_answer  # noqa: E402
from minpilot.eval.gaia_scorer import question_scorer  # noqa: E402

REP = re.compile(r"_r(\d+)$")


def arm_of(r: dict) -> str:
    return f"{r['mode']}|{r['pool']}|{r['condition']}|override={r['override_source'] or 'none'}"


def per_task(rows: list[dict]) -> dict[str, float]:
    by = defaultdict(list)
    for r in rows:
        by[r["task_id"]].append(r["correct"])
    return {t: sum(v) / len(v) for t, v in by.items()}


def compare(df: pd.DataFrame, x: str, y: str, n_boot: int = 10_000, seed: int = 0) -> dict:
    d = df[(df["mode"] == "restore") & (df["override_source"].isna())]
    out = {}
    for pool, g in d.groupby("pool"):
        gx, gy = g[g["condition"] == x], g[g["condition"] == y]
        cks = sorted(set(gx["checkpoint"]) & set(gy["checkpoint"]))
        if not cks:
            continue
        rows = []
        for ck in cks:
            ax, ay = gx[gx["checkpoint"] == ck], gy[gy["checkpoint"] == ck]
            rows.append({"task_id": ax["task_id"].iloc[0], "x": ax["correct"].mean(), "y": ay["correct"].mean(),
                         "nx": len(ax), "ny": len(ay)})
        t = pd.DataFrame(rows).groupby("task_id")[["x", "y"]].mean()
        diff = (t["y"] - t["x"]).to_numpy()
        rng = np.random.default_rng(seed)
        boots = rng.choice(diff, size=(n_boot, len(diff)), replace=True).mean(axis=1) if len(diff) else np.array([0])
        out[pool] = {"tasks": len(t), "checkpoints": len(cks), "x": float(t["x"].mean()), "y": float(t["y"].mean()),
                     "diff": float(diff.mean()), "ci95": [float(np.percentile(boots, 2.5)),
                                                          float(np.percentile(boots, 97.5))]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=[str(REPO / "outputs" / "runs")])
    ap.add_argument("--out", default=str(REPO / "outputs" / "scores" / "scores.csv"))
    ap.add_argument("--expected", default=None)
    ap.add_argument("--exclude", default=None, help="file with run dirs to drop (one per line)")
    ap.add_argument("--compare", nargs=2, action="append", default=[], metavar=("X", "Y"))
    a = ap.parse_args()

    truth = pd.read_parquet(GAIA_ROOT / "validation" / "metadata.parquet",
                            columns=["task_id", "Final answer"]).set_index("task_id")["Final answer"].to_dict()
    excluded = set()
    if a.exclude:
        excluded = {str(Path(x.strip()).resolve()) for x in Path(a.exclude).read_text().splitlines() if x.strip()}
    rows = []
    for p in map(Path, a.paths):
        for rj in ([p / "run.json"] if (p / "run.json").exists() else sorted(p.rglob("run.json"))):
            if "checkpoints" in rj.parts or "scratch" in rj.parts or str(rj.parent.resolve()) in excluded:
                continue
            info = json.loads(rj.read_text())
            raw = info.get("final_answer")
            ans = extract_final_answer(raw)
            ok = info.get("status") == "ok"
            gt = truth[info["task_id"]]
            c = info.get("counters") or {}
            label = info.get("label") or ""
            rep = REP.search(label)
            ck = info.get("restored_from")
            rows.append({
                "run_dir": str(rj.parent), "task_id": info["task_id"], "level": info.get("level"),
                "mode": info.get("mode"), "pool": ((info.get("config") or {}).get("pool") or {}).get("name"),
                "condition": info.get("condition"), "label": label, "rep": int(rep.group(1)) if rep else None,
                "checkpoint": ck, "pair_id": ck or str(rj.parent),
                "override_source": info.get("override_source") if info.get("override") else None,
                "status": info.get("status"), "final_answer_raw": raw, "answer": ans,
                "extraction": EXTRACTION_VERSION, "correct": bool(ok and question_scorer(ans, gt)),
                "correct_raw": bool(ok and question_scorer(raw, gt)),
                "llm_usd": c.get("llm_usd", c.get("cost_usd")), "tool_usd": c.get("tool_usd"),
                "cost_usd": c.get("cost_usd"), "tool_usd_cold": c.get("tool_usd_cold"),
                "unknown_cost_calls": c.get("unknown_cost_calls"), "n_delegations": info.get("n_delegations")})
    if a.expected:
        have = {(r["task_id"], r["label"]) for r in rows}
        with open(a.expected) as f:
            for e in pd.read_csv(f).to_dict("records"):
                key = (e["task_id"], e.get("label"))
                if key not in have:
                    rows.append({"task_id": e["task_id"], "label": e.get("label"), "status": "missing",
                                 "mode": "fresh", "pool": None, "condition": None, "override_source": None,
                                 "correct": False, "correct_raw": False})
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    arms = defaultdict(list)
    for r in rows:
        arms[arm_of(r)].append(r)
    for arm, rs in sorted(arms.items()):
        pt = per_task(rs)
        print(f"{arm}: tasks={len(pt)} runs={len(rs)} acc={sum(pt.values()) / len(pt):.3f}")
    for x, y in a.compare:
        for pool, res in compare(df, x, y).items():
            print(f"compare {y} - {x} [{pool}]: tasks={res['tasks']} checkpoints={res['checkpoints']} "
                  f"{x}={res['x']:.3f} {y}={res['y']:.3f} diff={res['diff']:+.3f} "
                  f"95% CI [{res['ci95'][0]:+.3f}, {res['ci95'][1]:+.3f}]")
    print(f"{len(rows)} runs -> {out}")


if __name__ == "__main__":
    main()
