#!/usr/bin/env python
"""Analysis only: pool finished MoNaCo instruction-selection experiments into one equal-weight task set.

Each part is an experiment whose executions are judged by the current judge (a run or a re-judging of one), with an
optional probe judging. v5 and v6 parts pool as one experiment (docs/decisions.md C40). Parts are read only; no
model is called. Writes `summary.json` into a new output directory with a manifest."""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from minpilot.artifacts import experiment_manifest
from minpilot.data import monaco
from perturbation_consistency import instruction_selection as ins
from perturbation_consistency import monaco_instruction_selection as mis

_spec = importlib.util.spec_from_file_location("monaco_runner", ROOT / "scripts/run_monaco_instruction_selection.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)
read_rows, write_json, digest = runner.read_rows, runner.write_json, runner.digest
PARTS = ("targets.jsonl", "selection.jsonl", "executions.jsonl", "judgements.jsonl")
CANDIDATES = ins.CANDIDATES  # v5 and v6 parts: naive, analogical, clarify, local_check


def rel(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def load_part(exp: Path) -> dict:
    manifest = json.loads((exp / "manifest.json").read_text())
    if manifest["judge"] != mis.JUDGE:
        raise ValueError(f"{exp}: executions not judged by {mis.JUDGE}")
    return {"targets": read_rows(exp / "targets.jsonl"), "selection": read_rows(exp / "selection.jsonl"),
            "executions": list(mis.latest(read_rows(exp / "executions.jsonl"), runner.run_key).values()),
            "judgements": list(mis.latest(read_rows(exp / "judgements.jsonl"), runner.run_key).values()),
            "version": manifest["experiment_version"]}


def scores(args, parts):
    targets = [t for p in parts for t in p["targets"]]
    ids = [t["target_id"] for t in targets]
    if len(ids) != len(set(ids)):
        raise ValueError("a task appears in two parts")
    kinds = {tid: mis.judge_kind(g) for tid, g in runner.gold(args, targets).items()}
    out = mis.analyze(targets, [s for p in parts for s in p["selection"]], [r for p in parts for r in p["executions"]],
                      [j for p in parts for j in p["judgements"]], kinds=kinds, candidates=CANDIDATES)
    return {k: v for k, v in out.items() if k != "per_task"}


def probe_policies(summaries):
    """Pooled probe-judge diagnostics from the per-task tables of each probe judging."""
    per_task = {tid: d for s in summaries for tid, d in s["per_task"].items()}
    cs = CANDIDATES
    pick = {"naive": lambda d: ["naive"], "random": lambda d: list(cs),
            "probe_oracle": lambda d: d["probe_oracle"],
            "best_in_hindsight": lambda d: [max(cs, key=lambda c: d[c]["execution_score"])]}
    table = {}
    for p, f in pick.items():
        table[p] = {tid: statistics.mean(d[c]["execution_score"] for c in f(d)) for tid, d in per_task.items()}
    res = {}
    for p, t in table.items():
        d = [t[tid] - table["naive"][tid] for tid in per_task]
        res[p] = {"mean": statistics.mean(t.values()), "delta_vs_naive": statistics.mean(d), "delta_ci95": ins.interval(d)}
    conc = {}
    for name, x, y in [("agreement_vs_probe_score", "agreement", "probe_score"),
                       ("probe_score_vs_execution", "probe_score", "execution_score"),
                       ("executor_probe_score_vs_execution", "executor_probe_score", "execution_score"),
                       ("agreement_vs_execution", "agreement", "execution_score")]:
        counts = {"same": 0, "opposite": 0, "tied": 0}
        for d in per_task.values():
            for a, b in itertools.combinations(cs, 2):
                dx, dy = d[a][x] - d[b][x], d[a][y] - d[b][y]
                counts["tied" if abs(dx) < 1e-9 or abs(dy) < 1e-9 else "same" if (dx > 0) == (dy > 0) else "opposite"] += 1
        conc[name] = counts
    return {"targets": len(per_task), "policies_on_executions": res, "within_task_concordance": conc,
            "note": "probe_oracle reads gold through probe judgements; diagnostic only, never a selection rule."}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True, help="new output directory")
    ap.add_argument("--parts", type=Path, nargs="+", required=True, help="judged experiments to pool")
    ap.add_argument("--probe-judged", type=Path, nargs="*", default=[], help="probe judgings of the same parts")
    ap.add_argument("--data-root", type=Path, default=monaco.MONACO_ROOT)
    args = ap.parse_args()
    if (args.out / "manifest.json").exists():
        raise ValueError("output already written; use another directory")
    parts = [load_part(p) for p in args.parts]
    summary = {"pooled": scores(args, parts),
               "parts": {rel(p): {"version": part["version"], **scores(args, [part])} for p, part in zip(args.parts, parts)}}
    if args.probe_judged:
        summary["probe_judge_pooled"] = probe_policies(
            [json.loads((p / "analysis/summary.json").read_text()) for p in args.probe_judged])
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "manifest.json", experiment_manifest(
        purpose="Analysis only: pool judged MoNaCo instruction-selection experiments (v5 and v6 as one, C40)",
        run_roots=[], harness="scripts/analyze_monaco_pooled.py", judge=mis.JUDGE,
        parts={rel(p): {n: digest(p / n) for n in PARTS} for p in args.parts},
        probe_judged={rel(p): digest(p / "analysis/summary.json") for p in args.probe_judged},
        implementation_hashes={rel(Path(__file__)): digest(Path(__file__)), **runner.implementation_hashes()},
        git_commit=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip(), created_at=runner.now()))
    write_json(args.out / "summary.json", summary)
    pooled = summary["pooled"]["selection"]["score"]
    print(json.dumps({"targets": summary["pooled"]["targets"],
                      "score": {p: [round(v["mean"], 4), round(v["delta_vs_naive"], 4), [round(x, 3) for x in v["delta_ci95"]]]
                                for p, v in pooled.items()},
                      "hindsight_null": summary["pooled"]["hindsight_null"],
                      "probe_judge": summary.get("probe_judge_pooled", {}).get("policies_on_executions")}, indent=2))


if __name__ == "__main__":
    main()
