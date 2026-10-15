#!/usr/bin/env python
"""Analysis only: does combining a candidate's probe answers raise list recall? prepare/judge/analyze.

For each list question of a finished MoNaCo instruction-selection experiment, the probe answers of one candidate
(9 slots) or of all candidates (36 slots) are combined by item support: an item group enters the answer when at
least k slots contain it (k = 1, 2/9, 3/9, 5/9 of the slots). Item groups come from the experiment's own split and
cluster records, so no answer is generated; only the combined answers are judged. Each is compared with the mean
judged score of the single probe answers it was built from (same slots, so 9 or 36 times the calls of one answer).
List questions are chosen by the gold's form (analysis side); the gold never reaches a model under test."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
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

FROM_SOURCE = ("targets.jsonl", "inputs.jsonl", "results.jsonl", "splits.jsonl", "clusters.jsonl")
SHARES = {"any": None, "2/9": 2 / 9, "3/9": 3 / 9, "5/9": 5 / 9}
POOLS = (*mis.CANDIDATES, "all")


def implementation_hashes():
    return {**runner.implementation_hashes(), str(Path(__file__).resolve().relative_to(ROOT)): digest(Path(__file__))}


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def threshold(share, n):
    return 1 if share is None else math.ceil(share * n - 1e-9)


def combine(records, lines, labels, k):
    """Item groups held by at least k of the slots; each written as its most frequent item text in these slots."""
    support, texts = Counter(), {}
    for r in records:
        items = mis.slot_items(r, lines)
        if not items:
            continue
        seen = set()
        for t in items:
            g = labels.get(t)
            if g is None:
                continue
            texts.setdefault(g, Counter())[t] += 1
            if g not in seen:
                support[g] += 1
                seen.add(g)
    keep = sorted((g for g, s in support.items() if s >= k), key=lambda g: (-support[g], texts[g].most_common(1)[0][0]))
    return "; ".join(texts[g].most_common(1)[0][0] for g in keep) or "none"


def prepare(args):
    src, exp = args.source.resolve(), args.experiment
    exp.mkdir(parents=True, exist_ok=True)
    if (exp / "manifest.json").exists():
        raise ValueError("experiment already prepared; use another directory")
    for name in FROM_SOURCE:
        shutil.copyfile(src / name, exp / name)
    shutil.copyfile(args.probe_judged.resolve() / "probe_judgements.jsonl", exp / "probe_judgements.jsonl")
    sargs = argparse.Namespace(experiment=exp, data_root=args.data_root)
    targets = read_rows(exp / "targets.jsonl")
    golds = runner.gold(sargs, targets)
    probes = runner.final_probes(sargs, targets)
    lines = runner.final_splits(sargs, targets)
    clusters = mis.latest(read_rows(exp / "clusters.jsonl"), lambda r: r["target_id"])
    rows = []
    for t in targets:
        tid = t["target_id"]
        if mis.judge_kind(golds[tid]) != "list":
            continue
        for pool in POOLS:
            recs = [r for r in probes if r["target_id"] == tid and (pool == "all" or r["candidate"] == pool)]
            for name, share in SHARES.items():
                k = threshold(share, len(recs))
                rows.append({"target_id": tid, "pool": pool, "share": name, "k": k, "slots": len(recs),
                             "answer_line": combine(recs, lines[tid], clusters[tid]["labels"], k)})
    (exp / "aggregates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    write_json(exp / "manifest.json", experiment_manifest(
        purpose="Analysis only: judge probe answers combined by item support to see whether combining raises list recall",
        run_roots=["aggregate_judge"], harness="scripts/aggregate_monaco_probes.py", experiment_version=mis.VERSION,
        source_experiment=rel(src), probe_judged_experiment=rel(args.probe_judged.resolve()), judge=mis.JUDGE,
        models={mis.JUDGE: get_spec(mis.JUDGE).identity()}, shares=list(SHARES), pools=list(POOLS),
        copied_hashes={n: digest(exp / n) for n in (*FROM_SOURCE, "probe_judgements.jsonl", "aggregates.jsonl")},
        implementation_hashes=implementation_hashes(),
        git_commit=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip(), created_at=runner.now()))
    print(f"Prepared {len(rows)} combined answers, "
          f"{len({(r['target_id'], r['answer_line']) for r in rows})} distinct: {exp}")


def load(exp):
    manifest = json.loads((exp / "manifest.json").read_text())
    if manifest["implementation_hashes"] != implementation_hashes() \
            or manifest["models"] != {mis.JUDGE: get_spec(mis.JUDGE).identity()}:
        raise ValueError("implementation or judge changed: use a new experiment")
    for name, sha in manifest["copied_hashes"].items():
        if digest(exp / name) != sha:
            raise ValueError(f"copied artifact changed: {name}")
    return read_rows(exp / "targets.jsonl"), {r["target_id"]: r for r in read_rows(exp / "inputs.jsonl")}


def line_key(r):
    return (r["target_id"], r["answer_line"])


def judge(args, targets, inputs):
    """Each distinct (question, combined answer) once."""
    path = args.experiment / "aggregate_judgements.jsonl"
    distinct = {line_key(r): r for r in read_rows(args.experiment / "aggregates.jsonl")}
    jobs = [distinct[k] for k in mis.pending(list(distinct), read_rows(path), line_key)]
    if not jobs:
        print("All combined answers judged; no calls.")
        return
    golds = runner.gold(args, targets)
    stage = runner.Stage(args, "aggregate_judge", [mis.JUDGE])

    def job(r):
        tid = r["target_id"]
        with stage.lock:
            client, trace = stage.client(runner.key_of(tid, r["answer_line"]), mis.JUDGE)
        with trace.tags(stage="aggregate_judge", target_id=tid):
            rec = mis.judge(client, inputs[tid]["question"], "Answers: " + r["answer_line"], golds[tid])
        with stage.lock:
            runner.append(path, {"target_id": tid, "answer_line": r["answer_line"], **rec,
                                 "cost_usd": trace.run_scope.cost_usd})
    try:
        runner.run_jobs(args, jobs, job)
    finally:
        stage.close()


def analyze(args, targets):
    exp = args.experiment
    judged = {line_key(j): j for j in mis.latest(read_rows(exp / "aggregate_judgements.jsonl"), line_key).values()}
    probe = {runner.probe_key(j): j for j in mis.latest(read_rows(exp / "probe_judgements.jsonl"), runner.probe_key).values()}
    aggs = read_rows(exp / "aggregates.jsonl")
    tids = sorted({r["target_id"] for r in aggs})

    def val(j, f):
        return (j.get(f) or 0.) if j and j["status"] == "ok" else 0.

    def single(tid, pool, f):
        cs = mis.CANDIDATES if pool == "all" else (pool,)
        return statistics.mean(val(probe.get((tid, c, k, w)), f) for c in cs for k in range(mis.REPEATS)
                               for w in mis.WORKERS)

    table = {}
    for pool in POOLS:
        base = {f: {tid: single(tid, pool, f) for tid in tids} for f in ("score", "precision", "recall")}
        table[pool] = {"single_answer": {f: statistics.mean(v.values()) for f, v in base.items()}}
        for name in SHARES:
            rows = {r["target_id"]: judged.get(line_key(r)) for r in aggs if r["pool"] == pool and r["share"] == name}
            d = [val(rows[tid], "score") - base["score"][tid] for tid in tids]
            table[pool][name] = {**{f: statistics.mean(val(rows[tid], f) for tid in tids) for f in ("score", "precision", "recall")},
                                 "items": statistics.mean((rows[tid] or {}).get("predicted") or 0 for tid in tids),
                                 "delta_vs_single": statistics.mean(d), "delta_ci95": ins.interval(d)}
    summary = {"list_targets": len(tids), "judged_ok": sum(j["status"] == "ok" for j in judged.values()),
               "distinct_answers": len(judged), "table": table,
               "cost_usd": sum(runner.trace_costs(exp / j["trace"])["recorded_request_cost"]
                               for j in read_rows(exp / "aggregate_judge_jobs.jsonl")),
               "note": "single_answer = mean judged score of the probe answers in the same slots; combined answers use "
                       "those slots' calls (9 or 36 answers)."}
    (exp / "analysis").mkdir(exist_ok=True)
    write_json(exp / "analysis" / "summary.json", summary)
    print(json.dumps(summary, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["prepare", "judge", "analyze"])
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--source", type=Path, help="finished experiment with probes, splits and clusters (prepare only)")
    ap.add_argument("--probe-judged", type=Path, help="probe judging of the source (prepare only)")
    ap.add_argument("--data-root", type=Path, default=monaco.MONACO_ROOT)
    ap.add_argument("--session-cost-usd", type=float)
    ap.add_argument("--run-cost-usd", type=float)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = ap.parse_args()
    args.batch = False
    if args.stage == "prepare":
        if args.source is None or args.probe_judged is None:
            ap.error("prepare requires --source and --probe-judged")
        prepare(args)
        return
    with runner.exclusive(args.experiment):
        targets, inputs = load(args.experiment)
        judge(args, targets, inputs) if args.stage == "judge" else analyze(args, targets)


if __name__ == "__main__":
    main()
