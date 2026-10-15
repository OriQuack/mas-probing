#!/usr/bin/env python
"""Analysis only: judge the probe answers of a finished MoNaCo instruction-selection experiment: prepare/judge/analyze.

Asks whether cross-worker agreement fails because it does not track probe correctness, or because probe
correctness does not carry over to the executor's fresh runs. Probe scores use gold and never feed a selection;
`probe_oracle` (the candidate with the best judged probes, scored on the separate executions) is a diagnostic, not a
policy. Sources are copied and read only; executions are scored by a re-judged experiment with the same judge."""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from minpilot.artifacts import experiment_manifest
from minpilot.data import monaco
from minpilot.llm.specs import get_spec
from perturbation_consistency import instruction_selection as ins
from perturbation_consistency import monaco_instruction_selection as mis

_spec = importlib.util.spec_from_file_location("monaco_runner", ROOT / "scripts/run_monaco_instruction_selection.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)
read_rows, write_json, digest = runner.read_rows, runner.write_json, runner.digest

FROM_SOURCE = ("targets.jsonl", "inputs.jsonl", "results.jsonl", "selection.jsonl")
FROM_JUDGED = ("executions.jsonl", "judgements.jsonl")


def implementation_hashes():
    return {**runner.implementation_hashes(), str(Path(__file__).resolve().relative_to(ROOT)): digest(Path(__file__))}


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def prepare(args):
    src, judged, exp = args.source.resolve(), args.judged.resolve(), args.experiment
    meta = json.loads((src / "selection_meta.json").read_text())
    if meta["results.jsonl_sha256"] != digest(src / "results.jsonl") or meta["selection_sha256"] != digest(src / "selection.jsonl"):
        raise ValueError("source probes or selection changed")
    judged_manifest = json.loads((judged / "manifest.json").read_text())
    if judged_manifest["judge"] != mis.JUDGE or (judged != src and judged_manifest.get("source_experiment") != rel(src)):
        raise ValueError("executions must be judged by the current judge, in the source or a re-judging of it")
    exp.mkdir(parents=True, exist_ok=True)
    if (exp / "manifest.json").exists():
        raise ValueError("experiment already prepared; use another directory")
    for name in FROM_SOURCE:
        shutil.copyfile(src / name, exp / name)
    for name in FROM_JUDGED:
        shutil.copyfile(judged / name, exp / name)
    write_json(exp / "manifest.json", experiment_manifest(
        purpose="Analysis only: judge probe answers to separate agreement-vs-correctness from probe-vs-execution",
        run_roots=["probe_judge"], harness="scripts/judge_monaco_probes.py", experiment_version=mis.VERSION,
        source_experiment=rel(src), judged_experiment=rel(judged), judge=mis.JUDGE,
        models={mis.JUDGE: get_spec(mis.JUDGE).identity()},
        judge_response="final answer line (`mis.judge_response`); full content when there is none",
        copied_hashes={n: digest(exp / n) for n in FROM_SOURCE + FROM_JUDGED},
        implementation_hashes=implementation_hashes(),
        git_commit=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip(), created_at=runner.now()))
    print(f"Prepared probe judging of {src.name}: {exp}")


def load(exp):
    manifest = json.loads((exp / "manifest.json").read_text())
    if manifest["implementation_hashes"] != implementation_hashes() \
            or manifest["models"] != {mis.JUDGE: get_spec(mis.JUDGE).identity()}:
        raise ValueError("implementation or judge changed: use a new experiment")
    for name, sha in manifest["copied_hashes"].items():
        if digest(exp / name) != sha:
            raise ValueError(f"copied artifact changed: {name}")
    return manifest, read_rows(exp / "targets.jsonl"), {r["target_id"]: r for r in read_rows(exp / "inputs.jsonl")}


def judge(args, targets, inputs):
    """Every final probe slot with content; slots without content score 0 unjudged."""
    path = args.experiment / "probe_judgements.jsonl"
    probes = {runner.probe_key(r): r for r in mis.latest(read_rows(args.experiment / "results.jsonl"), runner.probe_key).values()
              if r.get("content")}
    jobs = [probes[k] for k in mis.pending(list(probes), read_rows(path), runner.probe_key)]
    if not jobs:
        print("All probes judged; no calls.")
        return
    golds = runner.gold(args, targets)
    stage = runner.Stage(args, "probe_judge", [mis.JUDGE])

    def job(r):
        tid = r["target_id"]
        with stage.lock:
            client, trace = stage.client(runner.key_of(*runner.probe_key(r)), mis.JUDGE)
        with trace.tags(stage="probe_judge", target_id=tid, candidate=r["candidate"], worker=r["worker"], rep=r["sample"]):
            rec = mis.judge(client, inputs[tid]["question"], mis.judge_response(r), golds[tid])
        with stage.lock:
            runner.append(path, {"target_id": tid, "candidate": r["candidate"], "worker": r["worker"],
                                 "sample": r["sample"], **rec, "cost_usd": trace.run_scope.cost_usd})
    try:
        runner.run_jobs(args, jobs, job)
    finally:
        stage.close()


def concordance(pairs):
    """Candidate pairs within a task: whether ordering by x agrees with ordering by y (ties on either side apart)."""
    out = Counter()
    for xs, ys in pairs:
        for a, b in itertools.combinations(range(len(xs)), 2):
            dx, dy = xs[a] - xs[b], ys[a] - ys[b]
            out["tied" if abs(dx) < 1e-9 or abs(dy) < 1e-9 else "same" if (dx > 0) == (dy > 0) else "opposite"] += 1
    return dict(out)


def analyze(args, targets):
    exp = args.experiment
    tids = [t["target_id"] for t in targets]
    sels = {s["target_id"]: s for s in read_rows(exp / "selection.jsonl")}
    probe_scores = {runner.probe_key(j): j.get("score") if j["status"] == "ok" else None
                    for j in mis.latest(read_rows(exp / "probe_judgements.jsonl"), runner.probe_key).values()}
    exec_scores = {runner.run_key(j): j.get("score") if j["status"] == "ok" else None
                   for j in mis.latest(read_rows(exp / "judgements.jsonl"), runner.run_key).values()}

    def probe_mean(tid, c, workers=mis.WORKERS):
        return statistics.mean(probe_scores.get((tid, c, k, w)) or 0. for w in workers for k in range(mis.REPEATS))

    def exec_mean(tid, c):
        return statistics.mean(exec_scores.get((tid, c, k)) or 0. for k in range(mis.REPEATS))

    per_task, agree_probe, probe_exec, haiku_exec, agree_exec = {}, [], [], [], []
    for tid in tids:
        cs = mis.CANDIDATES
        ag = [sels[tid]["scores"][c]["agreement"] for c in cs]
        pm = [probe_mean(tid, c) for c in cs]
        hm = [probe_mean(tid, c, (mis.EXECUTOR,)) for c in cs]
        em = [exec_mean(tid, c) for c in cs]
        agree_probe.append((ag, pm)), probe_exec.append((pm, em)), haiku_exec.append((hm, em)), agree_exec.append((ag, em))
        top = max(pm)
        per_task[tid] = {c: {"agreement": a, "probe_score": p, "executor_probe_score": h, "execution_score": e}
                         for c, a, p, h, e in zip(cs, ag, pm, hm, em)}
        per_task[tid]["probe_oracle"] = sorted(c for c, p in zip(cs, pm) if p == top)
    policies = {
        "selected": lambda tid: [sels[tid]["primary"]["candidate"]],
        "naive": lambda tid: ["naive"],
        "random": lambda tid: list(mis.CANDIDATES),
        "probe_oracle": lambda tid: per_task[tid]["probe_oracle"],
        "best_in_hindsight": lambda tid: [max(mis.CANDIDATES, key=lambda c: per_task[tid][c]["execution_score"])]}
    table = {p: {tid: statistics.mean(per_task[tid][c]["execution_score"] for c in f(tid)) for tid in tids}
             for p, f in policies.items()}
    scores = {}
    for p, t in table.items():
        d = [t[tid] - table["naive"][tid] for tid in tids]
        scores[p] = {"mean": statistics.mean(t.values()), "delta_vs_naive": statistics.mean(d), "delta_ci95": ins.interval(d)}
    selected_probe = {tid: per_task[tid][sels[tid]["primary"]["candidate"]] for tid in tids}
    summary = {
        "targets": len(tids), "probe_judged_ok": sum(v is not None for v in probe_scores.values()),
        "probe_judge_statuses": dict(Counter(j["status"] for j in read_rows(exp / "probe_judgements.jsonl"))),
        "policies_on_executions": scores,
        "within_task_concordance": {"agreement_vs_probe_score": concordance(agree_probe),
                                    "probe_score_vs_execution": concordance(probe_exec),
                                    "executor_probe_score_vs_execution": concordance(haiku_exec),
                                    "agreement_vs_execution": concordance(agree_exec)},
        "high_agreement_low_probe_score": sorted(
            (tid, c) for tid in tids for c in mis.CANDIDATES
            if per_task[tid][c]["agreement"] >= .9 and per_task[tid][c]["probe_score"] < .5),
        "selected_probe_score_mean": statistics.mean(v["probe_score"] for v in selected_probe.values()),
        "per_task": per_task,
        "cost_usd": sum(runner.trace_costs(exp / j["trace"])["recorded_request_cost"]
                        for j in read_rows(exp / "probe_judge_jobs.jsonl")),
        "note": "probe_oracle reads gold through probe judgements; diagnostic only, never a selection rule."}
    out = exp / "analysis"
    out.mkdir(exist_ok=True)
    write_json(out / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_task"}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["prepare", "judge", "analyze"])
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--source", type=Path, help="finished experiment with the probes (prepare only)")
    ap.add_argument("--judged", type=Path, help="experiment whose current-judge judgements score the source's "
                                                "executions: the source itself or a re-judging (prepare only)")
    ap.add_argument("--data-root", type=Path, default=monaco.MONACO_ROOT)
    ap.add_argument("--session-cost-usd", type=float)
    ap.add_argument("--run-cost-usd", type=float)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = ap.parse_args()
    args.batch = False
    if args.stage == "prepare":
        if args.source is None or args.judged is None:
            ap.error("prepare requires --source and --judged")
        prepare(args)
        return
    with runner.exclusive(args.experiment):
        _, targets, inputs = load(args.experiment)
        judge(args, targets, inputs) if args.stage == "judge" else analyze(args, targets)


if __name__ == "__main__":
    main()
