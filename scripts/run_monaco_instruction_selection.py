#!/usr/bin/env python
"""MoNaCo oracle-setting instruction selection:
prepare/validate-judge/import-candidates/probe/split/cluster/select/execute/judge/analyze.

Candidates are authored outside this runner from the question text only and imported with review notes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import random
import subprocess
import sys
import tarfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from minpilot.artifacts import experiment_manifest
from minpilot.data import monaco
from minpilot.llm.client import http_transport
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import BudgetExceeded
from perturbation_consistency import monaco_instruction_selection as mis

# Stage budgets, journals and cost reconstruction are those of the LongCoT runner, loaded without modifying it.
_spec = importlib.util.spec_from_file_location("instruction_runner", ROOT / "scripts/run_instruction_selection.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
read_rows, write_json, append, digest, now = base.read_rows, base.write_json, base.append, base.digest, base.now
trace_costs, exclusive = base.trace_costs, base.exclusive

SEED, MAX_DOC_CHARS = 0, 40_000
STAGES = ("validate_judge", "probe", "split", "cluster", "execute", "judge")
# Stratified targets (analysis-side, reads published judge scores and the gold's shape, never shown to a model):
# the mean published GPT-4.1 score of the GPT-4o and Llama-3.1-405B oracle runs, 0 and 1 excluded.
ORACLE_RUNS = (monaco.ORACLE_RUN, "language_models_predictions/llama31_405b_instruct_rag_oracle")
LIST_BANDS = ((0., .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.))
ALLOCATION = {**{f"list_{lo:.1f}-{hi:.1f}": 6 for lo, hi in LIST_BANDS},
              "single_one_model_correct": 10, "single_partial": 10}
MAX_LIST_GOLD_VALUES = 100


class Stage(base.Stage):
    """The LongCoT stage, with this module's `http_transport` so offline tests can replace it."""
    def __init__(self, args, stage, workers):
        base.http_transport = http_transport
        super().__init__(args, stage, workers)


def implementation_hashes():
    return {str(p.relative_to(ROOT)): digest(p) for p in
            [Path(__file__).resolve(), ROOT / "src/perturbation_consistency/monaco_instruction_selection.py",
             ROOT / "src/perturbation_consistency/instruction_selection.py",
             ROOT / "scripts/run_instruction_selection.py", ROOT / "src/minpilot/data/monaco.py"]}


def model_keys():
    return tuple(dict.fromkeys((*mis.WORKERS, mis.JUDGE, mis.SPLITTER, mis.CLUSTERER)))


def pool(root):
    """Questions with oracle documents, labelled time-independent, documents at most MAX_DOC_CHARS in total."""
    time_dependent = monaco.load_time_dependency(root)
    questions = {q.ex_num: q.question for q in monaco.load_questions(root)}
    out = []
    for ex in monaco.oracle_ex_nums(root):
        q = questions[ex]
        if time_dependent.get(q) is False and sum(map(len, monaco.load_oracle_documents(ex, root))) <= MAX_DOC_CHARS:
            out.append(ex)
    return out, questions


def published_score(run, ex, root):
    """Analysis only: the published GPT-4.1 judge score of one run on one question, None when absent."""
    path = root / run / f"llm_qa_judgement__{ex}.json"
    return json.loads(path.read_text(encoding="utf-8"))["judge_scores"]["judge_score"] if path.exists() else None


def stratum(kind, gold_values, scores):
    """List questions by band of the mean published oracle score; single-answer questions by whether exactly one
    of the two runs was right (scores 0 and 1) or the score is partial. None: excluded."""
    mean = sum(scores) / len(scores)
    if mean <= 0 or mean >= 1:
        return None
    if kind == "single":
        return "single_one_model_correct" if sorted(scores) == [0., 1.] else "single_partial"
    if gold_values > MAX_LIST_GOLD_VALUES:
        return None
    lo, hi = next(b for b in LIST_BANDS if b[0] <= mean < b[1])
    return f"list_{lo:.1f}-{hi:.1f}"


def strata(eligible, root):
    refs = monaco.load_references(root)
    out = defaultdict(list)
    for ex in sorted(eligible):
        scores = [published_score(run, ex, root) for run in ORACLE_RUNS]
        gold_answers = refs[ex].answers
        if None not in scores and (name := stratum(mis.judge_kind(gold_answers), mis.gold_length(gold_answers), scores)):
            out[name].append(ex)
    return dict(out)


def stratified_sample(members):
    """ALLOCATION questions per stratum, each drawn with its own `random.Random(SEED)` from the sorted members."""
    chosen = {}
    for name, k in ALLOCATION.items():
        if len(members.get(name, [])) < k:
            raise ValueError(f"stratum {name} has {len(members.get(name, []))} questions, {k} planned")
        chosen[name] = sorted(random.Random(SEED).sample(members.get(name, []), k)) if k else []
    return chosen


def prepare(args):
    eligible, questions = pool(args.data_root)
    of = {}
    if args.ex_nums:
        chosen = sorted(set(args.ex_nums))
        if not set(chosen) <= set(eligible):
            raise ValueError(f"not in the pool: {sorted(set(chosen) - set(eligible))}")
        selection, target_selection = {"rule": "explicit", "ex_nums": chosen}, None
    else:
        members = strata(eligible, args.data_root)
        sample = stratified_sample(members)
        of = {ex: name for name, exs in sample.items() for ex in exs}
        chosen = sorted(of)
        selection = {"rule": "stratified", "seed": SEED, "allocation": ALLOCATION,
                     "strata_sizes": {n: len(members.get(n, [])) for n in ALLOCATION}}
        target_selection = {
            "rule": "mean published GPT-4.1 score of the GPT-4o and Llama-3.1-405B oracle runs; 0 and 1 excluded; "
                    f"list questions by band, list gold above {MAX_LIST_GOLD_VALUES} values excluded; single-answer "
                    "questions by one run right and one wrong, or partial; per stratum random.Random(seed).sample "
                    "of the sorted members",
            "oracle_runs": list(ORACLE_RUNS), "seed": SEED, "allocation": ALLOCATION,
            "reads": "published judge scores and the gold's kind and value count (analysis side only)",
            "strata": members, "sample": sample}
    targets = [{"target_id": f"monaco_{ex}", "ex_num": ex, **({"stratum": of[ex]} if ex in of else {})}
               for ex in chosen]
    inputs = [{"target_id": t["target_id"], "question": questions[t["ex_num"]],
               "documents": monaco.load_oracle_documents(t["ex_num"], args.data_root)} for t in targets]
    source = json.loads((args.data_root / "SOURCE.json").read_text())
    manifest = experiment_manifest(
        purpose="Exploratory task-specific instruction selection on MoNaCo, oracle documents, question only",
        run_roots=list(STAGES), harness="perturbation_consistency.monaco_instruction_selection",
        experiment_version=mis.VERSION, normalization_version=mis.NORMALIZATION_VERSION,
        dataset={"name": "MoNaCo", "origin": source["origin"], "revision": source["revision"],
                 "setting": "oracle documents (published gpt-4o oracle run inputs)", "oracle_run": monaco.ORACLE_RUN},
        pool={"criteria": f"oracle documents, time-independent label, documents <= {MAX_DOC_CHARS} chars",
              "size": len(eligible), **selection},
        target_ids=[t["target_id"] for t in targets], candidates=list(mis.CANDIDATES), workers=list(mis.WORKERS),
        executor=mis.EXECUTOR, candidate_source="imported; authored from the question text only (import-candidates)",
        judge=mis.JUDGE, splitter=mis.SPLITTER, clusterer=mis.CLUSTERER,
        answer_format="free text ending in an `Answers:` line; the judge reads that line",
        answer_items=f"splitter splits the answer lines of all probes of a question into verbatim items, checked by "
                     f"code (split version {mis.SPLIT_VERSION})",
        answer_equivalence=f"clusterer groups the items of all probe answers of a question (cluster version "
                           f"{mis.CLUSTER_VERSION}); exact normalized item sets are a diagnostic",
        agreement="most central answer's mean item F1 with the nine slots, itself included; cross-worker = mean "
                  "item F1 over cross-worker pairs; failed slots 0",
        retry_policy=f"probe error, length or no answer line retried once ({mis.PROBE_ATTEMPTS} attempts); other "
                     f"stages: errors retried on rerun, at most {mis.MAX_ATTEMPTS} attempts, invalid judge, split or "
                     f"cluster replies asked again within a call, {mis.TRIES} calls; "
                     "budget stops always retried; last record per slot counts",
        models={k: get_spec(k).identity() for k in model_keys()},
        probe_reps=mis.REPEATS, execution_reps=mis.REPEATS, seed=SEED, primary_metric="central_item_f1_of_nine",
        tie_policy="seeded_uniform", max_candidate_words=mis.MAX_WORDS,
        scoring="published MoNaCo judge prompts; single = final precision, list = F1 (see module)",
        exploratory=True, frozen=False,
        git_commit=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip(), created_at=now())
    if args.dry_run:
        n = len(targets)
        print(json.dumps({"pool": len(eligible), "targets": n, "ex_nums": chosen,
                          "judge_validation_calls": n,
                          "strata": dict(Counter(t.get("stratum") for t in targets)),
                          "probe_calls": n * 36, "split_calls": n, "cluster_calls": n, "execution_calls": n * 12,
                          "judge_calls": n * 12,
                          "document_chars": [sum(map(len, i["documents"])) for i in inputs]}, indent=2))
        print(mis.task_prompt(inputs[0]["documents"], inputs[0]["question"], "<imported instruction>"))
        return
    exp = args.experiment
    exp.mkdir(parents=True, exist_ok=True)
    with exclusive(exp):
        if (exp / "manifest.json").exists():
            raise ValueError("experiment already prepared; use another directory")
        for name, rows in [("targets.jsonl", targets), ("inputs.jsonl", inputs)]:
            (exp / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        inputs_hashed = ["targets.jsonl", "inputs.jsonl"]
        if target_selection is not None:
            write_json(exp / "target_selection.json", target_selection)
            inputs_hashed.append("target_selection.json")
        manifest["input_hashes"] = {n: digest(exp / n) for n in inputs_hashed}
        with tarfile.open(exp / "code_snapshot.tar.gz", "w:gz") as archive:
            for directory in ("src", "scripts"):
                for path in sorted((ROOT / directory).rglob("*.py")):
                    archive.add(path, arcname=str(path.relative_to(ROOT)))
        manifest["code_snapshot_sha256"] = digest(exp / "code_snapshot.tar.gz")
        manifest["implementation_hashes"] = implementation_hashes()
        write_json(exp / "manifest.json", manifest)
    print(f"Prepared {len(targets)} targets from a pool of {len(eligible)}: {exp}")


def load(exp):
    manifest = json.loads((exp / "manifest.json").read_text())
    if manifest["experiment_version"] != mis.VERSION or manifest["implementation_hashes"] != implementation_hashes():
        raise ValueError("implementation changed: use the saved snapshot or a new experiment")
    if manifest["normalization_version"] != mis.NORMALIZATION_VERSION:
        raise ValueError("answer normalization changed")
    if manifest["models"] != {k: get_spec(k).identity() for k in model_keys()}:
        raise ValueError("model configuration changed")
    for name, sha in {**manifest["input_hashes"], **manifest.get("frozen_hashes", {})}.items():
        if digest(exp / name) != sha:
            raise ValueError(f"frozen artifact changed: {name}")
    return manifest, read_rows(exp / "targets.jsonl"), {r["target_id"]: r for r in read_rows(exp / "inputs.jsonl")}


def gold(args, targets):
    """Scoring only. Never passed to a model under test."""
    refs = monaco.load_references(args.data_root)
    return {t["target_id"]: refs[t["ex_num"]].answers for t in targets}


def run_jobs(args, jobs, fn):
    with ThreadPoolExecutor(max_workers=min(128, max(1, len(jobs))) if args.batch else args.concurrency) as pool:
        list(pool.map(fn, jobs))


def key_of(*parts):
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:20]


def validate_judge(args, manifest, targets, inputs):
    """Re-judge GPT-4o's published oracle answers with our judge; compare with the published GPT-4.1 scores."""
    path = args.experiment / "judge_validation.jsonl"
    todo = set(mis.pending([t["target_id"] for t in targets], read_rows(path), lambda r: r["target_id"]))
    jobs = [t for t in targets if t["target_id"] in todo]
    golds = gold(args, targets)
    stage = Stage(args, "validate_judge", [mis.JUDGE]) if jobs else None

    def job(t):
        tid = t["target_id"]
        published = monaco.load_published_judgement(t["ex_num"], args.data_root)
        with stage.lock:
            client, trace = stage.client(key_of(tid), mis.JUDGE)
        prompt = mis.judge_prompt(inputs[tid]["question"], published["output"], golds[tid])
        with trace.tags(stage="judge_validation", target_id=tid):
            rec = mis.judge(client, inputs[tid]["question"], published["output"], golds[tid])
        with stage.lock:
            append(path, {"target_id": tid, "kind": mis.judge_kind(golds[tid]),
                          "prompt_matches_published": prompt == published["judge_prompt"],
                          "published_score": published["judge_scores"]["judge_score"], **rec,
                          "cost_usd": trace.run_scope.cost_usd})
    if stage is not None:
        try:
            run_jobs(args, jobs, job)
        finally:
            stage.close()
    rows = list(mis.latest(read_rows(path), lambda r: r["target_id"]).values())
    ok = [r for r in rows if r["status"] == "ok"]
    summary = {"rows": len(rows), "judged": len(ok)}
    for kind in ("single", "list"):
        rr = [r for r in ok if r["kind"] == kind]
        if rr:
            diffs = [abs(r["score"] - r["published_score"]) for r in rr]
            summary[kind] = {"n": len(rr), "exact": sum(d < 1e-6 for d in diffs), "mean_abs_diff": sum(diffs) / len(rr),
                             "prompt_differs_from_published": sum(not r["prompt_matches_published"] for r in rr)}
    write_json(args.experiment / "judge_validation_summary.json", summary)
    print(json.dumps(summary, indent=2))


def freeze(exp, manifest, targets, inputs):
    if manifest["frozen"]:
        return
    prep = {r["target_id"]: r for r in read_rows(exp / "candidates.jsonl")}
    if set(prep) != {t["target_id"] for t in targets}:
        return
    prompts, planned = [], []
    for t in targets:
        tid = t["target_id"]
        for c in mis.CANDIDATES:
            instruction = prep[tid]["instructions"].get(c)
            prompts.append({"target_id": tid, "candidate": c, "prompt": None if instruction is None else
                            mis.task_prompt(inputs[tid]["documents"], inputs[tid]["question"], instruction)})
            for k in range(mis.REPEATS):
                planned += [{"stage": "probe", "target_id": tid, "candidate": c, "worker": w, "rep": k}
                            for w in mis.WORKERS]
                planned.append({"stage": "execute", "target_id": tid, "candidate": c, "worker": mis.EXECUTOR, "rep": k})
    (exp / "prompts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in prompts))
    with (exp / "planned.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(planned[0]))
        writer.writeheader()
        writer.writerows(planned)
    manifest["frozen"] = True
    manifest["frozen_hashes"] = {n: digest(exp / n) for n in ("candidates.jsonl", "prompts.jsonl", "planned.csv")}
    write_json(exp / "manifest.json", manifest)


def import_candidates(args, manifest, targets, inputs):
    """Reviewed instructions authored from the question text only; no model API call."""
    if manifest["frozen"] or (args.experiment / "candidates.jsonl").exists():
        raise ValueError("candidates already imported; use a new experiment for revisions")
    if args.candidate_file is None or not args.author:
        raise ValueError("import requires --candidate-file and --author")
    raw = read_rows(args.candidate_file)
    by = {r["target_id"]: r for r in raw}
    if len(by) != len(raw) or set(by) != {t["target_id"] for t in targets}:
        raise ValueError("candidate file must contain each planned target exactly once")
    validated = []
    for t in targets:
        r = by[t["target_id"]]
        review = r.get("review", {})
        if review.get("accepted") is not True or not str(review.get("notes", "")).strip():
            raise ValueError(f"missing accepted review with notes: {t['target_id']}")
        validated.append({"target_id": t["target_id"], "status": "ok", "source": "session_authored",
                          "instructions": mis.validate_candidates(r["instructions"]),
                          "author": args.author, "review": review})
    (args.experiment / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in validated))
    manifest["candidate_authoring"] = {"author": args.author, "source_file": str(args.candidate_file.resolve()),
        "source_sha256": digest(args.candidate_file), "imported_at": now(), "separate_model_api_cost_usd": 0,
        "review_type": args.review_type, "input_visibility": "question_only", "source": "session_authored"}
    freeze(args.experiment, manifest, targets, inputs)
    print(f"Imported and froze {len(validated) * 3} instructions; no model API calls.")


def probe(args, manifest):
    prompts = read_rows(args.experiment / "prompts.jsonl")
    path = args.experiment / "results.jsonl"
    if (args.experiment / "splits.jsonl").exists():
        raise ValueError("answer lines already split; probes are closed")
    by = {(p["target_id"], p["candidate"]): p for p in prompts}
    todo = mis.pending_probes([(p["target_id"], p["candidate"], k, w) for p in prompts for k in range(mis.REPEATS)
                        for w in mis.WORKERS], read_rows(path), probe_key)
    jobs = [(by[(tid, c)], k, w) for tid, c, k, w in todo]
    if not jobs:
        print("All probes final; no calls.")
        return
    stage = Stage(args, "probe", mis.WORKERS)

    def job(item):
        p, k, w = item
        with stage.lock:
            client, trace = stage.client(key_of(p["target_id"], p["candidate"], k, w), w)
        with trace.tags(stage="instruction_probe", target_id=p["target_id"], candidate=p["candidate"], worker=w,
                        sample=k):
            rec = mis.solve(client, p["prompt"]) if p["prompt"] is not None else \
                {"status": "candidate_unavailable", "answer_line": None}
        with stage.lock:
            append(path, {"target_id": p["target_id"], "candidate": p["candidate"], "sample": k, "worker": w,
                          **rec, "cost_usd": trace.run_scope.cost_usd})
    try:
        run_jobs(args, jobs, job)
    finally:
        stage.close()


def probe_key(r):
    return r["target_id"], r["candidate"], r["sample"], r["worker"]


def final_probes(args, targets):
    """Last record per planned probe slot; raises while a slot is absent or still retryable."""
    rows = read_rows(args.experiment / "results.jsonl")
    planned = [(t["target_id"], c, k, w) for t in targets for c in mis.CANDIDATES
               for k in range(mis.REPEATS) for w in mis.WORKERS]
    if not set(map(probe_key, rows)) <= set(planned):
        raise ValueError("unplanned probe record")
    if left := mis.pending_probes(planned, rows, probe_key):
        raise ValueError(f"{len(left)} probe slots absent or retryable; rerun the probe stage")
    return list(mis.latest(rows, probe_key).values())


def split(args, manifest, targets, inputs):
    """One splitter call per question over the distinct answer lines of its 36 probes."""
    probes = final_probes(args, targets)
    path = args.experiment / "splits.jsonl"
    todo = set(mis.pending([t["target_id"] for t in targets], read_rows(path), lambda r: r["target_id"]))
    jobs = [t for t in targets if t["target_id"] in todo]
    if not jobs:
        print("All questions split; no calls.")
        return
    stage = Stage(args, "split", [mis.SPLITTER])

    def job(t):
        tid = t["target_id"]
        lines = [r["answer_line"] for r in probes if r["target_id"] == tid and r["status"] == "ok"]
        with stage.lock:
            client, trace = stage.client(key_of(tid), mis.SPLITTER)
        with trace.tags(stage="answer_splitting", target_id=tid):
            rec = mis.split(client, inputs[tid]["question"], lines, f"{manifest['seed']}:{tid}")
        with stage.lock:
            append(path, {"target_id": tid, **rec, "cost_usd": trace.run_scope.cost_usd})
    try:
        run_jobs(args, jobs, job)
    finally:
        stage.close()


def final_splits(args, targets):
    """Answer line -> split entry per question; raises until every question is split."""
    splits = mis.latest(read_rows(args.experiment / "splits.jsonl"), lambda r: r["target_id"])
    if missing := [t["target_id"] for t in targets if splits.get(t["target_id"], {}).get("status") != "ok"]:
        raise ValueError(f"finish the split stage first: {missing}")
    return {tid: r["lines"] for tid, r in splits.items()}


def cluster(args, manifest, targets, inputs):
    """One clusterer call per question over the distinct items of its 36 probe answers."""
    probes = final_probes(args, targets)
    lines = final_splits(args, targets)
    path = args.experiment / "clusters.jsonl"
    todo = set(mis.pending([t["target_id"] for t in targets], read_rows(path), lambda r: r["target_id"]))
    jobs = [t for t in targets if t["target_id"] in todo]
    if not jobs:
        print("All questions clustered; no calls.")
        return
    stage = Stage(args, "cluster", [mis.CLUSTERER])

    def job(t):
        tid = t["target_id"]
        texts = [x for r in probes if r["target_id"] == tid for x in (mis.slot_items(r, lines[tid]) or [])]
        with stage.lock:
            client, trace = stage.client(key_of(tid), mis.CLUSTERER)
        with trace.tags(stage="answer_clustering", target_id=tid):
            rec = mis.cluster(client, inputs[tid]["question"], texts, f"{manifest['seed']}:{tid}")
        with stage.lock:
            append(path, {"target_id": tid, **rec, "cost_usd": trace.run_scope.cost_usd})
    try:
        run_jobs(args, jobs, job)
    finally:
        stage.close()


def selections(args, manifest, targets):
    path = args.experiment / "selection.jsonl"
    frozen = ("results.jsonl", "splits.jsonl", "clusters.jsonl")
    if path.exists():
        meta = json.loads((args.experiment / "selection_meta.json").read_text())
        if any(meta[f"{n}_sha256"] != digest(args.experiment / n) for n in frozen) \
                or meta["selection_sha256"] != digest(path):
            raise ValueError("probes, splits, clusters or selection changed after selection freeze")
        return read_rows(path)
    probes = final_probes(args, targets)
    lines = final_splits(args, targets)
    clusters = mis.latest(read_rows(args.experiment / "clusters.jsonl"), lambda r: r["target_id"])
    if missing := [t["target_id"] for t in targets if clusters.get(t["target_id"], {}).get("status") != "ok"]:
        raise ValueError(f"finish the cluster stage before selecting: {missing}")
    out = []
    for t in targets:
        tid = t["target_id"]
        rows = {c: [r for r in probes if r["target_id"] == tid and r["candidate"] == c] for c in mis.CANDIDATES}
        labels = clusters[tid]["labels"]
        scores = {c: mis.set_agreement(mis.item_sets(rows[c], lines[tid], labels)) for c in mis.CANDIDATES}
        out.append({"target_id": tid, "scores": scores, "primary": mis.select(tid, scores, manifest["seed"]),
                    "cross": mis.select(tid, scores, manifest["seed"], cross=True),
                    "rule_scores": {c: mis.rule_agreement(rows[c], lines[tid]) for c in mis.CANDIDATES}})
    path.write_text("".join(json.dumps(r) + "\n" for r in out))
    write_json(args.experiment / "selection_meta.json", {**{f"{n}_sha256": digest(args.experiment / n) for n in frozen},
               "selection_sha256": digest(path)})
    return out


def execute(args, manifest, targets):
    """Fresh executor runs for every candidate, independent of the probe answers used for selection."""
    prompts = {(p["target_id"], p["candidate"]): p["prompt"] for p in read_rows(args.experiment / "prompts.jsonl")}
    path = args.experiment / "executions.jsonl"
    jobs = mis.pending([(t["target_id"], c, k) for t in targets for c in mis.CANDIDATES for k in range(mis.REPEATS)],
                       read_rows(path), run_key)
    if not jobs:
        print("All executions final; no calls.")
        return
    stage = Stage(args, "execute", [mis.EXECUTOR])

    def job(item):
        tid, c, k = item
        with stage.lock:
            client, trace = stage.client(key_of(tid, c, k), mis.EXECUTOR)
        prompt = prompts[(tid, c)]
        with trace.tags(stage="instruction_execution", target_id=tid, candidate=c, worker=mis.EXECUTOR, rep=k):
            rec = mis.solve(client, prompt) if prompt is not None else {"status": "candidate_unavailable", "answer_line": None}
        with stage.lock:
            append(path, {"target_id": tid, "candidate": c, "rep": k, "worker": mis.EXECUTOR, **rec,
                          "cost_usd": trace.run_scope.cost_usd})
    try:
        run_jobs(args, jobs, job)
    finally:
        stage.close()


def run_key(r):
    return r["target_id"], r["candidate"], r["rep"]


def judge(args, manifest, targets, inputs):
    """Judge every final execution that returned content (its parsed answer line, see `mis.judge_response`);
    executions without content score 0 unjudged."""
    path = args.experiment / "judgements.jsonl"
    gradable = {run_key(r): r for r in mis.latest(read_rows(args.experiment / "executions.jsonl"), run_key).values()
                if r.get("content") and r["status"] in ("ok", "no_answer")}
    jobs = [gradable[k] for k in mis.pending(list(gradable), read_rows(path), run_key)]
    if not jobs:
        print("All gradable executions judged; no calls.")
        return
    golds = gold(args, targets)
    stage = Stage(args, "judge", [mis.JUDGE])

    def job(r):
        tid = r["target_id"]
        with stage.lock:
            client, trace = stage.client(key_of(tid, r["candidate"], r["rep"]), mis.JUDGE)
        with trace.tags(stage="judge", target_id=tid, candidate=r["candidate"], rep=r["rep"]):
            rec = mis.judge(client, inputs[tid]["question"], mis.judge_response(r), golds[tid])
        with stage.lock:
            row = {"target_id": tid, "candidate": r["candidate"], "rep": r["rep"], **rec,
                   "cost_usd": trace.run_scope.cost_usd}
            append(path, row)
    try:
        run_jobs(args, jobs, job)
    finally:
        stage.close()


def analyze(args, manifest, targets):
    sels = selections(args, manifest, targets) if (args.experiment / "selection.jsonl").exists() else []
    golds = gold(args, targets)
    executions = list(mis.latest(read_rows(args.experiment / "executions.jsonl"), run_key).values())
    judgements = list(mis.latest(read_rows(args.experiment / "judgements.jsonl"), run_key).values())
    summary = mis.analyze(targets, sels, executions, judgements,
                          kinds={tid: mis.judge_kind(g) for tid, g in golds.items()})
    summary["experiment_version"] = manifest["experiment_version"]
    summary["ties"] = dict(Counter(len(s["primary"]["tied_candidates"]) for s in sels))
    summary["chosen"] = dict(Counter(s["primary"]["candidate"] for s in sels))
    summary["agreement_distribution"] = dict(Counter(s["scores"][c]["support"] for s in sels for c in mis.CANDIDATES))
    probe_rows = read_rows(args.experiment / "results.jsonl")
    probes = list(mis.latest(probe_rows, probe_key).values())
    summary["probes_recorded"] = len(probes)
    summary["probes_planned"] = len(targets) * 36
    summary["probe_statuses"] = dict(Counter(r["status"] for r in probes))
    summary["superseded_attempts"] = {
        name: len(rows) - len(mis.latest(rows, key)) for name, rows, key in [
            ("probe", probe_rows, probe_key),
            ("execute", read_rows(args.experiment / "executions.jsonl"), run_key),
            ("judge", read_rows(args.experiment / "judgements.jsonl"), run_key),
            ("split", read_rows(args.experiment / "splits.jsonl"), lambda r: r["target_id"]),
            ("cluster", read_rows(args.experiment / "clusters.jsonl"), lambda r: r["target_id"])]}
    split_lines = [v for r in mis.latest(read_rows(args.experiment / "splits.jsonl"), lambda r: r["target_id"]).values()
                   if r.get("status") == "ok" for v in r["lines"].values()]
    summary["split_line_statuses"] = dict(Counter(v["status"] for v in split_lines))
    summary["rule_agreement_distribution"] = dict(Counter(s["rule_scores"][c]["support"]
                                                          for s in sels for c in mis.CANDIDATES))
    summary["rule_would_choose_same"] = sum(
        s["primary"]["candidate"] == mis.select(s["target_id"], s["rule_scores"], manifest["seed"])["candidate"]
        for s in sels)
    summary["execution_statuses"] = dict(Counter(r["status"] for r in executions))
    by_stratum = defaultdict(list)
    for t in targets:
        by_stratum[t.get("stratum")].append(t)
    if None not in by_stratum:
        summary["by_stratum"] = {}
        for name, ts in sorted(by_stratum.items()):
            ids = {t["target_id"] for t in ts}
            part = mis.analyze(ts, [s for s in sels if s["target_id"] in ids],
                               [r for r in executions if r["target_id"] in ids],
                               [j for j in judgements if j["target_id"] in ids])
            summary["by_stratum"][name] = {"targets": len(ts), "score": part["selection"]["score"]}
    summary["candidate_statuses"] = dict(Counter(r["status"] for r in read_rows(args.experiment / "candidates.jsonl")))
    summary["multi_value_gold_targets"] = sum(any(isinstance(x, list) and len(x) > 1 for x in g) for g in golds.values())
    summary["cost_usd"] = {}
    for stage in STAGES:
        cost, unknown, exposure = 0., 0, 0.
        for job in read_rows(args.experiment / f"{stage}_jobs.jsonl"):
            costs = trace_costs(args.experiment / job["trace"])
            cost += costs["recorded_request_cost"]
            unknown += costs["unknown_cost_calls"]
            exposure += costs["unknown_reserved_usd"]
        batches = read_rows(args.experiment / f"{stage}_batches.jsonl")
        summary["cost_usd"][stage] = {"recorded_request_cost": cost, "unknown_cost_calls": unknown,
            "unknown_reserved_usd": exposure,
            "batch_charged_cost": sum(float((r.get("usage") or {}).get("cost") or 0.)
                                      for r in batches if r.get("event") == "finished")}
    summary["interpretation"] = ("Exploratory; selection from nine cross-worker probe answers, evaluated on fresh "
                                 "executor runs. Not an independent validation of instruction transfer.")
    out = args.experiment / "analysis"
    out.mkdir(exist_ok=True)
    write_json(out / "summary.json", summary)
    print(json.dumps({"summary": str(out / "summary.json"), "planned_executions": summary["planned_executions"],
                      "recorded_executions": summary["recorded_executions"], "judged_ok": summary["judged_ok"],
                      "score": {p: round(v["mean"], 4) for p, v in summary["selection"]["score"].items()}}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["prepare", "validate-judge", "import-candidates", "probe", "split", "cluster",
                                      "select", "execute", "judge", "analyze"])
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--data-root", type=Path, default=monaco.MONACO_ROOT)
    ap.add_argument("--ex-nums", type=int, nargs="+", help="explicit pool questions instead of the stratified sample")
    ap.add_argument("--candidate-file", type=Path, help="reviewed candidate JSONL, one row per target")
    ap.add_argument("--author", help="provenance label for the candidates")
    ap.add_argument("--review-type", default="author_self_review", help="how the candidates were reviewed")
    ap.add_argument("--session-cost-usd", type=float, help="cumulative stage budget, including previous invocations")
    ap.add_argument("--run-cost-usd", type=float, help="per probe, split, cluster, execution or judge call")
    ap.add_argument("--concurrency", type=int, default=4, help="sync calls in flight")
    ap.add_argument("--batch", action="store_true", help="use existing OpenRouter batch transport")
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ap.add_argument("--dry-run", action="store_true", help="read-only plan and prompt preview")
    args = ap.parse_args()
    if args.concurrency < 1:
        ap.error("--concurrency must be positive")
    if args.stage == "prepare":
        prepare(args)
        return
    if args.dry_run:
        manifest, targets, inputs = load(args.experiment)
        print(json.dumps({"stage": args.stage, "targets": len(targets), "frozen": manifest["frozen"],
                          "transport": "batch" if args.batch else "sync"}, indent=2))
        for row in read_rows(args.experiment / "prompts.jsonl")[:len(mis.CANDIDATES)]:
            print(f"--- {row['target_id']} / {row['candidate']}\n{row['prompt']}")
        return
    with exclusive(args.experiment):
        manifest, targets, inputs = load(args.experiment)
        if args.stage not in ("import-candidates", "validate-judge") and not manifest["frozen"]:
            raise ValueError("import candidates to freeze them before this stage")
        if args.stage == "validate-judge":
            validate_judge(args, manifest, targets, inputs)
        elif args.stage == "import-candidates":
            import_candidates(args, manifest, targets, inputs)
        elif args.stage == "probe":
            probe(args, manifest)
        elif args.stage == "split":
            split(args, manifest, targets, inputs)
        elif args.stage == "cluster":
            cluster(args, manifest, targets, inputs)
        elif args.stage == "select":
            sels = selections(args, manifest, targets)
            print(json.dumps({"targets": len(sels),
                              "top_ties": dict(Counter(len(s["primary"]["tied_candidates"]) for s in sels))}))
        elif args.stage == "execute":
            execute(args, manifest, targets)
        elif args.stage == "judge":
            judge(args, manifest, targets, inputs)
        else:
            analyze(args, manifest, targets)


if __name__ == "__main__":
    main()
