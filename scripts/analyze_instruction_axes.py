"""Descriptive, task-paired variant accuracy for designing instruction candidates."""
import json
import random
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from minpilot.data import longcot
from perturbation_consistency import longcot_math as math
from perturbation_consistency.longcot_nodes import parse_chain

OUT = ROOT / "outputs/analysis/2026-10-13_instruction-axes"
report = {}
for name, dirname in [("pre_pilot", "2026-10-12_longcot-segment-pilot-b"),
                      ("pilot", "2026-10-12_longcot-segment-routing-i")]:
    exp = ROOT / "outputs/experiments" / dirname
    targets = {t["target_id"]: t for t in map(json.loads, (exp / "targets.jsonl").read_text().splitlines())}
    prompts = list(map(json.loads, (exp / "prompts.jsonl").read_text().splitlines()))
    rows = list(map(json.loads, (exp / "results.jsonl").read_text().splitlines()))
    gold = {}
    for d in {t["difficulty"] for t in targets.values()}:
        refs = longcot.load_references("math", d)
        qs = {q.question_id: q for q in longcot.load_questions("math", d, template="linear")}
        for tid, t in targets.items():
            if t["difficulty"] == d:
                chain = parse_chain(t["question_id"], qs[t["question_id"]].prompt)
                gold[tid] = dict(zip(chain.requested, math.answer_parts(refs[t["question_id"]].answer)))[t["node"]]
    sent = Counter((p["target_id"], p["condition"]) for p in prompts)
    common = {tid for tid in targets if all(sent[tid, c] == 3 for c in
              ["repeat", "instruction", "surface", "methods", "avoid_first"])} if name == "pre_pilot" else set(targets)
    workers = sorted({r["worker"] for r in rows})
    keyed = {(r["target_id"], r["condition"], r["sample"], r["worker"]): r for r in rows}
    assert len(keyed) == len(rows)
    scored = []
    for p in prompts:
        for w in workers:
            r = keyed.get((p["target_id"], p["condition"], p["sample"], w), {})
            variant = p["condition"] + ":" + ("generated_strategy" if p["condition"] == "methods" else p["detail"])
            scored.append(dict(tid=p["target_id"], variant=variant, worker=w,
                               correct=int(math.same(gold[p["target_id"]], r.get("answer"))),
                               tokens=r.get("completion_tokens") or 0))
    report[name] = {"workers": workers, "all_targets": len(targets), "common_targets": len(common), "variants": {}}
    for variant in sorted({r["variant"] for r in scored}):
        rs = [r for r in scored if r["variant"] == variant and r["tid"] in common]
        per = defaultdict(list)
        base = defaultdict(list)
        for r in rs:
            per[r["tid"]].append(r["correct"])
        for r in scored:
            if r["variant"] == "repeat:plain" and r["tid"] in per:
                base[r["tid"]].append(r["correct"])
        diffs = [st.mean(per[t]) - st.mean(base[t]) for t in sorted(per)]
        rng = random.Random(0)
        boot = sorted(st.mean(rng.choices(diffs, k=len(diffs))) for _ in range(5000))
        report[name]["variants"][variant] = {
            "tasks": len(per), "calls": len(rs), "accuracy": st.mean(r["correct"] for r in rs),
            "accuracy_by_worker": {w: st.mean(r["correct"] for r in rs if r["worker"] == w) for w in workers},
            "mean_completion_tokens": st.mean(r["tokens"] for r in rs),
            "paired_delta_vs_repeat": st.mean(diffs), "ci95": [boot[125], boot[4874]]}
    # Per worker: task-level improvement/regression versus repeat mean, no selection.
    report[name]["instruction_task_differences"] = {}
    for variant in report[name]["variants"]:
        if not variant.startswith("instruction:"):
            continue
        out = {}
        for w in workers:
            vals = {}
            for tid in sorted(common):
                a = [r["correct"] for r in scored if r["tid"] == tid and r["worker"] == w and r["variant"] == variant]
                b = [r["correct"] for r in scored if r["tid"] == tid and r["worker"] == w and r["variant"] == "repeat:plain"]
                vals[tid] = st.mean(a) - st.mean(b)
            out[w] = {"improved": sum(v > 0 for v in vals.values()), "worsened": sum(v < 0 for v in vals.values()),
                      "equal": sum(v == 0 for v in vals.values())}
        report[name]["instruction_task_differences"][variant] = out
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
