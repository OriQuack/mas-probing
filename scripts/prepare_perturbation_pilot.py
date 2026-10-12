#!/usr/bin/env python
"""Perturbation pilot, step 1: pick target nodes and write every worker prompt (perturbation_consistency.perturb).

  python scripts/prepare_perturbation_pilot.py --experiment outputs/experiments/<date>_longcot-perturbation-pilot \
      [--quota hard:first:8 hard:middle:8 medium:first:2 medium:middle:2] [--templates linear dag] [--seed 0] \
      [--rewriter sonnet-medium] [--session-cost-usd 3] [--env-file .env] [--dry-run]

Targets are requested nodes whose dependencies are requested too, so a middle node gets its inputs from the gold
answers of the nodes it depends on (decision C32; its own gold answer is never shown). The rewriting model writes the
paraphrase and structured restatement of each node and its approach list; every call is traced under prep/.
Writes manifest.json, targets.jsonl, prep.jsonl (rewrites with their checks, approaches) and prompts.jsonl, the
input of scripts/run_perturbation_pilot.py. `--dry-run` picks the targets and prints them without model calls.
"""

from __future__ import annotations

import argparse
import json
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
from minpilot.runtime.trace import Limits, Trace  # noqa: E402
from perturbation_consistency import longcot_math, perturb  # noqa: E402
from perturbation_consistency.longcot_nodes import parse_chain  # noqa: E402


def target_pool(templates: list[str], difficulties: set[str]) -> tuple[list[perturb.Target], dict]:
    pool, chains = [], {}
    for difficulty in sorted(difficulties):
        refs = longcot.load_references("math", difficulty)  # gold: dependency inputs only (C32)
        for template in templates:
            for q in longcot.load_questions("math", difficulty, template=template):
                chain = parse_chain(q.question_id, q.prompt)
                gold = dict(zip(chain.requested, longcot_math.answer_parts(refs[q.question_id].answer)))
                chains[q.question_id] = chain
                pool += perturb.eligible_targets(chain, gold, difficulty, template)
    return pool, chains


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--quota", nargs="+", default=["hard:first:8", "hard:middle:8", "medium:first:2",
                                                   "medium:middle:2"])
    ap.add_argument("--templates", nargs="+", default=["linear", "dag"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rewriter", default="sonnet-medium")
    ap.add_argument("--session-cost-usd", type=float, default=3.0)
    ap.add_argument("--env-file", type=Path, default=REPO / ".env")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    quota = {(d, k): int(n) for d, k, n in (q.split(":") for q in args.quota)}
    pool, chains = target_pool(args.templates, {d for d, _ in quota})
    targets = perturb.pick_targets(pool, quota, args.seed)
    for t in targets:
        print(f"{t.target_id:28} {t.difficulty:6} {t.template:7} {t.kind:6} inputs {list(t.inputs)}")
    if args.dry_run:
        t = targets[-1]
        node = chains[t.question_id].node(t.node)
        print("\n" + perturb.build_prompts(node, t, {}, ["<approach 1>"])[0]["prompt"])
        return

    from dotenv import load_dotenv
    load_dotenv(args.env_file)
    exp = args.experiment
    if (exp / "manifest.json").exists():
        sys.exit(f"{exp} already has a manifest; use a new experiment directory")
    (exp / "prep").mkdir(parents=True)
    spec = get_spec(args.rewriter)
    lock, spent = threading.Lock(), [0.0]

    def prepare(t: perturb.Target) -> tuple[dict, list[dict]]:
        node = chains[t.question_id].node(t.node)
        with lock:
            if spent[0] >= args.session_cost_usd:
                return {"target_id": t.target_id, "skipped": "session cost cap"}, []
        trace = Trace(exp / "prep" / t.target_id.replace(":", "__"), Limits(max_cost_usd=1.0))
        client = LLMClient(spec, trace)
        with trace.tags(stage="perturbation_prep", target=t.target_id):
            rewrites = {k: perturb.rewrite(client, k, node.text) for k in ("paraphrase", "structured")}
            rewrites["related_fact"] = perturb.related_fact(client, node.text)
            methods = perturb.approaches(client, perturb.body(node, node.text, t.inputs))
        cost = trace.run_scope.counters()["cost_usd"]
        with lock:
            spent[0] += cost
        prep = {"target_id": t.target_id, "rewrites": rewrites, "approaches": methods, "cost_usd": cost}
        return prep, perturb.build_prompts(node, t, rewrites, methods)

    with ThreadPoolExecutor(8) as pool_:
        done = list(pool_.map(prepare, targets))
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "src", "scripts"],
                                capture_output=True, text=True).stdout.strip())
    prompts = [row for _, rows in done for row in rows]
    (exp / "targets.jsonl").write_text("".join(perturb.target_record(t) + "\n" for t in targets))
    (exp / "prep.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p, _ in done))
    (exp / "prompts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in prompts))
    manifest = experiment_manifest(
        purpose="Perturbation pilot: which perturbation makes single-node worker consistency informative",
        run_roots=["runs"], harness="perturbation_consistency.perturb",
        dataset={"name": "LongCoT", "domain": "math", "templates": args.templates,
                 "revision": json.loads((longcot.LONGCOT_ROOT.parents[2] / "SOURCE.json").read_text())["revision"]},
        quota={f"{d}:{k}": n for (d, k), n in quota.items()}, seed=args.seed,
        target_ids=[t.target_id for t in targets], conditions=list(perturb.CONDITIONS), samples=perturb.SAMPLES,
        rewriter=spec.identity(), prep_cost_usd=round(spent[0], 4), prompt_count=len(prompts),
        equivalence_version=longcot_math.EQUIVALENCE_VERSION, git_commit=commit, uncommitted_changes=dirty,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    (exp / "manifest.json").write_text(json.dumps(manifest, indent=1))
    failed = [(p["target_id"], k) for p, _ in done for k, r in (p.get("rewrites") or {}).items() if not r["ok"]]
    short = [p["target_id"] for p, _ in done if len(p.get("approaches") or []) < perturb.SAMPLES]
    print(f"prompts {len(prompts)}, prep cost ${spent[0]:.3f}, rewrites dropped {failed}, short approach lists {short}")


if __name__ == "__main__":
    main()
