#!/usr/bin/env python
"""Check the MoNaCo answer clusterer on published answers before it selects instructions: prepare/cluster/analyze.

For pool questions outside the seeded instruction-selection sample, the final `Answers:` lines of every published
run are clustered in one call per question with the whole-answer prompt (cluster version 1; version 2 groups items). Published GPT-4.1 judge scores label
answer pairs: two fully correct answers should share a group, a fully correct and a zero-score answer should not.
The normalized-answer-set rule is scored on the same pairs as a baseline."""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import random
import re
import subprocess
import sys
from collections import defaultdict
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
read_rows, write_json, append, digest, now = runner.read_rows, runner.write_json, runner.append, runner.digest, runner.now

QUESTIONS, SEED = 100, 0
SAMPLE_TARGETS, SAMPLE_SEED = 20, 0  # the v1-v6 seeded instruction-selection sample, kept out of this check
PUBLISHED_ANSWER = re.compile(r"(?im)^\W*answers?\W*:(.*)$")
RULE_ITEM_SPLIT = re.compile(r"###|;|,(?!\d{3})")


def published_answer(output: str) -> str | None:
    """Text of the last `Answers:` line of a published output, without markdown emphasis."""
    lines = PUBLISHED_ANSWER.findall(output)
    return (lines[-1].strip().strip("*").strip()[:1000] or None) if lines else None


def rule_key(text: str) -> frozenset:
    """Baseline: comma/semicolon/### items of a free-text answer, as normalized values. Approximate, since the
    published answers are not the JSON lists the probes return."""
    return frozenset(mis.normalize_value(x.strip().rstrip(".")) for x in RULE_ITEM_SPLIT.split(text) if x.strip())


def implementation_hashes():
    return {**runner.implementation_hashes(), str(Path(__file__).resolve().relative_to(ROOT)): digest(Path(__file__))}


def prepare(args):
    eligible, questions = runner.pool(args.data_root)
    targets = set(random.Random(SAMPLE_SEED).sample(eligible, SAMPLE_TARGETS))
    chosen = sorted(random.Random(SEED).sample(sorted(set(eligible) - targets), args.questions))
    inputs = []
    for ex in chosen:
        answers = [{"run": r["run"], "text": t, "judge_score": r["judge_score"]}
                   for r in monaco.load_published_answers(ex, args.data_root)
                   if (t := published_answer(r["output"])) is not None]
        inputs.append({"target_id": f"monaco_{ex}", "ex_num": ex, "question": questions[ex], "answers": answers})
    if args.dry_run:
        print(json.dumps({"questions": len(inputs), "answers": sum(len(i["answers"]) for i in inputs),
                          "distinct_texts": sum(len({a["text"] for a in i["answers"]}) for i in inputs)}, indent=2))
        print(mis.cluster_prompt(inputs[0]["question"], [a["text"] for a in inputs[0]["answers"]], "preview",
                                 mis.ANSWER_CLUSTER_PROMPT)[0])
        return
    exp = args.experiment
    exp.mkdir(parents=True, exist_ok=True)
    if (exp / "manifest.json").exists():
        raise ValueError("experiment already prepared; use another directory")
    (exp / "inputs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in inputs))
    source = json.loads((args.data_root / "SOURCE.json").read_text())
    write_json(exp / "manifest.json", experiment_manifest(
        purpose="Validate the MoNaCo answer clusterer against published judge scores before instruction selection",
        run_roots=["cluster_validation"], harness="scripts/validate_monaco_answer_clustering.py",
        experiment_version=mis.VERSION, cluster_version=1, cluster_prompt="whole answers",
        dataset={"name": "MoNaCo", "origin": source["origin"], "revision": source["revision"],
                 "answers": "final `Answers:` line of every published run with a text output"},
        questions={"pool_size": len(eligible), "excluded": "seeded instruction-selection sample",
                   "sample": args.questions, "seed": SEED},
        clusterer=mis.CLUSTERER, models={mis.CLUSTERER: get_spec(mis.CLUSTERER).identity()},
        labels="pairs of distinct answer texts; published GPT-4.1 judge_score: both 1 -> same, 1 and 0 -> "
               "different, other pairs and texts scored differently across runs unlabelled",
        input_hashes={"inputs.jsonl": digest(exp / "inputs.jsonl")}, implementation_hashes=implementation_hashes(),
        git_commit=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip(), created_at=now()))
    print(f"Prepared {len(inputs)} questions: {exp}")


def load(exp, calls: bool):
    """Clustering calls need the prepared implementation and model; analysis records its own hashes instead."""
    manifest = json.loads((exp / "manifest.json").read_text())
    if calls and (manifest["implementation_hashes"] != implementation_hashes()
                  or manifest["models"] != {mis.CLUSTERER: get_spec(mis.CLUSTERER).identity()}):
        raise ValueError("implementation or model changed: use a new experiment")
    if digest(exp / "inputs.jsonl") != manifest["input_hashes"]["inputs.jsonl"]:
        raise ValueError("inputs changed")
    return manifest, read_rows(exp / "inputs.jsonl")


def cluster(args, inputs):
    path = args.experiment / "clusters.jsonl"
    todo = set(mis.pending([i["target_id"] for i in inputs], read_rows(path), lambda r: r["target_id"]))
    jobs = [i for i in inputs if i["target_id"] in todo]
    if not jobs:
        print("All questions clustered; no calls.")
        return
    stage = runner.Stage(args, "cluster_validation", [mis.CLUSTERER])

    def job(i):
        with stage.lock:
            client, trace = stage.client(runner.key_of(i["target_id"]), mis.CLUSTERER)
        with trace.tags(stage="answer_clustering_validation", target_id=i["target_id"]):
            rec = mis.cluster(client, i["question"], [a["text"] for a in i["answers"]], f"{SEED}:{i['target_id']}",
                              template=mis.ANSWER_CLUSTER_PROMPT)
        with stage.lock:
            append(path, {"target_id": i["target_id"], **rec, "cost_usd": trace.run_scope.cost_usd})
    try:
        runner.run_jobs(args, jobs, job)
    finally:
        stage.close()


def labelled_pairs(answers: list[dict]):
    """Distinct answer texts in pairs, labelled by their published scores: both 1 -> same, 1 and 0 -> different.
    A text that received different scores in different runs is left out."""
    score, conflict = {}, set()
    for a in answers:
        if score.setdefault(a["text"], a["judge_score"]) != a["judge_score"]:
            conflict.add(a["text"])
    for x, y in itertools.combinations(sorted(set(score) - conflict), 2):
        scores = {score[x], score[y]}
        if scores == {1.0}:
            yield x, y, "same"
        elif scores == {0.0, 1.0}:
            yield x, y, "different"


def analyze(args, inputs):
    clusters = mis.latest(read_rows(args.experiment / "clusters.jsonl"), lambda r: r["target_id"])
    refs = monaco.load_references(args.data_root)
    counts = defaultdict(lambda: defaultdict(int))
    error_questions = defaultdict(set)
    examples = {"same": [], "different": []}
    for i in inputs:
        c = clusters.get(i["target_id"], {})
        if c.get("status") != "ok":
            counts["all"]["questions_failed"] += 1
            continue
        kind = mis.judge_kind(refs[i["ex_num"]].answers)
        shown = set()
        for x, y, label in labelled_pairs(i["answers"]):
            luna_same = c["labels"][x] is not None and c["labels"][x] == c["labels"][y]
            rule_same = rule_key(x) == rule_key(y)
            for scope in ("all", kind):
                counts[scope][f"{label}_pairs"] += 1
                counts[scope][f"{label}_luna_correct"] += luna_same == (label == "same")
                counts[scope][f"{label}_rule_correct"] += rule_same == (label == "same")
            if luna_same != (label == "same"):
                error_questions[label].add(i["target_id"])
                if label not in shown:  # one example per question and label
                    shown.add(label)
                    examples[label].append({"target_id": i["target_id"], "question": i["question"], "a": x, "b": y,
                                            "groups": [c["labels"][x], c["labels"][y]]})
        counts["all"]["no_answer_texts"] += sum(v is None for v in c["labels"].values())
        counts["all"]["distinct_texts"] += len(c["labels"])
        counts["all"]["questions_ok"] += 1
    summary = {}
    for scope, cnt in counts.items():
        row = dict(cnt)
        for label in ("same", "different"):
            if cnt[f"{label}_pairs"]:
                for m in ("luna", "rule"):
                    row[f"{label}_{m}_accuracy"] = cnt[f"{label}_{m}_correct"] / cnt[f"{label}_pairs"]
        summary[scope] = row
    summary["questions_with_luna_errors"] = {k: len(v) for k, v in error_questions.items()}
    summary["error_examples"] = examples
    summary["analysis_implementation_hashes"] = implementation_hashes()
    summary["cost_usd"] = sum(runner.trace_costs(args.experiment / j["trace"])["recorded_request_cost"]
                              for j in read_rows(args.experiment / "cluster_validation_jobs.jsonl"))
    summary["note"] = ("Pairs of distinct answer texts. Labels come from published GPT-4.1 judge scores, which grade "
                       "correctness against the gold rather than equivalence of two answers, and are noisy; the rule "
                       "baseline splits free-text answers on commas, so it is weaker here than on JSON probe answers.")
    write_json(args.experiment / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "error_examples"}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["prepare", "cluster", "analyze"])
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--data-root", type=Path, default=monaco.MONACO_ROOT)
    ap.add_argument("--questions", type=int, default=QUESTIONS)
    ap.add_argument("--session-cost-usd", type=float)
    ap.add_argument("--run-cost-usd", type=float)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    args.batch = False
    if args.stage == "prepare":
        prepare(args)
        return
    with runner.exclusive(args.experiment):
        _, inputs = load(args.experiment, calls=args.stage == "cluster")
        cluster(args, inputs) if args.stage == "cluster" else analyze(args, inputs)


if __name__ == "__main__":
    main()
