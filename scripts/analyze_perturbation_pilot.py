#!/usr/bin/env python
"""Perturbation pilot, step 3: per condition, is worker consistency informative? (reads gold answers)

  python scripts/analyze_perturbation_pilot.py outputs/experiments/<date>_longcot-perturbation-pilot [--out DIR]

A pair is (target node, worker) within one condition. Per condition:
- consistency: largest equivalent-answer group / samples sent (a missing answer is its own group);
- unanimous share, and the share of targets whose top consistency is shared by several workers (ties);
- accuracy of single samples and of each pair's modal answer; sample accuracy in unanimous vs other pairs, and the
  AUROC of consistency for "modal answer correct" over pairs;
- selection: per target the most consistent worker (ties averaged) vs a random worker vs the best worker in
  hindsight, by that worker's sample accuracy in the condition;
- method labels: distinct `method =` labels per pair (lower-cased, first four words);
- tokens and cost per call.
Writes pairs.csv and summary.json (default: <experiment>/analysis).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.data import longcot  # noqa: E402
from perturbation_consistency import longcot_math, perturb  # noqa: E402
from perturbation_consistency.longcot_nodes import parse_chain  # noqa: E402


def auroc(scores: list[float], labels: list[bool]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def label(method: str | None) -> str | None:
    return " ".join(re.findall(r"[a-z0-9]+", method.lower())[:4]) if method else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--exclude", type=Path, default=None,
                    help='JSON {"exclude": [{"target_id", "condition", "sample", "reason"}]}: prompts dropped from '
                         "the analysis after a review (default: <experiment>/exclusions.json if present)")
    args = ap.parse_args()
    exp = args.experiment
    exclude_path = args.exclude or (exp / "exclusions.json" if (exp / "exclusions.json").exists() else None)
    excluded = json.loads(exclude_path.read_text())["exclude"] if exclude_path else []
    drop = {(e["target_id"], e["condition"], e["sample"]) for e in excluded}
    targets = {t["target_id"]: t for t in map(json.loads, (exp / "targets.jsonl").read_text().splitlines())}
    results = [r for r in map(json.loads, (exp / "results.jsonl").read_text().splitlines())
               if (r["target_id"], r["condition"], r["sample"]) not in drop]
    prompts = [p for p in map(json.loads, (exp / "prompts.jsonl").read_text().splitlines())
               if (p["target_id"], p["condition"], p["sample"]) not in drop]
    sent = defaultdict(int)  # (target, condition) -> prompts per worker
    for p in prompts:
        sent[(p["target_id"], p["condition"])] += 1
    gold = {}
    for difficulty in {t["difficulty"] for t in targets.values()}:
        refs = longcot.load_references("math", difficulty)
        prompt_of = {q.question_id: q.prompt for q in longcot.load_questions("math", difficulty)}
        for tid, t in targets.items():
            if t["difficulty"] == difficulty:
                chain = parse_chain(t["question_id"], prompt_of[t["question_id"]])
                parts = longcot_math.answer_parts(refs[t["question_id"]].answer)
                gold[tid] = dict(zip(chain.requested, parts))[t["node"]]

    by_pair = defaultdict(list)
    for r in results:
        by_pair[(r["target_id"], r["condition"], r["worker"])].append(r)
    workers = sorted({r["worker"] for r in results})
    rows = []
    for (tid, cond, w), rs in sorted(by_pair.items()):
        n = sent[(tid, cond)]
        answers = [r["answer"] for r in rs] + [None] * (n - len(rs))
        groups = [g for g in longcot_math.group(answers) if answers[g[0]] is not None]
        modal = answers[groups[0][0]] if groups else None
        correct = [longcot_math.same(gold[tid], a) for a in answers]
        labels = {label(r.get("method")) for r in rs} - {None}
        rows.append({"target_id": tid, "kind": targets[tid]["kind"], "difficulty": targets[tid]["difficulty"],
                     "condition": cond, "worker": w, "samples": n, "answered": sum(a is not None for a in answers),
                     "consistency": len(groups[0]) / n if groups else 0.0,
                     "modal_correct": int(modal is not None and longcot_math.same(gold[tid], modal)),
                     "sample_acc": sum(correct) / n, "distinct_methods": len(labels),
                     "completion_tokens": mean([r.get("completion_tokens") for r in rs]),
                     "cost_usd": sum(r.get("cost_usd") or 0.0 for r in rs)})

    summary = {"experiment": str(exp), "equivalence_version": longcot_math.EQUIVALENCE_VERSION, "workers": workers,
               "excluded_prompts": excluded, "conditions": {}}
    for cond in perturb.CONDITIONS:
        cr = [r for r in rows if r["condition"] == cond]
        if not cr:
            continue
        per_target = defaultdict(dict)
        for r in cr:
            per_target[r["target_id"]][r["worker"]] = r
        ties, chosen, rand, best = 0, [], [], []
        for tid, ws in per_target.items():
            top = max(x["consistency"] for x in ws.values())
            tied = [x for x in ws.values() if x["consistency"] == top]
            ties += len(tied) > 1
            chosen.append(statistics.mean(x["sample_acc"] for x in tied))
            rand.append(statistics.mean(x["sample_acc"] for x in ws.values()))
            best.append(max(x["sample_acc"] for x in ws.values()))
        unanimous = [r for r in cr if r["consistency"] == 1.0]
        other = [r for r in cr if r["consistency"] < 1.0]
        calls = sum(r["samples"] for r in cr)
        summary["conditions"][cond] = {
            "pairs": len(cr), "targets": len(per_target),
            "mean_consistency": mean(r["consistency"] for r in cr),
            "unanimous_share": round(len(unanimous) / len(cr), 4),
            "targets_with_tied_top_worker": f"{ties}/{len(per_target)}",
            "sample_acc": mean(r["sample_acc"] for r in cr), "modal_acc": mean(r["modal_correct"] for r in cr),
            "sample_acc_unanimous": mean(r["sample_acc"] for r in unanimous),
            "sample_acc_not_unanimous": mean(r["sample_acc"] for r in other),
            "auroc_consistency_for_modal_correct": auroc([r["consistency"] for r in cr],
                                                         [bool(r["modal_correct"]) for r in cr]),
            "selection_sample_acc": {"most_consistent": mean(chosen), "random_worker": mean(rand),
                                     "best_in_hindsight": mean(best)},
            "by_kind": {k: {"mean_consistency": mean(r["consistency"] for r in cr if r["kind"] == k),
                            "sample_acc": mean(r["sample_acc"] for r in cr if r["kind"] == k)}
                        for k in ("first", "middle")},
            "mean_distinct_methods_per_pair": mean(r["distinct_methods"] for r in cr),
            "completion_tokens_per_call": mean(r["completion_tokens"] for r in cr),
            "cost_usd": round(sum(r["cost_usd"] for r in cr), 4),
            "cost_usd_per_call": round(sum(r["cost_usd"] for r in cr) / calls, 6) if calls else None,
        }
    prep = [json.loads(x) for x in (exp / "prep.jsonl").read_text().splitlines()]
    summary["approach_mentions_gold"] = [  # leak check; gold values shorter than 3 characters match too much
        p["target_id"] for p in prep for a in p.get("approaches") or []
        if len(g := str(gold[p["target_id"]]).replace(" ", "")) >= 3 and g in a.replace(" ", "")]
    out = args.out or exp / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "pairs.csv").open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
