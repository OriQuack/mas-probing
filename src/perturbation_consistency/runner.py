"""Runs of one LongCoT chain: consistency probes on the first node, the routed pipeline, and fixed-worker pipelines.

Every run (one pipeline, or one worker's n first-node probes) has its own `Trace` directory, so calls, usage and cost
are recorded like minpilot runs (llm_calls.jsonl, messages.jsonl), plus a `record.json` with the node answers.
A node without an answer line, cut off by the token limit, or failed by the API stops its pipeline: the pipeline has
no final answer (scored wrong). The same rule holds for every arm.
"""

from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from minpilot.llm.client import HTTPError, LLMClient, TransientError
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import BudgetExceeded, InfraError, Limits, Trace
from perturbation_consistency import longcot_math
from perturbation_consistency.longcot_nodes import Chain, extract_answer, node_prompt

ClientFactory = Callable[[str, Trace], LLMClient]


def default_client(key: str, trace: Trace) -> LLMClient:
    return LLMClient(get_spec(key), trace)


@dataclass
class Settings:
    workers: tuple[str, ...]
    n_variants: int = 5
    fixed_reps: int = 3
    run_cost_usd: float = 2.0   # per run (one pipeline or one worker's probes)
    client: ClientFactory = default_client


def _call(client: LLMClient, trace: Trace, chain: Chain, name: str, values: dict, variant: int, **tags) -> dict:
    prompt = node_prompt(chain.node(name), values, variant)
    with trace.tags(node=name, variant=variant, **tags):
        try:
            res = client.chat([{"role": "user", "content": prompt}])
        except (InfraError, BudgetExceeded, HTTPError, TransientError) as e:
            return {"node": name, "variant": variant, "answer": None, "status": "error", "error": str(e)[:300]}
    answer = extract_answer(res.content)
    if res.finish_reason == "length":
        status = "length"
    else:
        status = "ok" if answer is not None else "no_answer"
    return {"node": name, "variant": variant, "answer": answer if status == "ok" else None, "status": status,
            "finish_reason": res.finish_reason, "completion_tokens": (res.usage or {}).get("completion_tokens")}


def _finish(trace: Trace, run_dir: Path, record: dict, t0: float) -> dict:
    counters = trace.run_scope.counters()
    record.update(cost_usd=counters["cost_usd"], llm_calls=counters["llm_calls"], wall_s=round(time.time() - t0, 1))
    (run_dir / "record.json").write_text(json.dumps(record, indent=1, ensure_ascii=False))
    return record


def run_pipeline(chain: Chain, worker: str, run_dir: Path, s: Settings, *, arm: str, rep: int,
                 given: dict[str, str] | None = None) -> dict:
    """Solve the chain's nodes in order with variant 0, starting after the nodes already `given`."""
    t0, values = time.time(), dict(given or {})
    trace = Trace(run_dir, Limits(max_cost_usd=s.run_cost_usd))
    client = s.client(worker, trace)
    nodes, status = [], "ok"
    with trace.tags(stage=arm, worker=worker, rep=rep):
        for node in chain.nodes:
            if node.name in values:
                continue
            r = _call(client, trace, chain, node.name, values, 0)
            nodes.append(r)
            if r["status"] != "ok":
                status = f"stopped_at_{node.name}:{r['status']}"
                break
            values[node.name] = r["answer"]
    final = {n: values.get(n) for n in chain.requested} if status == "ok" else None
    return _finish(trace, run_dir, {"question_id": chain.question_id, "arm": arm, "worker": worker, "rep": rep,
                                    "given": given or {}, "nodes": nodes, "status": status, "final": final}, t0)


def probe_first_node(chain: Chain, worker: str, run_dir: Path, s: Settings) -> dict:
    """The worker answers the first node once per instruction variant; consistency = largest equivalent group / n."""
    t0 = time.time()
    trace = Trace(run_dir, Limits(max_cost_usd=s.run_cost_usd))
    client = s.client(worker, trace)
    first = chain.nodes[0]
    with trace.tags(stage="consistency_probe", worker=worker):
        samples = [_call(client, trace, chain, first.name, {}, v) for v in range(s.n_variants)]
    answers = [x["answer"] for x in samples]
    groups = [g for g in longcot_math.group(answers) if answers[g[0]] is not None]
    top = groups[0] if groups else []
    record = {"question_id": chain.question_id, "arm": "consistency_probe", "worker": worker, "node": first.name,
              "samples": samples, "groups": [[answers[g[0]], len(g)] for g in groups],
              "modal_answer": answers[top[0]] if top else None, "consistency": len(top) / s.n_variants}
    return _finish(trace, run_dir, record, t0)


def choose(probes: dict[str, dict], question_id: str) -> dict:
    best = max(p["consistency"] for p in probes.values())
    tied = sorted(w for w, p in probes.items() if p["consistency"] == best)
    chosen = random.Random(f"tie:{question_id}").choice(tied)
    return {"chosen": chosen, "consistency": {w: p["consistency"] for w, p in probes.items()}, "tied": tied,
            "modal_answer": probes[chosen]["modal_answer"]}


def run_routed(chain: Chain, out: Path, s: Settings) -> dict:
    """Consistency probes (workers in parallel, each worker's variants one after another), then the chosen worker
    solves the rest from its modal first answer."""
    with ThreadPoolExecutor(len(s.workers)) as pool:
        found = pool.map(lambda w: probe_first_node(chain, w, out / f"consistency_probe_{w}", s), s.workers)
        probes = dict(zip(s.workers, found))
    pick = choose(probes, chain.question_id)
    (out / "choice.json").write_text(json.dumps(pick, indent=1, ensure_ascii=False))
    if pick["modal_answer"] is None:  # no worker produced a first answer: nothing to route
        record = {"question_id": chain.question_id, "arm": "consistency_routed", "worker": pick["chosen"], "rep": 0,
                  "given": {}, "nodes": [], "status": "no_first_answer", "final": None, "cost_usd": 0.0}
        (out / "consistency_routed_r0").mkdir(parents=True, exist_ok=True)
        (out / "consistency_routed_r0" / "record.json").write_text(json.dumps(record, indent=1))
        return {"choice": pick, "routed": record}
    routed = run_pipeline(chain, pick["chosen"], out / "consistency_routed_r0", s, arm="consistency_routed", rep=0,
                          given={chain.nodes[0].name: pick["modal_answer"]})
    return {"choice": pick, "routed": routed}
