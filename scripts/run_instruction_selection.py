#!/usr/bin/env python
"""Standalone positive-instruction selection: prepare/generate/probe/select/continue/analyze."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from minpilot.artifacts import experiment_manifest
from minpilot.data import longcot
from minpilot.llm.client import LLMClient, http_transport
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import BudgetExceeded, Limits, Trace
from perturbation_consistency import instruction_selection as ins, longcot_math, segment
from perturbation_consistency.batch import BatchDispatcher, requests_http
from perturbation_consistency.longcot_nodes import parse_chain

DEFAULT_SOURCE = ROOT / "outputs/experiments/2026-10-12_longcot-segment-routing-i"


def read_rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def append(path, value):
    with path.open("a") as f:
        f.write(json.dumps(value, ensure_ascii=False) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def trace_costs(path):
    """Known costs and conservative exposure for unknown/interrupted requests."""
    started, terminal = {}, {}
    billed = 0.
    for r in read_rows(path / "llm_calls.jsonl"):
        call_id = r.get("call_id")
        if r["status"] == "started":
            started[call_id] = r
        elif r["status"] in ("ok", "error"):
            terminal[call_id] = r
            billed += float((r.get("usage") or {}).get("cost") or 0.)
    unknown = [r for key, r in started.items() if key not in terminal or
               terminal[key].get("transient", False)]
    return {"recorded_request_cost": billed, "unknown_cost_calls": len(unknown),
            "unknown_reserved_usd": sum(float(r.get("reserve_usd") or 0.) for r in unknown)}


@contextmanager
def exclusive(exp):
    """No two processes may mutate the same experiment concurrently."""
    import fcntl
    with (exp / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another process is using this experiment") from None
        yield


def target_obj(t):
    return segment.Target(**{k: tuple(v) if k == "nodes" else v for k, v in t.items()
                             if k in segment.Target.__dataclass_fields__})


def prepare(args):
    source = args.source.resolve()
    targets = read_rows(source / "targets.jsonl")
    source_manifest = json.loads((source / "manifest.json").read_text())
    if not targets or len({t["target_id"] for t in targets}) != len(targets):
        raise ValueError("missing or duplicate source targets")
    questions = {}
    for d in {t["difficulty"] for t in targets}:
        questions.update({q.question_id: q for q in longcot.load_questions("math", d, template="linear")})
    inputs = []
    for t in targets:
        q = questions[t["question_id"]]
        chain = parse_chain(q.question_id, q.prompt)
        expected = tuple(n.name for n in chain.nodes[:len(t["nodes"])])
        if tuple(t["nodes"]) != expected or t["node"] != expected[-1]:
            raise ValueError(f"invalid source segment: {t['target_id']}")
        t["requested_after"] = sorted((n for n in chain.requested if int(n[5:]) >= int(t["node"][5:])),
                                      key=lambda n: int(n[5:]))
        inputs.append({"target_id": t["target_id"], "question_id": q.question_id, "prompt": q.prompt})
    generation_mode = getattr(args, "generation_mode", "model")
    model_keys = (*ins.WORKERS, ins.GENERATOR) if generation_mode == "model" else ins.WORKERS
    manifest = experiment_manifest(
        purpose="Exploratory task-specific positive instruction selection by nine-answer modal agreement",
        run_roots=["generate", "probe", "continuation"], harness="perturbation_consistency.instruction_selection",
        experiment_version=ins.VERSION, equivalence_version=longcot_math.EQUIVALENCE_VERSION,
        dataset=source_manifest["dataset"], source_experiment=str(source),
        source_targets_sha256=digest(source / "targets.jsonl"),
        target_ids=[t["target_id"] for t in targets], candidates=list(ins.CANDIDATES),
        workers=list(ins.WORKERS), executor=ins.EXECUTOR,
        generator=ins.GENERATOR if generation_mode == "model" else None, generation_mode=generation_mode,
        models={w: get_spec(w).identity() for w in model_keys},
        probe_reps=3, continuation_reps=3, seed=0, primary_metric="modal_share_of_nine",
        tie_policy="seeded_uniform", start_policy="pooled_nine_probe_modal_canonical_first_tie",
        generation_tries=3, max_candidate_words=180, exploratory=True, frozen=False,
        git_commit=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip(), created_at=now())
    if args.dry_run:
        t = targets[0]
        chain = parse_chain(t["question_id"], inputs[0]["prompt"])
        print(json.dumps({"targets": len(targets), "difficulty": dict(Counter(t["difficulty"] for t in targets)),
                          "generation_mode": generation_mode,
                          "generation_calls": len(targets) if generation_mode == "model" else 0,
                          "max_generation_attempts": len(targets) * 3 if generation_mode == "model" else 0,
                          "probe_calls": len(targets) * 36, "continuation_rollouts": len(targets) * 12}, indent=2))
        print(ins.GENERATION_PROMPT.format(task=inputs[0]["prompt"]))
        print(ins.segment_prompt(chain, target_obj(t), "<generated instruction; unavailable before generation>"))
        nxt = chain.nodes[len(t["nodes"])]
        print(ins.continuation_prompt(nxt, {t["node"]: "<pooled nine-probe modal value>"}, "<same generated instruction>"))
        return
    exp = args.experiment
    exp.mkdir(parents=True, exist_ok=True)
    with exclusive(exp):
        if (exp / "manifest.json").exists():
            raise ValueError("experiment already prepared; use another directory")
        for filename, rows in [("targets.jsonl", targets), ("inputs.jsonl", inputs)]:
            (exp / filename).write_text("".join(json.dumps(r) + "\n" for r in rows))
        manifest["input_hashes"] = {n: digest(exp / n) for n in ("targets.jsonl", "inputs.jsonl")}
        # Preserve actual dirty source, not just the git revision.
        with tarfile.open(exp / "code_snapshot.tar.gz", "w:gz") as archive:
            for directory in ("src", "scripts"):
                for path in sorted((ROOT / directory).rglob("*.py")):
                    archive.add(path, arcname=str(path.relative_to(ROOT)))
        manifest["code_snapshot_sha256"] = digest(exp / "code_snapshot.tar.gz")
        manifest["implementation_hashes"] = implementation_hashes()
        write_json(exp / "manifest.json", manifest)
    print(f"Prepared {len(targets)} targets: {exp}")


def implementation_hashes():
    return {str(p.relative_to(ROOT)): digest(p) for p in
            [Path(__file__).resolve(), ROOT / "src/perturbation_consistency/instruction_selection.py",
             ROOT / "src/perturbation_consistency/longcot_math.py",
             ROOT / "src/perturbation_consistency/segment.py",
             ROOT / "src/perturbation_consistency/longcot_nodes.py"]}


def load(exp):
    manifest = json.loads((exp / "manifest.json").read_text())
    if manifest["experiment_version"] != ins.VERSION or manifest["implementation_hashes"] != implementation_hashes():
        raise ValueError("implementation changed: use the saved snapshot or a new experiment")
    if manifest["equivalence_version"] != longcot_math.EQUIVALENCE_VERSION:
        raise ValueError("answer equivalence changed")
    model_keys = (*ins.WORKERS, ins.GENERATOR) if manifest["generation_mode"] == "model" else ins.WORKERS
    if manifest["models"] != {w: get_spec(w).identity() for w in model_keys}:
        raise ValueError("model configuration changed")
    for name, sha in {**manifest["input_hashes"], **manifest.get("frozen_hashes", {})}.items():
        if digest(exp / name) != sha:
            raise ValueError(f"frozen artifact changed: {name}")
    targets = read_rows(exp / "targets.jsonl")
    inputs = {r["target_id"]: r for r in read_rows(exp / "inputs.jsonl")}
    chains = {t["target_id"]: parse_chain(t["question_id"], inputs[t["target_id"]]["prompt"]) for t in targets}
    return manifest, targets, inputs, chains


class StageTrace(Trace):
    """Use the existing reservation mechanism with one shared stage scope and lock."""
    def __init__(self, path, limit, session):
        super().__init__(path, Limits(max_cost_usd=limit))
        self.session = session
        self.scopes.append(session.run_scope)
        self._lock = session._lock

    def settle_llm(self, reserve_usd, cost_usd, unknown=False):
        with self._lock:
            super().settle_llm(reserve_usd, cost_usd, unknown)
            if unknown:
                # Do not reuse money that an unbilled timeout may already have spent.
                self.session.run_scope.reserved_usd += reserve_usd


class Stage:
    """A shared reserving budget across jobs, with cost reconstruction on resume."""
    def __init__(self, args, stage, workers):
        if args.session_cost_usd is None or args.run_cost_usd is None:
            raise ValueError("paid stages require --session-cost-usd and --run-cost-usd")
        if min(args.session_cost_usd, args.run_cost_usd) <= 0:
            raise ValueError("cost limits must be positive")
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
        key = os.environ["OPENROUTER_API_KEY"]
        self.exp, self.name, self.args = args.experiment, stage, args
        self.session = Trace(None, Limits(max_cost_usd=args.session_cost_usd))
        self.journal = self.exp / f"{stage}_jobs.jsonl"
        self.previous = read_rows(self.journal)
        self.lock = threading.RLock()
        # Trace paths are declared in a journal; no recursive run discovery.
        spent = 0.
        for row in self.previous:
            costs = trace_costs(self.exp / row["trace"])
            spent += costs["recorded_request_cost"] + costs["unknown_reserved_usd"]
        self.session.run_scope.cost_usd = spent
        self.session.run_scope.llm_usd = spent
        self.sync = http_transport(key)
        self.dispatcher = BatchDispatcher(requests_http(key), self.exp / f"{stage}_batches.jsonl",
                                          {w: get_spec(w) for w in workers},
                                          max_cost_usd=args.session_cost_usd) if args.batch else None

    def client(self, key, worker):
        path = f"{self.name}/{key}/attempt_{len(self.previous)}"
        rec = {"key": key, "trace": path, "started_at": now(), "worker": worker,
               "transport": "batch" if self.dispatcher else "sync",
               "session_cost_usd": self.args.session_cost_usd, "run_cost_usd": self.args.run_cost_usd}
        append(self.journal, rec)
        self.previous.append(rec)
        trace = StageTrace(self.exp / path, self.args.run_cost_usd, self.session)
        return LLMClient(get_spec(worker), trace,
                         transport=self.dispatcher.transport if self.dispatcher else self.sync), trace

    def close(self):
        if self.dispatcher:
            self.dispatcher.close()
        scope = self.session.run_scope
        print(f"{self.name}: cumulative budget exposure ${scope.cost_usd + scope.reserved_usd:.6f}")


def freeze(exp, manifest, targets, chains):
    if manifest["frozen"]:
        return
    prep = {r["target_id"]: r for r in read_rows(exp / "candidates.jsonl")}
    if set(prep) != {t["target_id"] for t in targets}:
        return
    prompts, planned = [], []
    for t in targets:
        tid = t["target_id"]
        for c in ins.CANDIDATES:
            instruction = prep[tid]["instructions"].get(c)
            for sample in range(3):
                prompts.append({"target_id": tid, "condition": c, "sample": sample, "detail": c,
                                "answer_node": t["node"], "nodes": t["nodes"],
                                "prompt": ins.segment_prompt(chains[tid], target_obj(t), instruction)
                                if instruction is not None else None})
                for w in ins.WORKERS:
                    planned.append({"stage": "probe", "target_id": tid, "candidate": c,
                                    "worker": w, "rep": sample})
                planned.append({"stage": "continuation", "target_id": tid, "candidate": c,
                                "worker": ins.EXECUTOR, "rep": sample})
    (exp / "prompts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in prompts))
    with (exp / "planned.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(planned[0]))
        writer.writeheader()
        writer.writerows(planned)
    manifest["frozen"] = True
    manifest["frozen_hashes"] = {n: digest(exp / n) for n in ("candidates.jsonl", "prompts.jsonl", "planned.csv")}
    write_json(exp / "manifest.json", manifest)


def generate(args, manifest, targets, inputs, chains):
    if manifest.get("generation_mode", "model") != "model":
        raise ValueError("session-authored experiment: use import-candidates, not model generation")
    if manifest["frozen"]:
        print("Candidates already frozen; no calls.")
        return
    done = {r["target_id"] for r in read_rows(args.experiment / "candidates.jsonl")}
    attempts = read_rows(args.experiment / "generation_attempts.jsonl")
    stage = Stage(args, "generate", [ins.GENERATOR])
    try:
        for t in targets:
            tid = t["target_id"]
            if tid in done:
                continue
            prior = [r for r in attempts if r["target_id"] == tid]
            accepted = next((r["instructions"] for r in prior if r["status"] == "ok"), None)
            for attempt in range(len(prior), ins.GENERATION_TRIES) if accepted is None else []:
                client, trace = stage.client(hashlib.sha256(tid.encode()).hexdigest()[:16], ins.GENERATOR)
                try:
                    with trace.tags(stage="instruction_generation", target_id=tid, attempt=attempt):
                        accepted = ins.generate(client, inputs[tid]["prompt"])
                    rec = {"status": "ok", "instructions": accepted}
                except BudgetExceeded:
                    # Budget interruptions remain pending, and do not consume a generation attempt.
                    return
                except ins.ERRORS as exc:
                    rec = {"status": "error", "error": str(exc)[:300]}
                append(args.experiment / "generation_attempts.jsonl", {"target_id": tid, "attempt": attempt, **rec})
                if accepted is not None:
                    break
            append(args.experiment / "candidates.jsonl", {"target_id": tid,
                   "status": "ok" if accepted else "generation_failed", "instructions": accepted or {"naive": ""}})
        freeze(args.experiment, manifest, targets, chains)
    finally:
        stage.close()


def import_candidates(args, manifest, targets, chains):
    """Import session-authored, reviewed instructions without an additional model API call."""
    if manifest["generation_mode"] != "session":
        raise ValueError("prepare with --generation-mode session before importing")
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
        instructions = ins.validate_candidates(r["instructions"])
        review = r.get("review", {})
        if review.get("accepted") is not True or not isinstance(review.get("notes"), str) or not review["notes"].strip():
            raise ValueError(f"missing accepted review with notes: {t['target_id']}")
        validated.append({"target_id": t["target_id"], "status": "ok", "instructions": instructions,
                          "author": args.author, "review": review, "source": "session_authored"})
    # Validate the whole file before writing anything; reviewer and author may be the same session.
    (args.experiment / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in validated))
    manifest["candidate_authoring"] = {"author": args.author, "source_file": str(args.candidate_file.resolve()),
        "source_sha256": digest(args.candidate_file), "imported_at": now(), "separate_model_api_cost_usd": 0,
        "review_type": "author_self_review", "input_visibility": "question_only", "source": "session_authored"}
    freeze(args.experiment, manifest, targets, chains)
    print(f"Imported and froze {len(validated) * 3} session-authored instructions; no model API calls.")


def probe(args, manifest):
    rows = read_rows(args.experiment / "prompts.jsonl")
    path = args.experiment / "results.jsonl"
    done = {(r["target_id"], r["condition"], r["sample"], r["worker"]) for r in read_rows(path)}
    jobs = [(p, w) for p in rows for w in ins.WORKERS
            if (p["target_id"], p["condition"], p["sample"], w) not in done]
    if not jobs:
        print("All probes recorded; no calls.")
        return
    stage = Stage(args, "probe", ins.WORKERS)

    def job(item):
        p, w = item
        key = hashlib.sha256(f"{p['target_id']}:{p['condition']}:{p['sample']}:{w}".encode()).hexdigest()[:20]
        with stage.lock:
            client, trace = stage.client(key, w)
        with trace.tags(stage="instruction_probe", target_id=p["target_id"], candidate=p["condition"], worker=w,
                        sample=p["sample"]):
            rec = ins.solve_segment(client, p["prompt"], p["answer_node"]) if p["prompt"] is not None else \
                {"status": "candidate_unavailable", "answer": None}
        with stage.lock:
            append(path, {k: p[k] for k in ("target_id", "condition", "sample", "detail")} |
                   {"worker": w, **rec, "cost_usd": trace.run_scope.cost_usd})
    try:
        # A bounded wave can form a batch without allocating thousands of threads.
        with ThreadPoolExecutor(max_workers=min(128, max(1, len(jobs))) if args.batch else args.concurrency) as pool:
            list(pool.map(job, jobs))
    finally:
        stage.close()


def selections(args, manifest, targets):
    path = args.experiment / "selection.jsonl"
    probes = read_rows(args.experiment / "results.jsonl")
    if path.exists():
        meta = json.loads((args.experiment / "selection_meta.json").read_text())
        if meta["probe_sha256"] != digest(args.experiment / "results.jsonl") or meta["selection_sha256"] != digest(path):
            raise ValueError("probes or selection changed after selection freeze")
        return read_rows(path)
    expected = {(t["target_id"], c, k, w) for t in targets for c in ins.CANDIDATES
                for k in range(3) for w in ins.WORKERS}
    recorded = [(r["target_id"], r["condition"], r["sample"], r["worker"]) for r in probes]
    if len(set(recorded)) != len(recorded) or not set(recorded) <= expected:
        raise ValueError("duplicate or unplanned probe record")
    if set(recorded) != expected:
        raise ValueError("finish probe stage before selecting; failed slots are allowed, absent slots are pending")
    out = []
    for t in targets:
        tid = t["target_id"]
        grouped = {c: [r for r in probes if r["target_id"] == tid and r["condition"] == c] for c in ins.CANDIDATES}
        scores = {c: ins.agreement(rr) for c, rr in grouped.items()}
        out.append({"target_id": tid, "scores": scores, "primary": ins.select(tid, scores, manifest["seed"]),
                    "cross": ins.select(tid, scores, manifest["seed"], cross=True),
                    "starts": {c: ins.start_answer(rr) for c, rr in grouped.items()}})
    path.write_text("".join(json.dumps(r) + "\n" for r in out))
    write_json(args.experiment / "selection_meta.json", {"probe_sha256": digest(args.experiment / "results.jsonl"),
               "selection_sha256": digest(path)})
    return out


def continuation(args, manifest, targets, chains):
    selected = {r["target_id"]: r for r in selections(args, manifest, targets)}
    prep = {r["target_id"]: r for r in read_rows(args.experiment / "candidates.jsonl")}
    gold = {}
    for d in {t["difficulty"] for t in targets}:
        refs = longcot.load_references("math", d)
        for t in targets:
            if t["difficulty"] == d:
                gold[t["target_id"]] = dict(zip(chains[t["target_id"]].requested,
                                                longcot_math.answer_parts(refs[t["question_id"]].answer)))
    path = args.experiment / "continuation.jsonl"
    done = {(r["target_id"], r["candidate"], r["rep"]) for r in read_rows(path)}
    jobs = [(t, c, k) for t in targets for c in ins.CANDIDATES for k in range(3)
            if (t["target_id"], c, k) not in done]
    if not jobs:
        print("All continuations recorded; no calls.")
        return
    stage = Stage(args, "continuation", [ins.EXECUTOR])

    def job(item):
        t, c, k = item
        tid = t["target_id"]
        key = hashlib.sha256(f"{tid}:{c}:{k}".encode()).hexdigest()[:20]
        with stage.lock:
            client, trace = stage.client(key, ins.EXECUTOR)
        instruction = prep[tid]["instructions"].get(c)
        with trace.tags(stage="instruction_continuation", target_id=tid, candidate=c, worker=ins.EXECUTOR, rep=k):
            rec = ins.continue_chain(client, trace, chains[tid], target_obj(t), selected[tid]["starts"][c]["answer"],
                                     gold[tid], instruction or "")
        with stage.lock:
            append(path, {"target_id": tid, "candidate": c, "worker": ins.EXECUTOR, "rep": k,
                          "start_support": selected[tid]["starts"][c], **rec, "cost_usd": trace.run_scope.cost_usd})
    try:
        with ThreadPoolExecutor(max_workers=min(128, max(1, len(jobs))) if args.batch else args.concurrency) as pool:
            list(pool.map(job, jobs))
    finally:
        stage.close()


def analyze(args, manifest, targets):
    sels = read_rows(args.experiment / "selection.jsonl")
    if sels:
        selections(args, manifest, targets)  # verify frozen provenance
    runs = read_rows(args.experiment / "continuation.jsonl")
    summary = ins.analyze(targets, sels, runs)
    summary["experiment_version"] = manifest["experiment_version"]
    summary["start_policy"] = manifest["start_policy"]
    summary["ties"] = dict(Counter(len(s["primary"]["tied_candidates"]) for s in sels))
    summary["chosen"] = dict(Counter(s["primary"]["candidate"] for s in sels))
    summary["agreement_distribution"] = dict(Counter(s["scores"][c]["support"] for s in sels for c in ins.CANDIDATES))
    summary["probes_recorded"] = len(read_rows(args.experiment / "results.jsonl"))
    summary["probes_planned"] = len(targets) * 36
    summary["probes_missing"] = summary["probes_planned"] - summary["probes_recorded"]
    summary["rollout_statuses"] = dict(Counter(r["status"] for r in runs))
    summary["generation_statuses"] = dict(Counter(r["status"] for r in read_rows(args.experiment / "candidates.jsonl")))
    summary["cost_usd"] = {}
    for stage in ("generate", "probe", "continuation"):
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
    summary["interpretation"] = "Exploratory; pooling nine cross-worker probe answers plus instruction selection, not independent instruction validation."
    out = args.experiment / "analysis"
    out.mkdir(exist_ok=True)
    write_json(out / "summary.json", summary)
    # Optional plotting dependency is needed only for report figures.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for p in ("selected", "naive", "random", "analogical", "clarify", "local_check", "best_in_hindsight"):
        data = summary["node_order"][p]
        ax.plot([r["order"] for r in data], [r["accuracy"] for r in data], marker="o", label=p)
    ax.set(xlabel="Requested node order (1 = probe segment endpoint)", ylabel="Accuracy", ylim=(0, 1))
    ax.set_xticks([r["order"] for r in summary["node_order"]["naive"]])
    ax.legend(fontsize=8)
    ax.grid(alpha=.25)
    fig.savefig(out / "node_order_accuracy.png", dpi=150)
    plt.close(fig)
    print(json.dumps({"summary": str(out / "summary.json"), "node_order_plot": str(out / "node_order_accuracy.png"),
                      "planned_rollouts": summary["planned_rollouts"], "missing_rollouts": summary["missing_rollouts"],
                      "requested_share": summary["selection"]["requested_share"]}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["prepare", "generate", "import-candidates", "probe", "select", "continue", "analyze"])
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--generation-mode", choices=["model", "session"], default="model")
    ap.add_argument("--candidate-file", type=Path, help="reviewed session-authored JSONL, one row per target")
    ap.add_argument("--author", help="provenance label for session-authored candidates")
    ap.add_argument("--session-cost-usd", type=float, help="cumulative stage budget, including previous invocations")
    ap.add_argument("--run-cost-usd", type=float, help="per probe call, generation attempt or continuation rollout")
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--batch", action="store_true", help="use existing OpenRouter batch transport")
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ap.add_argument("--dry-run", action="store_true", help="read-only plan and actual prepared prompt preview")
    args = ap.parse_args()
    if args.concurrency < 1:
        ap.error("--concurrency must be positive")
    if args.stage == "prepare":
        prepare(args)
        return
    if args.dry_run:
        manifest, targets, inputs, chains = load(args.experiment)
        print(json.dumps({"stage": args.stage, "targets": len(targets), "frozen": manifest["frozen"],
                          "transport": "batch" if args.batch else "sync",
                          "generation_mode": manifest["generation_mode"],
                          "probe_calls": len(targets) * 36, "continuation_rollouts": len(targets) * 12}, indent=2))
        candidates = read_rows(args.experiment / "candidates.jsonl")
        if manifest["frozen"] and candidates:
            t = targets[0]
            for c, text in candidates[0]["instructions"].items():
                print(f"Candidate {c}:\n{ins.segment_prompt(chains[t['target_id']], target_obj(t), text)}")
                print(ins.continuation_prompt(chains[t["target_id"]].nodes[len(t["nodes"])],
                                             {t["node"]: "<pooled nine-probe modal value>"}, text))
        return
    with exclusive(args.experiment):
        manifest, targets, inputs, chains = load(args.experiment)
        if args.stage not in ("generate", "import-candidates") and not manifest["frozen"]:
            raise ValueError("finish generation to freeze candidates before this stage")
        if args.stage == "generate":
            generate(args, manifest, targets, inputs, chains)
        elif args.stage == "import-candidates":
            import_candidates(args, manifest, targets, chains)
        elif args.stage == "probe":
            probe(args, manifest)
        elif args.stage == "select":
            sels = selections(args, manifest, targets)
            print(json.dumps({"targets": len(sels), "top_ties": dict(Counter(len(s["primary"]["tied_candidates"]) for s in sels))}))
        elif args.stage == "continue":
            continuation(args, manifest, targets, chains)
        else:
            analyze(args, manifest, targets)


if __name__ == "__main__":
    main()
