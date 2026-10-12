#!/usr/bin/env python
"""Segment routing, step 3: every worker continues each chain node by node from its own segment answer (C34).

  python scripts/run_segment_continuation.py --experiment outputs/experiments/<date>_longcot-segment-routing \
      [--workers haiku-medium luna-medium flash-lite-high] [--batch-workers ...] [--reps 3] \
      [--sync-concurrency 12] [--session-cost-usd 30] [--run-cost-usd 2] [--env-file .env] [--dry-run]

Reads the probe results (results.jsonl, from scripts/run_perturbation_pilot.py). A worker's start value is its most
frequent answer to the segment's last node over all its probe samples. Each (target, worker, rep) run solves the
following nodes one call each (perturbation_consistency.segment_routing.continue_chain) up to the last requested node,
and stops at the first requested node it gets wrong: the requested nodes' gold answers are read for that check only.
All runs go out at once; under the batch transport each node is one batch round trip. One line per run in
continuation.jsonl (`--out`); traces under continuation/<target>/<worker>_r<rep>/.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.data import longcot  # noqa: E402
from minpilot.llm.client import LLMClient, http_transport  # noqa: E402
from minpilot.llm.specs import get_spec  # noqa: E402
from minpilot.runtime.trace import Limits, Trace  # noqa: E402
from perturbation_consistency import longcot_math, segment, segment_routing as sr  # noqa: E402
from perturbation_consistency.batch import BatchDispatcher, requests_http  # noqa: E402
from perturbation_consistency.longcot_nodes import node_prompt, parse_chain  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--workers", nargs="+", default=["haiku-medium", "luna-medium", "flash-lite-high"])
    ap.add_argument("--batch-workers", nargs="*", default=["haiku-medium", "luna-medium", "flash-lite-high"])
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--sync-concurrency", type=int, default=12)
    ap.add_argument("--session-cost-usd", type=float, default=30.0)
    ap.add_argument("--run-cost-usd", type=float, default=2.0, help="per (target, worker, rep)")
    ap.add_argument("--env-file", type=Path, default=REPO / ".env")
    ap.add_argument("--name", default="continuation",
                    help="this invocation's run record (<name>_run.json) and batch log; runs already in "
                         "the output file are skipped, so workers can be started in separate invocations")
    ap.add_argument("--out", default="continuation.jsonl",
                    help="output file in the experiment (two invocations running at once should not share one)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    exp = args.experiment
    if not set(args.batch_workers) <= set(args.workers):
        sys.exit("--batch-workers must be a subset of --workers")
    if (exp / f"{args.name}_run.json").exists():
        sys.exit(f"{exp}/{args.name}_run.json exists; use a new --name")
    targets = [segment.Target(**{k: tuple(v) if k == "nodes" else v for k, v in json.loads(x).items()})
               for x in (exp / "targets.jsonl").read_text().splitlines()]
    probes = defaultdict(list)
    for r in map(json.loads, (exp / "results.jsonl").read_text().splitlines()):
        probes[(r["target_id"], r["worker"])].append(r)
    sent = defaultdict(int)
    for p in map(json.loads, (exp / "prompts.jsonl").read_text().splitlines()):
        sent[p["target_id"]] += 1
    incomplete = sorted({w for t in targets for w in args.workers if len(probes[(t.target_id, w)]) < sent[t.target_id]})
    if incomplete:
        sys.exit(f"probe results incomplete for {incomplete}: start a worker once all its probes are in")
    out = exp / args.out
    done = set()
    if out.exists():
        done = {(r["target_id"], r["worker"], r["rep"]) for r in map(json.loads, out.read_text().splitlines())}
    chains, gold = {}, {}
    for d in {t.difficulty for t in targets}:
        prompt_of = {q.question_id: q.prompt for q in longcot.load_questions("math", d, template="linear")}
        refs = longcot.load_references("math", d)  # requested nodes' gold: the stop check only
        for t in targets:
            if t.difficulty == d:
                chain = chains[t.question_id] = parse_chain(t.question_id, prompt_of[t.question_id])
                gold[t.target_id] = dict(zip(chain.requested, longcot_math.answer_parts(refs[t.question_id].answer)))
    order = {c: i for i, c in enumerate(sr.CONDITIONS)}
    starts = {}
    for t in targets:
        for w in args.workers:
            rs = sorted(probes[(t.target_id, w)], key=lambda r: (order[r["condition"]], r["sample"]))
            starts[(t.target_id, w)] = sr.start_answer([r["answer"] for r in rs])
    jobs = [(t, w, k) for t in targets for w in args.workers for k in range(args.reps)
            if (t.target_id, w, k) not in done]
    after = {t.target_id: len(chains[t.question_id].nodes) for t in targets}
    print(f"{len(targets)} targets x {len(args.workers)} workers x {args.reps} reps = {len(jobs)} runs; "
          f"starts without an answer: {sum(s['answer'] is None for s in starts.values())}")
    if args.dry_run:
        t = targets[0]
        chain = chains[t.question_id]
        nxt = chain.nodes[[n.name for n in chain.nodes].index(t.node) + 1]
        print(f"\n===== {t.target_id}: next node {nxt.name} =====\n"
              f"{node_prompt(nxt, {t.node: '<start value>'}, sr.CONTINUATION_VARIANT)}")
        print("max nodes after the segment:", max(after[t.target_id] - len(t.nodes) for t in targets))
        return

    from dotenv import load_dotenv
    load_dotenv(args.env_file)
    key = os.environ["OPENROUTER_API_KEY"]
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    (exp / f"{args.name}_run.json").write_text(json.dumps({
        "workers": args.workers, "models": {w: get_spec(w).identity() for w in args.workers},
        "transport": {w: "openrouter_batch" if w in args.batch_workers else "openrouter_sync" for w in args.workers},
        "reps": args.reps, "starts": {f"{tid}|{w}": s for (tid, w), s in starts.items()},
        "session_cost_usd": args.session_cost_usd, "run_cost_usd": args.run_cost_usd, "git_commit": commit,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1, ensure_ascii=False))
    dispatcher = None
    if args.batch_workers:
        dispatcher = BatchDispatcher(requests_http(key), exp / f"openrouter_batches_{args.name}.jsonl",
                                     {w: get_spec(w) for w in args.batch_workers},
                                     max_cost_usd=args.session_cost_usd)
    sync, slots = http_transport(key), threading.Semaphore(args.sync_concurrency)

    def limited(body: dict, timeout: float | None) -> dict:
        with slots:
            return sync(body, timeout)

    lock, spent = threading.Lock(), [0.0]

    def job(item) -> None:
        t, w, k = item
        with lock:
            if spent[0] >= args.session_cost_usd:
                return
        trace = Trace(exp / "continuation" / t.target_id.replace(":", "__") / f"{w}_r{k}",
                      Limits(max_cost_usd=args.run_cost_usd))
        client = LLMClient(get_spec(w), trace, transport=dispatcher.transport if w in args.batch_workers else limited)
        with trace.tags(stage="segment_continuation", worker=w, rep=k):
            rec = sr.continue_chain(client, trace, chains[t.question_id], t, starts[(t.target_id, w)]["answer"],
                                    gold[t.target_id])
        cost = trace.run_scope.counters()["cost_usd"]
        with lock:
            spent[0] += cost
            with out.open("a") as f:
                f.write(json.dumps({"target_id": t.target_id, "worker": w, "rep": k,
                                    "start_support": starts[(t.target_id, w)], **rec, "cost_usd": cost},
                                   ensure_ascii=False) + "\n")
            print(f"[${spent[0]:.3f}] {t.target_id} {w} r{k} {rec['status']} "
                  f"{rec['requested_correct']}/{rec['requested_total']}", flush=True)

    with ThreadPoolExecutor(len(jobs)) as pool:
        list(pool.map(job, jobs))
    if dispatcher is not None:
        dispatcher.close()
        print(f"batch: charged ${dispatcher.charged_usd:.3f} (estimated per call ${dispatcher.estimated_usd:.3f})")
    print(f"done: {len(jobs)} runs, recorded spend ${spent[0]:.3f} -> {exp}")


if __name__ == "__main__":
    main()
