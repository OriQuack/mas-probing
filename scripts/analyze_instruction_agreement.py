"""Exploratory instruction selection from existing cross-worker probe agreement."""
import csv
import json
import random
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from minpilot.data import longcot
from perturbation_consistency import longcot_math as math
from perturbation_consistency.longcot_nodes import parse_chain

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "outputs/experiments/2026-10-12_longcot-segment-routing-i"
OUT = ROOT / "outputs/analysis/2026-10-13_instruction-worker-agreement"
WORKERS = ["haiku-medium", "luna-medium", "flash-lite-high"]
CONDS = ["naive", "zero_shot_cot", "plan_and_solve", "step_back", "analogical", "verify"]
targets = [json.loads(x) for x in (EXP / "targets.jsonl").read_text().splitlines()]
results = [json.loads(x) for x in (EXP / "results.jsonl").read_text().splitlines()]
gold = {}
for d in {t["difficulty"] for t in targets}:
    refs = longcot.load_references("math", d)
    questions = {q.question_id: q for q in longcot.load_questions("math", d, template="linear")}
    for t in targets:
        if t["difficulty"] == d:
            chain = parse_chain(t["question_id"], questions[t["question_id"]].prompt)
            gold[t["target_id"]] = dict(zip(chain.requested, math.answer_parts(refs[t["question_id"]].answer)))[t["node"]]
by = {}
for r in results:
    if r["condition"] == "instruction" or (r["condition"] == "repeat" and r["sample"] == 0):
        c = "naive" if r["condition"] == "repeat" else r["detail"]
        key = (r["target_id"], c, r["worker"])
        assert key not in by, key
        by[key] = r
rows = []
for t in targets:
    tid = t["target_id"]
    for c in CONDS:
        answers = [by[tid, c, w]["answer"] for w in WORKERS]
        groups = [g for g in math.group(answers) if answers[g[0]] is not None]
        support = len(groups[0]) if groups else 0
        modal = answers[groups[0][0]] if groups else None
        rows.append(dict(target_id=tid, instruction=c, agreement=support / 3,
                         modal_tied=len(groups) > 1 and len(groups[1]) == support,
                         modal_correct=int(modal is not None and math.same(gold[tid], modal)),
                         haiku_correct=int(math.same(gold[tid], answers[0])),
                         mean_worker_correct=st.mean(math.same(gold[tid], a) for a in answers)))

def auc(rs, label):
    pos = [r["agreement"] for r in rs if r[label]]
    neg = [r["agreement"] for r in rs if not r[label]]
    return sum((a > b) + .5 * (a == b) for a in pos for b in neg) / (len(pos) * len(neg))

summary = {"targets": len(targets), "candidate_instructions": CONDS,
           "naive_definition": "repeat sample 0, fixed before this analysis",
           "auroc_modal_correct": auc(rows, "modal_correct"),
           "auroc_haiku_correct": auc(rows, "haiku_correct"),
           "by_agreement": {}, "instruction_haiku_accuracy": {}, "selection": {}}
for level in sorted({r["agreement"] for r in rows}):
    rs = [r for r in rows if r["agreement"] == level]
    summary["by_agreement"][str(level)] = {"n": len(rs), **{k: st.mean(r[k] for r in rs)
        for k in ["modal_correct", "haiku_correct", "mean_worker_correct"]}}
for c in CONDS:
    summary["instruction_haiku_accuracy"][c] = st.mean(r["haiku_correct"] for r in rows if r["instruction"] == c)
for candidates, name in [(CONDS, "six_candidates"), (CONDS[1:], "five_instructions")]:
    per = []
    for t in targets:
        rs = [r for r in rows if r["target_id"] == t["target_id"] and r["instruction"] in candidates]
        top = max(r["agreement"] for r in rs)
        tied = [r for r in rs if r["agreement"] == top]
        naive = next(r["haiku_correct"] for r in rows if r["target_id"] == t["target_id"] and r["instruction"] == "naive")
        per.append(dict(target_id=t["target_id"], tied=len(tied),
                        selected=st.mean(r["haiku_correct"] for r in tied),
                        random=st.mean(r["haiku_correct"] for r in rs), naive=naive,
                        oracle=max(r["haiku_correct"] for r in rs)))
    metrics = {k: st.mean(r[k] for r in per) for k in ["selected", "random", "naive", "oracle"]}
    metrics["top_tie_histogram"] = dict(Counter(r["tied"] for r in per))
    metrics["unique_top_tasks"] = sum(r["tied"] == 1 for r in per)
    for baseline in ["random", "naive"]:
        diffs = [r["selected"] - r[baseline] for r in per]
        rng = random.Random(0)
        boot = sorted(st.mean(rng.choices(diffs, k=len(diffs))) for _ in range(10000))
        metrics["delta_vs_" + baseline] = {"mean": st.mean(diffs), "task_bootstrap_ci95": [boot[250], boot[9749]]}
    summary["selection"][name] = metrics
summary["limitations"] = ["Exploratory, same probe answers used for selection and scoring; not independent validation.",
    "Ties averaged: expected uniform random tie-breaking, not an executed policy.",
    "Modal ties use first worker (haiku); interpret modal AUROC cautiously.",
    "No instruction-specific continuation data: cannot evaluate downstream benefit."]
OUT.mkdir(parents=True, exist_ok=True)
with (OUT / "instruction_pairs.csv").open("w") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
