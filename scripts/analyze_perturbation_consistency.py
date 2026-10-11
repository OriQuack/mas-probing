#!/usr/bin/env python
"""Score a perturbation-consistency experiment (the only step that reads LongCoT gold answers).

  python scripts/analyze_perturbation_consistency.py outputs/experiments/<date>_longcot-perturbation-consistency

A run is correct when every requested node's answer matches the gold list (LongCoT's math comparison, no LLM
fallback). Per question: the routed run; each worker's fixed-run accuracy (mean over reps); their mean (the expected
accuracy of picking a worker at random); the best worker in hindsight; and a majority vote over all fixed runs' final
answers. The routing signal is checked on independent runs: the chosen worker's fixed accuracy against the mean.
Questions are the unit: paired differences over questions with a bootstrap CI (nodes are not independent samples).
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


def bootstrap(diffs: list[float], n: int = 10_000, seed: int = 0) -> list[float]:
    if not diffs:
        return [0.0, 0.0]
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return [means[int(0.025 * n)], means[int(0.975 * n) - 1]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", type=Path)
    args = ap.parse_args()
    exp = args.experiment
    manifest = json.loads((exp / "manifest.json").read_text())
    refs = longcot.load_references("math", manifest["dataset"]["difficulty"])
    workers = manifest["workers"]
    prompts = {q.question_id: q.prompt for q in longcot.load_questions("math", manifest["dataset"]["difficulty"])}
    qrows, wrows = [], []
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
        # earliest requested node: a proxy for accuracy early in the chain (node_0 itself has no gold)
        early = min(requested, key=lambda n: int(n.split("_")[1]))
        k = requested.index(early)
        gold_parts = longcot_math.answer_parts(gold)
        row["early_node"] = early
        row["routed_early_correct"] = int(bool(routed and routed.get("final")) and
                                          longcot_math.same(gold_parts[k], routed["final"].get(early)))
        qrows.append(row)
        for w in workers:
            wrows.append({"question_id": qid, "worker": w, "consistency": (probes[w] or {}).get("consistency"),
                          "fixed_acc": acc[w], "chosen": int(w == chosen)})
    n = len(qrows)
    mean = lambda key: sum(r[key] for r in qrows) / n  # noqa: E731
    d_routed = [r["routed_correct"] - r["fixed_mean"] for r in qrows]
    d_signal = [r["chosen_fixed_acc"] - r["fixed_mean"] for r in qrows]
    summary = {
        "questions": n, "workers": workers,
        "accuracy": {"consistency_routed": mean("routed_correct"), "fixed_mean (random worker)": mean("fixed_mean"),
                     "fixed_best_in_hindsight": mean("fixed_best"), "majority_vote_over_fixed": mean("vote_correct"),
                     **{f"fixed_{w}": sum(x["fixed_acc"] for x in wrows if x["worker"] == w) / n for w in workers}},
        "routed_minus_fixed_mean": {"mean": sum(d_routed) / n, "ci95": bootstrap(d_routed)},
        "chosen_worker_fixed_acc_minus_mean": {"mean": sum(d_signal) / n, "ci95": bootstrap(d_signal)},
        "chosen_is_best_in_hindsight": sum(r["chosen_fixed_acc"] == r["fixed_best"] for r in qrows) / n,
        "ties": sum(1 for r in qrows if "," in r["tied"]),
        "routed_status": {s: sum(r["routed_status"] == s for r in qrows) for s in {r["routed_status"] for r in qrows}},
        "cost_usd": {"routed_per_question": mean("routed_cost_usd"),
                     "fixed_per_run": mean("fixed_cost_usd_per_run")},
    }
    out = exp / "analysis"
    out.mkdir(exist_ok=True)
    for name, rows in (("questions.csv", qrows), ("workers.csv", wrows)):
        with (out / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
