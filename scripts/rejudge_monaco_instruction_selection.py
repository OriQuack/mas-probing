#!/usr/bin/env python
"""Re-judge a finished MoNaCo instruction-selection experiment with the current judge: prepare/validate-judge/judge/analyze.

The source's targets, inputs, executions and selections are copied unchanged into a new experiment directory; only
the judge model and what it reads change (`mis.JUDGE`, `mis.judge_response`). No probe, execution or selection call
is made. The source directory is read only."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from minpilot.artifacts import experiment_manifest
from minpilot.data import monaco
from minpilot.llm.specs import get_spec
from perturbation_consistency import monaco_instruction_selection as mis

_spec = importlib.util.spec_from_file_location("monaco_runner", ROOT / "scripts/run_monaco_instruction_selection.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)
read_rows, write_json, digest = runner.read_rows, runner.write_json, runner.digest

COPIED = ("targets.jsonl", "inputs.jsonl", "executions.jsonl", "selection.jsonl")


def implementation_hashes():
    return {**runner.implementation_hashes(), str(Path(__file__).resolve().relative_to(ROOT)): digest(Path(__file__))}


def prepare(args):
    src, exp = args.source.resolve(), args.experiment
    source = json.loads((src / "manifest.json").read_text())
    for name, sha in source["input_hashes"].items():
        if digest(src / name) != sha:
            raise ValueError(f"source artifact changed: {name}")
    if json.loads((src / "selection_meta.json").read_text())["selection_sha256"] != digest(src / "selection.jsonl"):
        raise ValueError("source selection changed")
    exp.mkdir(parents=True, exist_ok=True)
    if (exp / "manifest.json").exists():
        raise ValueError("experiment already prepared; use another directory")
    for name in COPIED:
        shutil.copyfile(src / name, exp / name)
    write_json(exp / "manifest.json", experiment_manifest(
        purpose="Re-judge recorded executions with the current judge and answer-line judge input",
        run_roots=["validate_judge", "judge"], harness="scripts/rejudge_monaco_instruction_selection.py",
        experiment_version=mis.VERSION, source_experiment=str(src.relative_to(ROOT) if src.is_relative_to(ROOT) else src),
        source_experiment_version=source["experiment_version"], source_judge=source["judge"],
        judge=mis.JUDGE, models={mis.JUDGE: get_spec(mis.JUDGE).identity()},
        judge_response="final answer line (`mis.judge_response`); full content when there is none",
        seed=source["seed"], copied_hashes={n: digest(exp / n) for n in COPIED},
        implementation_hashes=implementation_hashes(),
        git_commit=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip(), created_at=runner.now()))
    print(f"Prepared re-judging of {src.name}: {exp}")


def load(exp):
    manifest = json.loads((exp / "manifest.json").read_text())
    if manifest["implementation_hashes"] != implementation_hashes() \
            or manifest["models"] != {mis.JUDGE: get_spec(mis.JUDGE).identity()}:
        raise ValueError("implementation or judge changed: use a new experiment")
    for name, sha in manifest["copied_hashes"].items():
        if digest(exp / name) != sha:
            raise ValueError(f"copied artifact changed: {name}")
    return manifest, read_rows(exp / "targets.jsonl"), {r["target_id"]: r for r in read_rows(exp / "inputs.jsonl")}


def overcounted(judgements, executions):
    """List judgements whose overlap count exceeds the items of the parsed final answer. Only executions recorded
    before v7 carry a parsed JSON answer; answer-line executions are not counted."""
    ex = {runner.run_key(r): r for r in executions}
    return sum(j.get("kind") == "list" and j["status"] == "ok" and ex[runner.run_key(j)].get("answer") is not None
               and j["num_correct"] > len(ex[runner.run_key(j)]["answer"]) for j in judgements)


def analyze(args, manifest, targets):
    exp, src = args.experiment, ROOT / manifest["source_experiment"]
    golds = runner.gold(args, targets)
    kinds = {tid: mis.judge_kind(g) for tid, g in golds.items()}
    executions = list(mis.latest(read_rows(exp / "executions.jsonl"), runner.run_key).values())
    sels = read_rows(exp / "selection.jsonl")
    new = list(mis.latest(read_rows(exp / "judgements.jsonl"), runner.run_key).values())
    old = list(mis.latest(read_rows(src / "judgements.jsonl"), runner.run_key).values())
    summary = mis.analyze(targets, sels, executions, new, kinds=kinds)
    before = mis.analyze(targets, sels, executions, old, kinds=kinds)
    pairs = {runner.run_key(j): j.get("score") for j in old}
    diffs = [abs((j.get("score") or 0.) - (pairs.get(runner.run_key(j)) or 0.)) for j in new]
    summary["source_judge"] = {"judge": manifest["source_judge"],
                               "score": {p: v["mean"] for p, v in before["selection"]["score"].items()},
                               "by_kind": {k: {p: v["mean"] for p, v in b["score"].items()}
                                           for k, b in before["by_kind"].items()},
                               "hindsight_null": before["hindsight_null"]}
    summary["judge_changes"] = {"compared": len(diffs), "changed": sum(d > 1e-9 for d in diffs),
                                "mean_abs_diff": sum(diffs) / len(diffs) if diffs else None,
                                "overcounted_list_judgements": {"source": overcounted(old, executions),
                                                                "current": overcounted(new, executions)}}
    summary["judge_validation"] = json.loads((exp / "judge_validation_summary.json").read_text()) \
        if (exp / "judge_validation_summary.json").exists() else None
    summary["judge_statuses"] = dict(Counter(j["status"] for j in new))
    summary["cost_usd"] = {stage: sum(runner.trace_costs(exp / j["trace"])["recorded_request_cost"]
                                      for j in read_rows(exp / f"{stage}_jobs.jsonl"))
                           for stage in ("validate_judge", "judge")}
    summary["experiment_version"] = manifest["experiment_version"]
    out = exp / "analysis"
    out.mkdir(exist_ok=True)
    write_json(out / "summary.json", summary)
    print(json.dumps({"score": {p: round(v["mean"], 4) for p, v in summary["selection"]["score"].items()},
                      "source_score": {p: round(v, 4) for p, v in summary["source_judge"]["score"].items()},
                      "hindsight_null": summary["hindsight_null"], "judge_changes": summary["judge_changes"],
                      "cost_usd": summary["cost_usd"]}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["prepare", "validate-judge", "judge", "analyze"])
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--source", type=Path, help="finished experiment to re-judge (prepare only)")
    ap.add_argument("--data-root", type=Path, default=monaco.MONACO_ROOT)
    ap.add_argument("--session-cost-usd", type=float)
    ap.add_argument("--run-cost-usd", type=float)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = ap.parse_args()
    args.batch = False
    if args.stage == "prepare":
        if args.source is None:
            ap.error("prepare requires --source")
        prepare(args)
        return
    with runner.exclusive(args.experiment):
        manifest, targets, inputs = load(args.experiment)
        if args.stage == "validate-judge":
            runner.validate_judge(args, manifest, targets, inputs)
        elif args.stage == "judge":
            runner.judge(args, manifest, targets, inputs)
        else:
            analyze(args, manifest, targets)


if __name__ == "__main__":
    main()
