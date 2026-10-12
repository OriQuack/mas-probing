#!/usr/bin/env python
"""Segment routing, step 4: does a worker's segment consistency pick a worker that does well on the rest? (reads gold)

  python scripts/analyze_segment_routing.py outputs/experiments/<date>_longcot-segment-routing [--out DIR]

Probe level, per condition (repeat / instruction / surface) and for all 15 samples pooled: a pair is (target, worker);
consistency = largest equivalent-answer group / samples sent; AUROC of consistency for "modal answer correct";
unanimous share; targets whose top consistency is tied.

Chain level: a run (target, worker, rep) scores the share of the requested nodes from the segment's last node on that
it got right (a run stops at its first wrong requested node, so the later ones count wrong) and whether it got all of
them. A worker's score on a target is the mean over its reps. Selection per condition: the most consistent worker
(ties: mean of the tied workers), a random worker (mean of all), the best in hindsight, and each worker always.
Targets are weighted equally; 95% intervals by resampling targets. Writes pairs.csv, runs.csv and summary.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.data import longcot  # noqa: E402
from perturbation_consistency import longcot_math, segment_routing as sr  # noqa: E402
from perturbation_consistency.longcot_nodes import parse_chain  # noqa: E402

POOLED = "all_15"


def auroc(scores: list[float], labels: list[bool]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def interval(values_by_target: dict[str, float], n: int = 2000, seed: int = 0) -> list[float]:
    keys, rng, out = sorted(values_by_target), random.Random(seed), []
    for _ in range(n):
        out.append(statistics.mean(values_by_target[rng.choice(keys)] for _ in keys))
    out.sort()
    return [round(out[int(0.025 * n)], 4), round(out[int(0.975 * n) - 1], 4)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    exp = args.experiment
    targets = {t["target_id"]: t for t in map(json.loads, (exp / "targets.jsonl").read_text().splitlines())}
    prompts = [json.loads(x) for x in (exp / "prompts.jsonl").read_text().splitlines()]
    results = [json.loads(x) for x in (exp / "results.jsonl").read_text().splitlines()]
    runs = [json.loads(x) for f in sorted(exp.glob("continuation*.jsonl")) for x in f.read_text().splitlines()]
    sent = defaultdict(int)
    for p in prompts:
        sent[(p["target_id"], p["condition"])] += 1
        sent[(p["target_id"], POOLED)] += 1
    gold = {}
    for d in {t["difficulty"] for t in targets.values()}:
        refs = longcot.load_references("math", d)
        prompt_of = {q.question_id: q.prompt for q in longcot.load_questions("math", d, template="linear")}
        for tid, t in targets.items():
            if t["difficulty"] == d:
                chain = parse_chain(t["question_id"], prompt_of[t["question_id"]])
                gold[tid] = dict(zip(chain.requested, longcot_math.answer_parts(refs[t["question_id"]].answer)))[
                    t["node"]]
    workers = sorted({r["worker"] for r in results})
    conditions = list(sr.CONDITIONS) + [POOLED]

    by = defaultdict(list)
    for r in results:
        by[(r["target_id"], r["condition"], r["worker"])].append(r)
        by[(r["target_id"], POOLED, r["worker"])].append(r)
    pairs = []
    for (tid, cond, w), rs in sorted(by.items()):
        n = sent[(tid, cond)]
        answers = [r["answer"] for r in rs] + [None] * (n - len(rs))
        groups = [g for g in longcot_math.group(answers) if answers[g[0]] is not None]
        modal = answers[groups[0][0]] if groups else None
        pairs.append({"target_id": tid, "difficulty": targets[tid]["difficulty"], "condition": cond, "worker": w,
                      "samples": n, "consistency": len(groups[0]) / n if groups else 0.0,
                      "modal_correct": int(modal is not None and longcot_math.same(gold[tid], modal)),
                      "sample_acc": sum(longcot_math.same(gold[tid], a) for a in answers) / n})

    chain_score, chain_all = defaultdict(list), defaultdict(list)
    for r in runs:
        chain_score[(r["target_id"], r["worker"])].append(r["requested_correct"] / r["requested_total"])
        chain_all[(r["target_id"], r["worker"])].append(float(r["requested_correct"] == r["requested_total"]))
    score = {k: statistics.mean(v) for k, v in chain_score.items()}
    full = {k: statistics.mean(v) for k, v in chain_all.items()}
    complete = [tid for tid in targets if all((tid, w) in score for w in workers)]

    summary = {"experiment": str(exp), "equivalence_version": longcot_math.EQUIVALENCE_VERSION, "workers": workers,
               "targets": len(targets), "targets_with_every_chain": len(complete), "runs": len(runs),
               "probe": {}, "selection": {}, "worker_chain": {}}
    for cond in conditions:
        cr = [p for p in pairs if p["condition"] == cond]
        per = defaultdict(dict)
        for p in cr:
            per[p["target_id"]][p["worker"]] = p
        ties = sum(len([x for x in ws.values() if x["consistency"] == max(y["consistency"] for y in ws.values())]) > 1
                   for ws in per.values())
        summary["probe"][cond] = {
            "pairs": len(cr), "mean_consistency": round(statistics.mean(p["consistency"] for p in cr), 4),
            "unanimous_share": round(sum(p["consistency"] == 1.0 for p in cr) / len(cr), 4),
            "modal_acc": round(statistics.mean(p["modal_correct"] for p in cr), 4),
            "auroc_consistency_for_modal_correct": auroc([p["consistency"] for p in cr],
                                                         [bool(p["modal_correct"]) for p in cr]),
            "targets_with_tied_top_worker": f"{ties}/{len(per)}"}
        for metric, table in (("requested_share", score), ("all_requested", full)):
            picks = defaultdict(dict)
            for tid in complete:
                ws = per[tid]
                top = max(x["consistency"] for x in ws.values())
                tied = [w for w, x in ws.items() if x["consistency"] == top]
                picks["most_consistent"][tid] = statistics.mean(table[(tid, w)] for w in tied)
                picks["random_worker"][tid] = statistics.mean(table[(tid, w)] for w in workers)
                picks["best_in_hindsight"][tid] = max(table[(tid, w)] for w in workers)
                for w in workers:
                    picks[f"always_{w}"][tid] = table[(tid, w)]
            summary["selection"].setdefault(cond, {})[metric] = {
                k: {"mean": round(statistics.mean(v.values()), 4), "ci95": interval(v)} for k, v in picks.items()}
    for w in workers:
        cons = [p["consistency"] for p in pairs if p["condition"] == POOLED and p["worker"] == w]
        summary["worker_chain"][w] = {
            "requested_share": round(statistics.mean(score[(t, w)] for t in complete), 4),
            "all_requested": round(statistics.mean(full[(t, w)] for t in complete), 4),
            "segment_sample_acc": round(statistics.mean(p["sample_acc"] for p in pairs
                                                        if p["condition"] == POOLED and p["worker"] == w), 4),
            "mean_consistency_all_15": round(statistics.mean(cons), 4)}

    out = args.out or exp / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "pairs.csv").open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(pairs[0]))
        wr.writeheader()
        wr.writerows(pairs)
    with (out / "runs.csv").open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["target_id", "worker", "rep", "status", "requested_correct",
                                           "requested_total", "calls", "cost_usd"])
        wr.writeheader()
        for r in runs:
            wr.writerow({k: r.get(k) for k in wr.fieldnames} | {"calls": len(r["calls"])})
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
