#!/usr/bin/env python
"""Segment routing, step 1: pick the linear chain segments and write every probe prompt (decision C34).

  python scripts/prepare_segment_routing.py --experiment outputs/experiments/<date>_longcot-segment-routing \
      [--difficulties easy medium hard] [--rewriter sonnet-high] [--session-cost-usd 5] [--reuse PREP.jsonl ...] \
      [--review REVIEW.json] [--env-file .env] [--dry-run]

Every linear question whose requested nodes include one in node_1..node_k (k = 8 easy, 6 medium, 4 hard) gives one
segment. The rewriter writes a paraphrase of the segment and one irrelevant sentence (perturbation_consistency.
segment_routing); every call is traced under prep/. Each item gets at most `TRIES` candidates over all rounds.
`--reuse` takes an earlier round's prep.jsonl; `--review` is that round's manual review:

  {"reject": [{"target_id", "item": "paraphrase" | "irrelevant_context", "reason"}],
   "drop_targets": [{"target_id", "reason"}]}

A rejected item is generated again while candidates remain (the rejected text stays in its history); `--recheck`
judges reused paraphrase candidates that failed again with the current checks, without a new one; `--manual` puts in
hand-written irrelevant sentences for items left without one (same checks, recorded as `claude_manual`); a dropped target
gets no prompts. Writes manifest.json, targets.jsonl, prep.jsonl and prompts.jsonl, the input of
scripts/run_perturbation_pilot.py. No gold answer is read here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from collections import Counter
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
from perturbation_consistency import longcot_math, segment_routing as sr  # noqa: E402
from perturbation_consistency.longcot_nodes import parse_chain  # noqa: E402

ITEMS = ("paraphrase", "irrelevant_context")


def used(item: dict) -> int:
    """Candidates an item has had: generated attempts plus earlier rounds' history."""
    return len(item.get("attempts", [])) + sum(len(h.get("attempts", [])) for h in item.get("history", []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", type=Path, required=True)
    ap.add_argument("--difficulties", nargs="+", default=["easy", "medium", "hard"])
    ap.add_argument("--rewriter", default="sonnet-high")
    ap.add_argument("--session-cost-usd", type=float, default=5.0)
    ap.add_argument("--reuse", nargs="*", type=Path, default=[])
    ap.add_argument("--review", type=Path, default=None)
    ap.add_argument("--env-file", type=Path, default=REPO / ".env")
    ap.add_argument("--recheck", action="store_true",
                    help="judge reused paraphrase candidates that failed again with the current checks (no new one)")
    ap.add_argument("--manual", type=Path, default=None,
                    help='JSON {"irrelevant_context": [{"target_id", "node", "sentence", "before"}]}: hand-written '
                         "sentences for items left without an accepted candidate, judged like generated ones")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    chains, targets = {}, []
    for d in args.difficulties:
        for q in longcot.load_questions("math", d, template="linear"):
            chain = parse_chain(q.question_id, q.prompt)
            if t := sr.segment_target(chain, d):
                chains[q.question_id] = chain
                targets.append(t)
    review = json.loads(args.review.read_text()) if args.review else {"reject": [], "drop_targets": []}
    dropped = {d["target_id"]: d["reason"] for d in review.get("drop_targets", [])}
    targets = [t for t in targets if t.target_id not in dropped]
    print(Counter(t.difficulty for t in targets), "nodes per segment:",
          dict(sorted(Counter(len(t.nodes) for t in targets).items())))
    if args.dry_run:
        t = next(t for t in targets if len(t.nodes) >= 3)
        chain = chains[t.question_id]
        demo = {"paraphrase": {"ok": True, "text": "<paraphrase of the segment>"},
                "irrelevant_context": {"ok": True, "node": t.nodes[1], "sentence": "<sentence>",
                                       "text": chain.node(t.nodes[1]).text + " <irrelevant sentence>"}}
        for row in sr.build_prompts(chain, t, demo):
            if row["condition"] != "repeat" or row["sample"] == 0:
                print(f"\n===== {row['target_id']} {row['condition']}#{row['sample']} {row['detail']} =====\n"
                      f"{row['prompt']}")
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
            reused[p["target_id"]] = p | {"reused_from": str(path)}
    rejected = {(r["target_id"], r["item"]): r["reason"] for r in review.get("reject", [])}
    manual = {m["target_id"]: m for m in json.loads(args.manual.read_text())["irrelevant_context"]} \
        if args.manual else {}

    def prepare(t) -> tuple[dict, list[dict]]:
        chain = chains[t.question_id]
        old = reused.get(t.target_id, {}).get("items", {})
        items, todo = {}, []
        for k in ITEMS:
            item = dict(old.get(k, {}))
            if (t.target_id, k) in rejected:
                item = {"kind": k, "ok": False, "history": item.get("history", []) + [
                    {k2: v for k2, v in item.items() if k2 != "history"} | {"rejected_by_review": rejected[
                        (t.target_id, k)]}]}
            if not item or (not item.get("ok") and (t.target_id, k) in rejected):
                todo.append(k)
            elif args.recheck and k == "paraphrase" and not item.get("ok") and item.get("attempts") \
                    and not any(a.get("rechecked") for a in item["attempts"]):
                todo.append("recheck:paraphrase")
            elif k == "irrelevant_context" and not item.get("ok") and t.target_id in manual:
                todo.append("manual:irrelevant_context")
            items[k] = item
        if todo:
            with lock:
                if spent[0] >= args.session_cost_usd:
                    return {"target_id": t.target_id, "skipped": "session cost cap", "items": items}, []
            trace = Trace(exp / "prep" / t.target_id.replace(":", "__"), Limits(max_cost_usd=2.0))
            client = LLMClient(spec, trace)
            with trace.tags(stage="segment_routing_prep", target=t.target_id):
                for k in todo:
                    if k == "manual:irrelevant_context":
                        m, before = manual[t.target_id], items["irrelevant_context"]
                        items["irrelevant_context"] = sr.manual_irrelevant(
                            client, chain, t.nodes, m["node"], m["sentence"], m["before"]) | {
                            "history": before.get("history", []) + [
                                {k2: v for k2, v in before.items() if k2 != "history"}]}
                        continue
                    if k == "recheck:paraphrase":
                        items["paraphrase"] = sr.recheck_paraphrase(client, chain, t.nodes, items["paraphrase"]) | {
                            "history": items["paraphrase"].get("history", [])}
                        continue
                    left = sr.TRIES - used(items[k])
                    fresh = (sr.paraphrase if k == "paraphrase" else sr.irrelevant_context)(
                        client, chain, t.nodes, tries=left)
                    items[k] = fresh | {"history": items[k].get("history", [])}
            with lock:
                spent[0] += trace.run_scope.counters()["cost_usd"]
        rec = {"target_id": t.target_id, "items": items, "generated": todo}
        return rec, sr.build_prompts(chain, t, items)

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
        purpose="Segment routing: probe workers on the first chain segment with published prompt perturbations, "
                "then every worker continues the chain node by node",
        run_roots=["runs", "continuation"], harness="perturbation_consistency.segment_routing",
        dataset={"name": "LongCoT", "domain": "math", "template": "linear", "difficulties": args.difficulties,
                 "segment_caps": sr.CAPS,
                 "revision": json.loads((longcot.LONGCOT_ROOT.parents[2] / "SOURCE.json").read_text())["revision"]},
        target_ids=[t.target_id for t in targets], conditions=list(sr.CONDITIONS), samples=sr.SAMPLES,
        instructions=[name for name, _ in sr.INSTRUCTIONS], surface=list(sr.SURFACE), tries=sr.TRIES,
        rewriter=spec.identity(), prep_cost_usd=round(spent[0], 4), prompt_count=len(prompts),
        reused_prep=[str(p) for p in args.reuse], review=review,
        manual=json.loads(args.manual.read_text()) if args.manual else None,
        equivalence_version=longcot_math.EQUIVALENCE_VERSION, git_commit=commit, uncommitted_changes=dirty,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    (exp / "manifest.json").write_text(json.dumps(manifest, indent=1))
    missing = [(p["target_id"], k) for p, _ in done for k, v in p["items"].items() if not v.get("ok")]
    print(f"prompts {len(prompts)}, prep cost ${spent[0]:.3f}, items without an accepted candidate {missing}")


if __name__ == "__main__":
    main()
