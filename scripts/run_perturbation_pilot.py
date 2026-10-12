#!/usr/bin/env python
"""Perturbation pilot, step 2: every worker answers every prompt of prompts.jsonl (written by step 1).

  python scripts/run_perturbation_pilot.py --experiment outputs/experiments/<date>_longcot-perturbation-pilot \
      [--workers luna-medium haiku-medium flash-medium] [--batch-workers flash-medium] [--sync-concurrency 12] \
      [--session-cost-usd 10] [--run-cost-usd 2] [--max-tokens N] [--resume NAME] [--env-file .env]

All calls go out at once: the listed batch workers through the OpenRouter Batch API (one round trip unless a batch
is resubmitted), the others as synchronous calls. Each (target, worker) has its own Trace under runs/; results.jsonl
gets one line per call (answer, method line, status, tokens, cost). Gold answers are not read here; score with
scripts/analyze_perturbation_pilot.py.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.llm.client import HTTPError, LLMClient, TransientError, http_transport  # noqa: E402
from minpilot.llm.specs import get_spec  # noqa: E402
from minpilot.runtime.trace import BudgetExceeded, InfraError, Limits, Trace  # noqa: E402
from perturbation_consistency.batch import BatchDispatcher, requests_http  # noqa: E402
from perturbation_consistency.longcot_nodes import extract_answer  # noqa: E402
from perturbation_consistency.perturb import method_label  # noqa: E402
from perturbation_consistency.segment import node_answers  # noqa: E402


def call(client: LLMClient, trace: Trace, row: dict, worker: str) -> dict:
    out = {k: row[k] for k in ("target_id", "condition", "sample", "detail")} | {"worker": worker}
    with trace.tags(stage="perturbation_pilot", condition=row["condition"], sample=row["sample"]):
        try:
            res = client.chat([{"role": "user", "content": row["prompt"]}])
        except (InfraError, BudgetExceeded, HTTPError, TransientError, ValueError) as e:  # ValueError: not JSON
            return out | {"answer": None, "method": None, "status": "error", "error": str(e)[:300]}
    nodes = node_answers(res.content) if row.get("nodes") else {}
    answer = extract_answer(res.content)
    if answer is None and row.get("answer_node"):  # a segment prompt: the last node's line also gives the answer
        answer = nodes.get(row["answer_node"])
    status = "length" if res.finish_reason == "length" else ("ok" if answer is not None else "no_answer")
    return out | {"answer": answer if status == "ok" else None, "node_answers": nodes,
                  "method": method_label(res.content),
                  "status": status, "finish_reason": res.finish_reason,
                  "completion_tokens": (res.usage or {}).get("completion_tokens"),
                  "cost_usd": float((res.usage or {}).get("cost") or 0.0),
                  "cost_estimated": bool((res.usage or {}).get("cost_estimated"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--workers", nargs="+", default=["luna-medium", "haiku-medium", "flash-medium"])
    ap.add_argument("--batch-workers", nargs="*", default=["flash-medium"])
    ap.add_argument("--sync-concurrency", type=int, default=12)
    ap.add_argument("--session-cost-usd", type=float, default=10.0)
    ap.add_argument("--run-cost-usd", type=float, default=2.0, help="per (target, worker)")
    ap.add_argument("--max-tokens", type=int, default=None, help="override the workers' output cap (segment prompts)")
    ap.add_argument("--env-file", type=Path, default=REPO / ".env")
    ap.add_argument("--resume", default=None, metavar="NAME",
                    help="append to an existing results.jsonl, skipping every (prompt, worker) it already has; traces "
                         "go under NAME/ and the run record to NAME.json (e.g. a stalled batch worker sent again)")
    args = ap.parse_args()
    if not set(args.batch_workers) <= set(args.workers):
        sys.exit("--batch-workers must be a subset of --workers")
    exp = args.experiment
    if not (exp / "prompts.jsonl").exists():
        sys.exit(f"{exp}/prompts.jsonl missing: run scripts/prepare_{{perturbation,segment}}_pilot.py first")
    if (exp / "results.jsonl").exists() and not args.resume:
        sys.exit(f"{exp} already has results.jsonl")
    if args.resume and (exp / f"{args.resume}.json").exists():
        sys.exit(f"{exp}/{args.resume}.json exists; use a new --resume name")
    have = set()
    if args.resume and (exp / "results.jsonl").exists():
        have = {(r["target_id"], r["condition"], r["sample"], r["worker"])
                for r in map(json.loads, (exp / "results.jsonl").read_text().splitlines())}
    runs_root, run_record = (args.resume, f"{args.resume}.json") if args.resume else ("runs", "run.json")
    from dotenv import load_dotenv
    load_dotenv(args.env_file)
    key = os.environ["OPENROUTER_API_KEY"]
    rows = [json.loads(x) for x in (exp / "prompts.jsonl").read_text().splitlines()]

    def spec_of(w: str):
        spec = get_spec(w)
        return dataclasses.replace(spec, max_tokens=args.max_tokens) if args.max_tokens else spec

    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    (exp / run_record).write_text(json.dumps({
        "workers": args.workers, "models": {w: spec_of(w).identity() for w in args.workers},
        "transport": {w: "openrouter_batch" if w in args.batch_workers else "openrouter_sync" for w in args.workers},
        "session_cost_usd": args.session_cost_usd, "run_cost_usd": args.run_cost_usd, "calls": len(rows) * len(
            args.workers) - len(have), "skipped_as_recorded": len(have), "git_commit": commit,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1))

    dispatcher = None
    if args.batch_workers:
        dispatcher = BatchDispatcher(requests_http(key), exp / "openrouter_batches.jsonl",
                                     {w: spec_of(w) for w in args.batch_workers}, max_cost_usd=args.session_cost_usd)
    sync, slots = http_transport(key), threading.Semaphore(args.sync_concurrency)

    def limited(body: dict, timeout: float | None) -> dict:
        with slots:
            return sync(body, timeout)

    clients: dict[tuple[str, str], tuple[LLMClient, Trace]] = {}
    for tid in sorted({r["target_id"] for r in rows}):
        for w in args.workers:
            trace = Trace(exp / runs_root / tid.replace(":", "__") / w, Limits(max_cost_usd=args.run_cost_usd))
            transport = dispatcher.transport if w in args.batch_workers else limited
            clients[(tid, w)] = (LLMClient(spec_of(w), trace, transport=transport), trace)
    lock, spent = threading.Lock(), [0.0]

    def job(item: tuple[dict, str]) -> None:
        row, w = item
        with lock:
            if spent[0] >= args.session_cost_usd:
                return
        client, trace = clients[(row["target_id"], w)]
        rec = call(client, trace, row, w)
        with lock:
            spent[0] += rec.get("cost_usd") or 0.0
            with (exp / "results.jsonl").open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[${spent[0]:.3f}] {rec['target_id']} {rec['condition']}#{rec['sample']} {w} {rec['status']}",
                  flush=True)

    jobs = [(r, w) for r in rows for w in args.workers
            if (r["target_id"], r["condition"], r["sample"], w) not in have]
    with ThreadPoolExecutor(max(1, len(jobs))) as pool:
        list(pool.map(job, jobs))
    if dispatcher is not None:
        dispatcher.close()
        print(f"batch: charged ${dispatcher.charged_usd:.3f} (estimated per call ${dispatcher.estimated_usd:.3f})")
    print(f"done: {len(jobs)} calls, recorded spend ${spent[0]:.3f} -> {exp}")


if __name__ == "__main__":
    main()
