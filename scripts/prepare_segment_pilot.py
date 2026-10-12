#!/usr/bin/env python
"""Segment pilot, step 1: pick linear chain segments and write every worker prompt (perturbation_consistency.segment).

  python scripts/prepare_segment_pilot.py --experiment outputs/experiments/<date>_longcot-segment-pilot \
      [--difficulties medium hard] [--rewriter sonnet-high] [--session-cost-usd 5] [--reuse PREP.jsonl ...] \
      [--review REVIEW.json] [--env-file .env] [--dry-run]

Every linear question of the listed difficulties whose requested nodes include one in node_1..node_4 gives one
segment, node_0 up to the first such node. The rewriter writes the segment's paraphrase, its Given/Dependencies/Find
restatement, a related note and three strategies; every call is traced under prep/. `--reuse` takes earlier
prep.jsonl records for the same targets; `--review` drops items found wrong in a manual review (a rewrite kind or
`approach:<i>`). Writes manifest.json, targets.jsonl, prep.jsonl and prompts.jsonl, the input of
scripts/run_perturbation_pilot.py. No gold answer is read here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.artifacts import experiment_manifest  # noqa: E402
from minpilot.data import longcot  # noqa: E402
from minpilot.llm.client import LLMClient  # noqa: E402
from minpilot.llm.specs import get_spec  # noqa: E402
from minpilot.runtime.trace import Limits, Trace  # noqa: E402
from perturbation_consistency import longcot_math, perturb, segment  # noqa: E402
from perturbation_consistency.longcot_nodes import parse_chain  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--difficulties", nargs="+", default=["medium", "hard"])
    ap.add_argument("--rewriter", default="sonnet-high")
    ap.add_argument("--session-cost-usd", type=float, default=5.0)
    ap.add_argument("--reuse", nargs="*", type=Path, default=[])
    ap.add_argument("--review", type=Path, default=None)
    ap.add_argument("--env-file", type=Path, default=REPO / ".env")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    chains, targets = {}, []
    for d in args.difficulties:
        for q in longcot.load_questions("math", d, template="linear"):
            chain = parse_chain(q.question_id, q.prompt)
            if t := segment.segment_target(chain, d):
                chains[q.question_id] = chain
                targets.append(t)
    for t in targets:
        print(f"{t.target_id:24} {t.difficulty:6} {len(t.nodes)} nodes")
    if args.dry_run:
        t = targets[0]
        print("\n" + segment.build_prompts(chains[t.question_id], t, {}, ["<strategy>"])[3]["prompt"])
        return

    from dotenv import load_dotenv
    load_dotenv(args.env_file)
    exp = args.experiment
    if (exp / "manifest.json").exists():
        sys.exit(f"{exp} already has a manifest; use a new experiment directory")
    (exp / "prep").mkdir(parents=True)
    spec = get_spec(args.rewriter)
    lock, spent = threading.Lock(), [0.0]
    reused = {}
    for path in args.reuse:
        for line in path.read_text().splitlines():
            p = json.loads(line)
            reused[p["target_id"]] = {k: v for k, v in p.items() if k != "reviewed"} | {"reused_from": str(path)}
    review = json.loads(args.review.read_text()) if args.review else {"drop": []}

    def apply_review(prep: dict) -> tuple[dict, list[str]]:
        rewrites = {k: dict(v) for k, v in prep["rewrites"].items()}
        methods = list(prep["approaches"])
        for d in review["drop"]:
            if d["target_id"] == prep["target_id"]:
                if d["item"].startswith("approach:"):
                    methods[int(d["item"].split(":")[1])] = None
                else:
                    rewrites[d["item"]] |= {"ok": False, "dropped_by_review": d["reason"]}
        return rewrites, [m for m in methods if m is not None]

    def prepare(t: segment.Target) -> tuple[dict, list[dict]]:
        chain = chains[t.question_id]
        text = segment.segment_text(chain, t.nodes)
        if t.target_id in reused:
            prep = reused[t.target_id]
        else:
            with lock:
                if spent[0] >= args.session_cost_usd:
                    return {"target_id": t.target_id, "skipped": "session cost cap"}, []
            trace = Trace(exp / "prep" / t.target_id.replace(":", "__"), Limits(max_cost_usd=2.0))
            client = LLMClient(spec, trace)
            with trace.tags(stage="segment_prep", target=t.target_id):
                rewrites = {k: segment.rewrite(client, k, text, t.nodes) for k in ("paraphrase", "structured")}
                rewrites["related_fact"] = segment.related_fact(client, text)
                methods = segment.strategies(client, text)
            cost = trace.run_scope.counters()["cost_usd"]
            with lock:
                spent[0] += cost
            prep = {"target_id": t.target_id, "rewrites": rewrites, "approaches": methods, "cost_usd": cost}
        rewrites, methods = apply_review(prep)
        return prep | {"reviewed": {"rewrites": rewrites, "approaches": methods}}, \
            segment.build_prompts(chain, t, rewrites, methods)

    with ThreadPoolExecutor(8) as pool:
        done = list(pool.map(prepare, targets))
    prompts = [row for _, rows in done for row in rows]
    (exp / "targets.jsonl").write_text("".join(json.dumps(asdict(t)) + "\n" for t in targets))
    (exp / "prep.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p, _ in done))
    (exp / "prompts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in prompts))
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "src", "scripts"],
                                capture_output=True, text=True).stdout.strip())
    manifest = experiment_manifest(
        purpose="Segment pilot: which whole-segment perturbation makes worker consistency informative",
        run_roots=["runs"], harness="perturbation_consistency.segment",
        dataset={"name": "LongCoT", "domain": "math", "template": "linear", "difficulties": args.difficulties,
                 "revision": json.loads((longcot.LONGCOT_ROOT.parents[2] / "SOURCE.json").read_text())["revision"]},
        target_ids=[t.target_id for t in targets], conditions=list(perturb.CONDITIONS), samples=segment.SAMPLES,
        rewriter=spec.identity(), prep_cost_usd=round(spent[0], 4), prompt_count=len(prompts),
        reused_prep=[str(p) for p in args.reuse], review=review,
        equivalence_version=longcot_math.EQUIVALENCE_VERSION, git_commit=commit, uncommitted_changes=dirty,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    (exp / "manifest.json").write_text(json.dumps(manifest, indent=1))
    failed = [(p["target_id"], k) for p, _ in done for k, r in p.get("reviewed", {}).get("rewrites", {}).items()
              if not r["ok"]]
    short = [p["target_id"] for p, _ in done if len(p.get("reviewed", {}).get("approaches", [])) < segment.SAMPLES]
    print(f"prompts {len(prompts)}, prep cost ${spent[0]:.3f}, rewrites dropped {failed}, short strategy lists {short}")


if __name__ == "__main__":
    main()
