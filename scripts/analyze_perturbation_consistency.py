#!/usr/bin/env python
"""Score a perturbation-consistency experiment (the only step that reads LongCoT gold answers).

  python scripts/analyze_perturbation_consistency.py outputs/experiments/<date>_longcot-perturbation-consistency
  python scripts/analyze_perturbation_consistency.py EXP_A EXP_B --out <dir>     # pool several experiments

A run is correct when every requested node's answer matches the gold list (LongCoT's math comparison, no LLM
fallback). Per question: the routed run; each worker's fixed-run accuracy (mean over reps); their mean (the expected
accuracy of picking a worker at random); the best worker in hindsight; and a majority vote over all fixed runs' final
answers. The routing signal is checked on independent runs: the chosen worker's fixed accuracy against the mean.
Questions are the unit: paired differences over questions with a bootstrap CI (nodes are not independent samples).
Secondary, added after the first hard results showed 0% whole-chain accuracy everywhere: the share of requested
nodes answered correctly (partial credit), and "chosen = best" restricted to questions where workers differ.
Writes analysis/questions.csv, analysis/workers.csv and analysis/summary.json into the experiment directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.data import longcot  # noqa: E402
from perturbation_consistency import longcot_math  # noqa: E402
from perturbation_consistency.longcot_nodes import parse_chain  # noqa: E402


def correct(record: dict | None, requested: list[str], gold) -> bool:
    if not record or record.get("final") is None:
        return False
    return longcot_math.compare_answer_lists(gold, [record["final"].get(r) for r in requested]) == "match"


def node_acc(record: dict | None, requested: list[str], gold_parts: list[str]) -> float:
    """Secondary (partial credit): share of requested nodes answered correctly, including nodes answered before
    the run stopped. Missing run = 0."""
    if not record:
        return 0.0
    answers = {n["node"]: n["answer"] for n in record.get("nodes", [])} | record.get("given", {})
    return sum(longcot_math.same(g, answers.get(r)) for r, g in zip(requested, gold_parts)) / len(requested)


def majority(records: list[dict], requested: list[str], seed: str) -> list | None:
    finals = [[r["final"].get(n) for n in requested] for r in records if r.get("final")]
    groups: list[list[int]] = []
    for i, f in enumerate(finals):
        for g in groups:
            if longcot_math.compare_answer_lists(finals[g[0]], f) == "match":
                g.append(i)
                break
        else:
            groups.append([i])
    if not groups:
        return None
    top = max(len(g) for g in groups)
    return finals[random.Random(seed).choice([g for g in groups if len(g) == top])[0]]


def recompute(probe: dict | None) -> float | None:
    """Consistency from the raw samples with the current comparison (the recorded value is what routing used)."""
    if not probe:
        return None
    answers = [s["answer"] for s in probe["samples"]]
    groups = [g for g in longcot_math.group(answers) if answers[g[0]] is not None]
    return len(groups[0]) / len(answers) if groups else 0.0


def bootstrap(diffs: list[float], n: int = 10_000, seed: int = 0) -> list[float]:
    if not diffs:
        return [0.0, 0.0]
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return [means[int(0.025 * n)], means[int(0.975 * n) - 1]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiments", type=Path, nargs="+", help="one experiment, or several to pool (same workers)")
    ap.add_argument("--out", type=Path, default=None, help="output dir (default: <experiment>/analysis; required "
                                                           "when pooling)")
    args = ap.parse_args()
    if len(args.experiments) > 1 and args.out is None:
        ap.error("--out is required when pooling experiments")
    qrows, wrows, workers = [], [], None
    for exp in args.experiments:
        manifest = json.loads((exp / "manifest.json").read_text())
        if workers is not None and manifest["workers"] != workers:
            sys.exit(f"{exp}: workers differ from the other experiments")
        workers = manifest["workers"]
        collect(exp, manifest, qrows, wrows)
    summarize(qrows, wrows, workers, args.out or args.experiments[0] / "analysis")


def collect(exp: Path, manifest: dict, qrows: list, wrows: list) -> None:
    refs = longcot.load_references("math", manifest["dataset"]["difficulty"])
    workers = manifest["workers"]
    prompts = {q.question_id: q.prompt for q in longcot.load_questions("math", manifest["dataset"]["difficulty"])}
    for qid in manifest["question_ids"]:
        qdir = exp / "runs" / qid
        requested = list(parse_chain(qid, prompts[qid]).requested)
        gold = refs[qid].answer
        load = lambda p: json.loads(p.read_text()) if p.exists() else None  # noqa: E731
        choice = load(qdir / "choice.json") or {}
        routed = load(qdir / "consistency_routed_r0" / "record.json")
        fixed = {w: [load(p) for p in sorted(qdir.glob(f"fixed_{w}_r*/record.json"))] for w in workers}
        planned_reps = manifest["fixed_reps"]
        acc = {w: sum(correct(r, requested, gold) for r in fixed[w]) / planned_reps for w in workers}  # missing=wrong
        vote = majority([r for w in workers for r in fixed[w] if r], requested, f"vote:{qid}")
        probes = {w: load(qdir / f"consistency_probe_{w}" / "record.json") for w in workers}
        chosen = choice.get("chosen")
        probe_cost = sum((p or {}).get("cost_usd", 0) for p in probes.values())
        row = {"question_id": qid, "chosen": chosen, "tied": ",".join(choice.get("tied", [])),
               "routed_correct": int(correct(routed, requested, gold)),
               "routed_status": (routed or {}).get("status", "missing"),
               "fixed_mean": sum(acc.values()) / len(acc), "fixed_best": max(acc.values()),
               "chosen_fixed_acc": acc.get(chosen, 0.0) if chosen else 0.0,
               "vote_correct": int(vote is not None and longcot_math.compare_answer_lists(gold, vote) == "match"),
               "routed_cost_usd": probe_cost + (routed or {}).get("cost_usd", 0),
               "fixed_cost_usd_per_run": sum(r["cost_usd"] for w in workers for r in fixed[w] if r) /
               max(1, sum(1 for w in workers for r in fixed[w] if r))}
        gold_parts = longcot_math.answer_parts(gold)
        nacc = {w: sum(node_acc(r, requested, gold_parts) for r in fixed[w]) / planned_reps for w in workers}
        row.update(routed_node_acc=node_acc(routed, requested, gold_parts),
                   fixed_node_mean=sum(nacc.values()) / len(nacc), fixed_node_best=max(nacc.values()),
                   chosen_node_acc=nacc.get(chosen, 0.0) if chosen else 0.0,
                   workers_differ=int(max(acc.values()) > min(acc.values())),
                   workers_differ_node=int(max(nacc.values()) > min(nacc.values())))
        # earliest requested node: a proxy for accuracy early in the chain (node_0 itself has no gold)
        early = min(requested, key=lambda n: int(n.split("_")[1]))
        k = requested.index(early)
        row["early_node"] = early
        row["routed_early_correct"] = int(bool(routed and routed.get("final")) and
                                          longcot_math.same(gold_parts[k], routed["final"].get(early)))
        qrows.append(row)
        for w in workers:
            wrows.append({"question_id": qid, "worker": w, "consistency": (probes[w] or {}).get("consistency"),
                          "consistency_recomputed": recompute(probes[w]),
                          "fixed_acc": acc[w], "fixed_node_acc": nacc[w], "chosen": int(w == chosen)})


def summarize(qrows: list, wrows: list, workers: list, out: Path) -> None:
    n = len(qrows)
    mean = lambda key: sum(r[key] for r in qrows) / n  # noqa: E731
    d_routed = [r["routed_correct"] - r["fixed_mean"] for r in qrows]
    d_signal = [r["chosen_fixed_acc"] - r["fixed_mean"] for r in qrows]
    d_routed_node = [r["routed_node_acc"] - r["fixed_node_mean"] for r in qrows]
    d_signal_node = [r["chosen_node_acc"] - r["fixed_node_mean"] for r in qrows]
    differ = [r for r in qrows if r["workers_differ"]]
    differ_node = [r for r in qrows if r["workers_differ_node"]]
    untied = [r for r in qrows if "," not in r["tied"]]
    summary = {
        "questions": n, "workers": workers, "equivalence_version": longcot_math.EQUIVALENCE_VERSION,
        "accuracy": {"consistency_routed": mean("routed_correct"), "fixed_mean (random worker)": mean("fixed_mean"),
                     "fixed_best_in_hindsight": mean("fixed_best"), "majority_vote_over_fixed": mean("vote_correct"),
                     **{f"fixed_{w}": sum(x["fixed_acc"] for x in wrows if x["worker"] == w) / n for w in workers}},
        "routed_minus_fixed_mean": {"mean": sum(d_routed) / n, "ci95": bootstrap(d_routed)},
        "chosen_worker_fixed_acc_minus_mean": {"mean": sum(d_signal) / n, "ci95": bootstrap(d_signal)},
        "chosen_is_best_in_hindsight": sum(r["chosen_fixed_acc"] == r["fixed_best"] for r in qrows) / n,
        "chosen_is_best_when_workers_differ": {
            "questions": len(differ),
            "share": sum(r["chosen_fixed_acc"] == r["fixed_best"] for r in differ) / len(differ) if differ else None},
        "ties": sum(1 for r in qrows if "," in r["tied"]),
        "untied_questions": {"questions": len(untied), "routed_minus_fixed_mean_node_acc":
                             sum(r["routed_node_acc"] - r["fixed_node_mean"] for r in untied) / len(untied)
                             if untied else None},
        "secondary_partial_credit (share of requested nodes correct)": {
            "consistency_routed": mean("routed_node_acc"), "fixed_mean (random worker)": mean("fixed_node_mean"),
            "fixed_best_in_hindsight": mean("fixed_node_best"),
            **{f"fixed_{w}": sum(x["fixed_node_acc"] for x in wrows if x["worker"] == w) / n for w in workers},
            "routed_minus_fixed_mean": {"mean": sum(d_routed_node) / n, "ci95": bootstrap(d_routed_node)},
            "chosen_worker_minus_mean": {"mean": sum(d_signal_node) / n, "ci95": bootstrap(d_signal_node)},
            "chosen_is_best_when_workers_differ": {
                "questions": len(differ_node),
                "share": (sum(r["chosen_node_acc"] == r["fixed_node_best"] for r in differ_node) / len(differ_node)
                          if differ_node else None)}},
        "routed_status": {s: sum(r["routed_status"] == s for r in qrows) for s in {r["routed_status"] for r in qrows}},
        "cost_usd": {"routed_per_question": mean("routed_cost_usd"),
                     "fixed_per_run": mean("fixed_cost_usd_per_run")},
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("questions.csv", qrows), ("workers.csv", wrows)):
        with (out / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
