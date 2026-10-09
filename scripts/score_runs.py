#!/usr/bin/env python
"""Score run directories against GAIA ground truth (a separate step: ground truth never enters a run dir).

  python scripts/score_runs.py [RUN_DIR_OR_ROOT ...] [--out outputs/scores/scores.csv] [--expected planned.csv]
                               [--exclude runs.txt] [--compare A_none C_probe [--compare A_none B_self_review]]

Primary metric: `correct` on the extracted answer (eval/answer.py, version recorded); `correct_raw` alongside.
Runs with status other than ok count as wrong. `--expected` is a session's planned.csv (run_batch.py): every
planned run without a run.json is added as `missing` (wrong) **in its own arm** (mode, pool, condition,
checkpoint from the plan; decision E3), so it stays in that arm's denominator and in paired comparisons. A plan
row matches a run by (task_id, label, checkpoint). Old plans with only task_id,label take mode/pool/condition from
the session's batch_args.json (fresh batches). `--exclude` lists run dirs to drop (e.g. contaminated runs), one
per line: they leave the denominator on purpose and are **not** re-added as missing.

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


def run_key(task_id: str, label, checkpoint) -> tuple:
    return (task_id, label or "", str(Path(checkpoint).resolve()) if checkpoint else "")


def load_plan(path: Path) -> list[dict]:
    """Planned runs with their arms. Old plans (task_id,label only) get the arm from batch_args.json (fresh)."""
    plan = pd.read_csv(path, dtype=str, keep_default_na=False).to_dict("records")
    if plan and "condition" not in plan[0]:
        args_file = Path(path).parent / "batch_args.json"
        if not args_file.exists():
            raise SystemExit(f"{path}: no arm columns and no batch_args.json; cannot place missing runs in an arm")
        from minpilot.config import load_pool, load_refiner

        args = json.loads(args_file.read_text())
        arm = {"mode": "fresh", "pool": load_pool(args["pool"]).name,
               "condition": load_refiner(args["refiner"]).name, "checkpoint": "", "override_source": ""}
        plan = [{**arm, **p} for p in plan]
    return plan


def missing_rows(rows: list[dict], plan: list[dict], excluded: set[tuple]) -> list[dict]:
    """Planned runs with no scored run and not deliberately excluded, as failures of their own arm."""
    have = {run_key(r["task_id"], r.get("label"), r.get("checkpoint")) for r in rows}
    out = []
    for p in plan:
        key = run_key(p["task_id"], p.get("label"), p.get("checkpoint"))
        if key in have or key in excluded:
            continue
        ck = key[2] or None
        out.append({"task_id": p["task_id"], "label": p.get("label"), "status": "missing", "mode": p.get("mode"),
                    "pool": p.get("pool") or None, "condition": p.get("condition") or None, "checkpoint": ck,
                    "pair_id": ck, "override_source": p.get("override_source") or None,
                    "correct": False, "correct_raw": False})
    return out


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
    rows, excluded_keys = [], set()
    for p in map(Path, a.paths):
        for rj in ([p / "run.json"] if (p / "run.json").exists() else sorted(p.rglob("run.json"))):
            if "checkpoints" in rj.parts or "scratch" in rj.parts:
                continue
            info = json.loads(rj.read_text())
            if str(rj.parent.resolve()) in excluded:
                excluded_keys.add(run_key(info["task_id"], info.get("label"), info.get("restored_from")))
                continue
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
        miss = missing_rows(rows, load_plan(Path(a.expected)), excluded_keys)
        rows += miss
        print(f"planned runs without a run.json (scored as failures of their arm): {len(miss)}; "
              f"excluded on purpose: {len(excluded_keys)}")
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
