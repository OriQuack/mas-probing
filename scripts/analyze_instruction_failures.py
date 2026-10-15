#!/usr/bin/env python
"""Post-hoc diagnostics for a finished LongCoT instruction-selection experiment (reads gold-scored records only)

  python scripts/analyze_instruction_failures.py outputs/experiments/<date>_instruction-selection-...-continuation

Downstream score of a rollout = share of requested nodes after the first bundle answered correctly (unreached count
wrong); a candidate's score on a task is the mean over reps; tasks are weighted equally.

- Decomposes selected - naive into instruction effect (mean of the three non-naive candidates - naive) and selection
  effect (selected - that mean), with 95% intervals by resampling tasks.
- Same-correct-start subset: tasks whose four candidates start from one answer and that answer is correct.
- Per candidate: wrong share among reached downstream requested nodes, non-ok calls per call, completion tokens
  relative to naive on the same (task, node), and answers that declare the problem undefined.
- Selection signal: within-task correlation of (candidate - naive) agreement with (candidate - naive) downstream score;
  first-bundle correctness by modal support.
No model calls. Prints JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

CANDIDATES = ["naive", "analogical", "clarify", "local_check"]
UNDEFINED = re.compile(r"undefined|no such|does not exist|not determined|underdetermined|no solution|not defined|"
                       r"cannot be determined", re.I)


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def interval(values: list[float], seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    boot = sorted(st.mean(rng.choices(values, k=len(values))) for _ in range(5000))
    return [boot[125], boot[4874]]


def corr(xs: list[float], ys: list[float]) -> float:
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return num / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment", type=Path)
    exp = ap.parse_args().experiment
    runs = load(exp / "continuation.jsonl")
    selections = {s["target_id"]: s for s in load(exp / "selection.jsonl")}
    by = defaultdict(list)
    for r in runs:
        by[(r["target_id"], r["candidate"])].append(r)

    def first_ok(r: dict) -> bool:
        return r["requested"][next(iter(r["requested"]))] == "correct"

    def downstream(tid: str, cand: str) -> float:
        rr = by[(tid, cand)]
        later = list(rr[0]["requested"])[1:]
        return st.mean(st.mean(r["requested"][n] == "correct" for n in later) for r in rr)

    tasks = sorted(selections)
    chosen = {t: selections[t]["primary"]["candidate"] for t in tasks}
    instr, sel = [], []
    for t in tasks:
        others = st.mean(downstream(t, c) for c in CANDIDATES[1:])
        instr.append(others - downstream(t, "naive"))
        sel.append(downstream(t, chosen[t]) - others)
    total = [a + b for a, b in zip(instr, sel)]
    out = {"tasks": len(tasks), "decomposition": {
        name: {"mean": st.mean(v), "ci95": interval(v)}
        for name, v in [("selected_minus_naive", total), ("instruction_effect", instr), ("selection_effect", sel)]}}

    same = [t for t in tasks if len({selections[t]["starts"][c]["answer"] for c in CANDIDATES}) == 1
            and all(first_ok(r) for c in CANDIDATES for r in by[(t, c)])]
    out["same_correct_start"] = {"tasks": len(same), **{
        c: {"delta_vs_naive": st.mean(d), "wins": sum(x > 0 for x in d), "losses": sum(x < 0 for x in d)}
        for c in CANDIDATES[1:] for d in [[downstream(t, c) - downstream(t, "naive") for t in same]]}}

    per = {}
    for c in CANDIDATES:
        rr = [r for r in runs if r["candidate"] == c]
        reached = [r["requested"][n] for r in rr for n in list(r["requested"])[1:] if r["requested"][n] != "not_reached"]
        calls = [x for r in rr for x in r["calls"]]
        per[c] = {"reached_downstream": len(reached), "wrong_given_reached": reached.count("wrong") / len(reached),
                  "calls": len(calls), "non_ok_per_call": sum(x["status"] != "ok" for x in calls) / len(calls),
                  "undefined_answer_per_call": sum(bool(x["answer"] and UNDEFINED.search(x["answer"]))
                                                   for x in calls) / len(calls),
                  "rollouts_with_undefined": Counter(
                      "ok" if r["status"] == "ok" else "failed" for r in rr
                      if any(x["answer"] and UNDEFINED.search(x["answer"]) for x in r["calls"]))}
    tokens = defaultdict(list)
    for line in (exp / "continuation_jobs.jsonl").open():
        trace = exp / json.loads(line)["trace"]
        f = trace / "llm_calls.jsonl"
        if not f.exists():
            continue
        for rec in map(json.loads, f.open()):
            n = (rec.get("usage") or {}).get("completion_tokens")
            if rec["status"] != "started" and n:
                tokens[(rec["target_id"], rec["node"], rec["candidate"])].append(n)
    for c in CANDIDATES[1:]:
        ratios = [st.median(v) / st.median(tokens[(t, n, "naive")]) for (t, n, k), v in tokens.items()
                  if k == c and tokens.get((t, n, "naive"))]
        per[c]["median_token_ratio_vs_naive"] = st.median(ratios)
    out["per_candidate"] = per

    xs, ys = [], []
    for t in tasks:
        sc = selections[t]["scores"]
        for c in CANDIDATES[1:]:
            xs.append(sc[c]["agreement"] - sc["naive"]["agreement"])
            ys.append(downstream(t, c) - downstream(t, "naive"))
    support = defaultdict(list)
    for t in tasks:
        for c in CANDIDATES:
            support[selections[t]["scores"][c]["support"]].append(first_ok(by[(t, c)][0]))
    out["selection"] = {
        "chosen": Counter(chosen.values()),
        "naive_in_top_tie": sum("naive" in selections[t]["primary"]["tied_candidates"] for t in tasks),
        "agreement_vs_downstream_corr": corr(xs, ys), "pairs": len(xs),
        "first_bundle_correct_by_support": {k: [len(v), st.mean(v)] for k, v in sorted(support.items())}}
    out["by_difficulty"] = {d: {"tasks": len(ts), "selected": st.mean(downstream(t, chosen[t]) for t in ts),
                                "naive": st.mean(downstream(t, "naive") for t in ts)}
                            for d in ["easy", "medium", "hard"] for ts in [[t for t in tasks if f"_{d}_" in t]]}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
