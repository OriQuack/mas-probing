#!/usr/bin/env python
"""Score run directories against GAIA ground truth (a separate step: ground truth never enters a run dir).

  python scripts/score_runs.py [RUN_DIR_OR_ROOT ...] [--out outputs/scores/scores.csv] [--expected planned.csv]
                               [--exclude runs.txt] [--compare direct_execution adaptive_probe [--compare ...]]

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
- `mode=fresh` runs (recording runs) and `mode=restore` runs are separate arms. When a recording run's
  continuation serves as the baseline (CLAUDE.md), compare it with restore arms outside `--compare`.
- Post-hoc overrides (Exp 1) form their own arms (`override=<source>`), never mixed with B/C.
`--compare X Y`: paired comparison of restore arms X and Y on the same checkpoints (same pool, no override):
per checkpoint the success rate over reps, per task the mean over its checkpoints, then the mean difference
Y - X over tasks with a paired task-level bootstrap 95% CI (10,000 resamples, seed 0), and the same paired
mean difference of cost (`after_ck_usd`) and of refiner cost (`refine_usd`).

Cost columns (decision E7: conditions are compared on cost too): `cost_usd` is the run's total; a restore carries
the checkpoint's counters, so it includes the recording run's cost up to the checkpoint. `after_ck_usd` = cost
after the checkpoint (= `cost_usd` for fresh runs); `refine_usd` = LLM + tool cost of the refiner's stages
(`refine.*`: predictions, probes, analysis, checks, rewrite). Each arm prints its mean of both.
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
from minpilot.artifacts import find_run_records, resolve_artifact_path
from minpilot.eval.answer import EXTRACTION_VERSION, extract_final_answer  # noqa: E402
from minpilot.eval.gaia_scorer import question_scorer  # noqa: E402

REP = re.compile(r"_r(\d+)$")


def run_key(task_id: str, label, checkpoint) -> tuple:
    return (task_id, label or "", str(resolve_artifact_path(checkpoint)) if checkpoint else "")


def load_plan(path: Path) -> list[dict]:
    """Planned runs with their arms. Old plans (task_id,label only) get the arm from batch_args.json (fresh)."""
    plan = pd.read_csv(path, dtype=str, keep_default_na=False).to_dict("records")
    if plan and "condition" not in plan[0]:
        args_file = Path(path).parent / "batch_args.json"
        if not args_file.exists():
            raise SystemExit(f"{path}: no arm columns and no batch_args.json; cannot place missing runs in an arm")
        import yaml
        from minpilot.config import CONFIG_DIR

        args = json.loads(args_file.read_text())
        arm = {"mode": "fresh", "pool": args["pool"],
               "condition": yaml.safe_load((CONFIG_DIR / "refiners" / f"{args['refiner']}.yaml").read_text())["name"], "checkpoint": "", "override_source": ""}
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


def refine_usd(usage: dict) -> float:
    return sum(float(b.get("cost_usd") or 0.0) + float(b.get("tool_usd") or 0.0)
               for stage, b in (usage or {}).items() if stage.startswith("refine"))


def stage_usd(usage, stages):
    return sum(float(b.get("cost_usd") or 0.0) + float(b.get("tool_usd") or 0.0)
               for stage, b in (usage or {}).items() if stage in stages)


def checkpoint_usd(ck: str | None) -> float:
    if not ck:
        return 0.0
    try:
        state = json.loads((resolve_artifact_path(ck) / "state.json").read_text())
    except (OSError, ValueError):
        return float("nan")
    return float(((state.get("trace") or {}).get("counters") or {}).get("cost_usd") or 0.0)


def mean(xs) -> float:
    xs = [float(x) for x in xs if x is not None and not pd.isna(x)]
    return sum(xs) / len(xs) if xs else float("nan")


def arm_of(r: dict) -> str:
    return f"{r['mode']}|{r['pool']}|{r['condition']}|override={r['override_source'] or 'none'}"


def per_task(rows: list[dict]) -> dict[str, float]:
    by = defaultdict(list)
    for r in rows:
        by[r["task_id"]].append(r["correct"])
    return {t: sum(v) / len(v) for t, v in by.items()}


def compare(df: pd.DataFrame, x: str, y: str, n_boot: int = 10_000, seed: int = 0) -> dict:
    d = df[(df["mode"] == "restore") & (df["override_source"].isna())]
    d = d.assign(**{c: np.nan for c in ("after_ck_usd", "refine_usd") if c not in d})  # rows without costs
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
                         "nx": len(ax), "ny": len(ay),
                         "usd_x": ax["after_ck_usd"].mean(), "usd_y": ay["after_ck_usd"].mean(),
                         "ref_x": ax["refine_usd"].mean(), "ref_y": ay["refine_usd"].mean()})
        t = pd.DataFrame(rows).groupby("task_id")[["x", "y", "usd_x", "usd_y", "ref_x", "ref_y"]].mean()
        diff = (t["y"] - t["x"]).to_numpy()
        rng = np.random.default_rng(seed)
        boots = rng.choice(diff, size=(n_boot, len(diff)), replace=True).mean(axis=1) if len(diff) else np.array([0])
        out[pool] = {"tasks": len(t), "checkpoints": len(cks), "x": float(t["x"].mean()), "y": float(t["y"].mean()),
                     "diff": float(diff.mean()), "ci95": [float(np.percentile(boots, 2.5)),
                                                          float(np.percentile(boots, 97.5))],
                     "usd_diff": float((t["usd_y"] - t["usd_x"]).mean()),
                     "refine_usd_diff": float((t["ref_y"] - t["ref_x"]).mean())}
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
        excluded = {str(resolve_artifact_path(x.strip())) for x in Path(a.exclude).read_text().splitlines() if x.strip()}
    records = sorted({rj.resolve() for p in map(Path, a.paths) for rj in find_run_records(p)})
    experiments = set()
    for rj in records:
        experiment = next((parent for parent in rj.parents if (parent / "manifest.json").is_file()), None)
        if experiment:
            experiments.add(experiment)
    if len(experiments) > 1:
        ap.error("score one experiment at a time; separate experiments may have different prompts and protocols")
    rows, excluded_keys = [], set()
    for rj in records:
        info = json.loads(rj.read_text())
        if str(rj.parent.resolve()) in excluded:
            excluded_keys.add(run_key(info["task_id"], info.get("label"), info.get("restored_from")))
            continue
        raw = info.get("final_answer")
        ans = extract_final_answer(raw)
        ok = info.get("status") == "ok"
        gt = truth[info["task_id"]]
        c = info.get("counters") or {}
        ref_usd = refine_usd(info.get("usage"))
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
            "unknown_cost_calls": c.get("unknown_cost_calls"), "n_delegations": info.get("n_delegations"),
            # Keep the historical aggregate while exposing independent current actions.
            "pre_execution_usd": stage_usd(info.get("usage"), {"probe", "evaluator.probe", "orchestrator.select", "refiner"}),
            "probe_usd": stage_usd(info.get("usage"), {"probe", "evaluator.probe"}),
            "refinement_usd": stage_usd(info.get("usage"), {"refiner"}),
            "n_probes": info.get("n_probes"),
            "evaluator_usd": stage_usd(info.get("usage"), {"evaluator.probe", "evaluator.execution"}),
            "serper_billed_credits": (info.get("paid_search") or {}).get("billed"),
            "serper_unknown_credits": (info.get("paid_search") or {}).get("unknown"),
            "after_ck_usd": (c.get("cost_usd") or 0.0) - checkpoint_usd(ck), "refine_usd": ref_usd})
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
        print(f"{arm}: tasks={len(pt)} runs={len(rs)} acc={sum(pt.values()) / len(pt):.3f} "
              f"usd/run={mean(r.get('after_ck_usd') for r in rs):.4f} "
              f"refine_usd/run={mean(r.get('refine_usd') for r in rs):.4f}")
    for x, y in a.compare:
        for pool, res in compare(df, x, y).items():
            print(f"compare {y} - {x} [{pool}]: tasks={res['tasks']} checkpoints={res['checkpoints']} "
                  f"{x}={res['x']:.3f} {y}={res['y']:.3f} diff={res['diff']:+.3f} "
                  f"95% CI [{res['ci95'][0]:+.3f}, {res['ci95'][1]:+.3f}] "
                  f"usd {res['usd_diff']:+.4f} refine_usd {res['refine_usd_diff']:+.4f}")
    print(f"{len(rows)} runs -> {out}")


if __name__ == "__main__":
    main()
