#!/usr/bin/env python
"""Perturbation consistency on LongCoT math chains (package `perturbation_consistency`, not the minpilot framework).

  python scripts/run_perturbation_consistency.py --experiment outputs/experiments/<date>_longcot-perturbation-consistency \
      --template linear --difficulty easy --limit 3 [--workers luna-high haiku-high gemini] [--n 5] [--reps 3] \
      [--probe-depth 3] [--batch] [--parallel 12] [--session-cost-usd 8] [--run-cost-usd 2] [--env-file .env] [--dry-run]

Questions are taken in data-file order (`--offset`, `--limit`), by exact id (`--only`), or as a seeded random sample
(`--sample K --seed S`, drawn before any run and listed in the manifest). Per question: the consistency probes and the
routed pipeline (one job), and `--reps` fixed pipelines per worker. New jobs are not started once the recorded spend
reaches --session-cost-usd. `--dry-run` parses the chains and prints prompts without any model call.

`--batch` sends every model call through the OpenRouter Batch API (perturbation_consistency.batch): all jobs run at
once, calls are pooled into batches, and a batch stops being submitted once the charged batch spend reaches
--session-cost-usd. Each node of a chain is one batch round trip (minutes, up to 24 h). Batch submissions and their
charged usage are logged in openrouter_batches.jsonl; batch.jsonl stays the per-job log.
Gold answers are not read here; score with scripts/analyze_perturbation_consistency.py.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.artifacts import experiment_manifest  # noqa: E402
from minpilot.data import longcot  # noqa: E402
from minpilot.llm.client import LLMClient  # noqa: E402
from minpilot.llm.specs import get_spec  # noqa: E402
from perturbation_consistency.batch import BatchDispatcher, requests_http  # noqa: E402
from perturbation_consistency.longcot_nodes import VARIANTS, node_prompt, parse_chain  # noqa: E402
from perturbation_consistency.runner import Settings, run_pipeline, run_routed  # noqa: E402

DEFAULT_WORKERS = ("luna-high", "haiku-high", "gemini")


def select_questions(args) -> list:
    qs = longcot.load_questions("math", args.difficulty, template=args.template)
    if args.only:
        qs = [q for q in qs if q.question_id in args.only]
    if args.sample:
        picked = set(random.Random(f"{args.seed}:{args.difficulty}:{args.template}").sample(
            [q.question_id for q in qs], args.sample))
        qs = [q for q in qs if q.question_id in picked]  # data-file order
    qs = qs[args.offset:]
    return qs[:args.limit] if args.limit else qs


def dry_run(chains: list) -> None:
    for c in chains:
        print(f"{c.question_id}: {len(c.nodes)} nodes, requested {', '.join(c.requested)}, "
              f"deps {sum(1 for n in c.nodes if n.deps)}")
    c = chains[0]
    for v in range(len(VARIANTS)):
        print(f"\n===== {c.question_id} {c.nodes[0].name} variant {v} =====\n{node_prompt(c.nodes[0], {}, v)}")
    nxt = next(n for n in c.nodes if n.deps)
    print(f"\n===== {c.question_id} {nxt.name} variant 0 =====\n"
          f"{node_prompt(nxt, {d: f'<answer of {d}>' for d in nxt.deps}, 0)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--purpose", default="Perturbation consistency worker routing on LongCoT math chains")
    ap.add_argument("--difficulty", default="easy", choices=longcot.DIFFICULTIES)
    ap.add_argument("--template", default="linear")
    ap.add_argument("--offset", type=int, default=0, help="skip the first K selected questions (data-file order)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", nargs="*", default=None, help="exact question ids")
    ap.add_argument("--sample", type=int, default=None, help="seeded random sample of K questions")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", nargs="+", default=list(DEFAULT_WORKERS))
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--probe-depth", type=int, default=3,
                    help="probe up to this many first nodes; a node is probed only by workers still tied")
    ap.add_argument("--batch", action="store_true", help="OpenRouter Batch API for every call")
    ap.add_argument("--parallel", type=int, default=12)
    ap.add_argument("--session-cost-usd", type=float, default=8.0)
    ap.add_argument("--run-cost-usd", type=float, default=2.0)
    ap.add_argument("--env-file", type=Path, default=REPO / ".env")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not 1 <= args.n <= len(VARIANTS):
        sys.exit(f"--n must be 1..{len(VARIANTS)} (fixed instruction variants)")

    chains = [parse_chain(q.question_id, q.prompt) for q in select_questions(args)]
    if not chains:
        sys.exit("no questions selected")
    if args.dry_run:
        dry_run(chains)
        return

    from dotenv import load_dotenv
    if not args.env_file.exists():
        sys.exit(f"no env file {args.env_file} (OPENROUTER_API_KEY)")
    load_dotenv(args.env_file)
    exp = args.experiment
    if (exp / "manifest.json").exists():
        sys.exit(f"{exp} already has a manifest; use a new experiment directory")
    (exp / "runs").mkdir(parents=True)
    source = json.loads((longcot.LONGCOT_ROOT.parents[2] / "SOURCE.json").read_text())
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "src", "scripts"],
                                capture_output=True, text=True).stdout.strip())
    planned = []
    for c in chains:
        planned.append({"question_id": c.question_id, "arm": "consistency_routed", "worker": None, "rep": 0})
        planned += [{"question_id": c.question_id, "arm": f"fixed_{w}", "worker": w, "rep": r}
                    for w in args.workers for r in range(args.reps)]
    (exp / "planned.jsonl").write_text("".join(json.dumps(p) + "\n" for p in planned))
    manifest = experiment_manifest(
        purpose=args.purpose, run_roots=["runs"], harness="perturbation_consistency",
        dataset={"name": "LongCoT", "domain": "math", "difficulty": args.difficulty, "template": args.template,
                 "revision": source["revision"], "selection": {"offset": args.offset, "limit": args.limit,
                                                               "only": args.only, "sample": args.sample,
                                                               "seed": args.seed}},
        question_ids=[c.question_id for c in chains], workers=args.workers,
        models={w: get_spec(w).identity() for w in args.workers}, n_variants=args.n, fixed_reps=args.reps,
        variants=list(VARIANTS[:args.n]), probe_depth=args.probe_depth,
        transport="openrouter_batch" if args.batch else "openrouter_sync",
        run_cost_usd=args.run_cost_usd, session_cost_usd=args.session_cost_usd,
        git_commit=commit, uncommitted_changes=dirty, planned_run_count=len(planned),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    (exp / "manifest.json").write_text(json.dumps(manifest, indent=1))

    s = Settings(workers=tuple(args.workers), n_variants=args.n, fixed_reps=args.reps, run_cost_usd=args.run_cost_usd,
                 probe_depth=args.probe_depth)
    dispatcher = None
    if args.batch:
        dispatcher = BatchDispatcher(requests_http(os.environ["OPENROUTER_API_KEY"]), exp / "openrouter_batches.jsonl",
                                     {w: get_spec(w) for w in args.workers}, max_cost_usd=args.session_cost_usd)
        s.client = lambda key, trace: LLMClient(get_spec(key), trace, transport=dispatcher.transport)
    lock, spent, log = threading.Lock(), [0.0], exp / "batch.jsonl"

    def job(kind: str, chain, worker=None, rep=0):
        with lock:
            if spent[0] >= args.session_cost_usd:
                return
        out = exp / "runs" / chain.question_id
        try:
            if kind == "routed":
                res = run_routed(chain, out, s)
                cost = sum(json.loads(p.read_text())["cost_usd"]
                           for p in out.glob("consistency_probe_*/record.json")) + res["routed"].get("cost_usd", 0)
                line = {"question_id": chain.question_id, "arm": "consistency_routed", "worker": res["choice"]["chosen"],
                        "status": res["routed"]["status"], "cost_usd": cost}
            else:
                rec = run_pipeline(chain, worker, out / f"fixed_{worker}_r{rep}", s, arm=f"fixed_{worker}", rep=rep)
                line = {"question_id": chain.question_id, "arm": f"fixed_{worker}", "worker": worker, "rep": rep,
                        "status": rec["status"], "cost_usd": rec["cost_usd"]}
        except Exception as e:  # noqa: BLE001 - keep the batch going; the run counts as a failure
            line = {"question_id": chain.question_id, "kind": kind, "worker": worker, "rep": rep,
                    "status": "crashed", "error": repr(e)[:300], "cost_usd": 0.0}
        with lock:
            spent[0] += line["cost_usd"]
            with log.open("a") as f:
                f.write(json.dumps(line) + "\n")
            print(f"[${spent[0]:.3f}] {line['question_id'][:24]} {line.get('arm', kind)} {worker or ''} "
                  f"{line['status']}", flush=True)

    jobs = []
    for c in chains:  # routed first: its probes and pipeline are sequential, so it is the longest job
        jobs.append(("routed", c, None, 0))
        jobs += [("fixed", c, w, r) for r in range(args.reps) for w in args.workers]
    with ThreadPoolExecutor(len(jobs) if args.batch else args.parallel) as pool:
        list(pool.map(lambda j: job(*j), jobs))
    if dispatcher is not None:
        dispatcher.close()
        print(f"batch: charged ${dispatcher.charged_usd:.3f} (estimated per call ${dispatcher.estimated_usd:.3f})")
    print(f"done: {len(jobs)} jobs, recorded spend ${spent[0]:.3f} -> {exp}")


if __name__ == "__main__":
    main()
