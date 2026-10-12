"""Runs of one LongCoT chain: consistency probes on the first nodes, the routed pipeline, and fixed-worker pipelines.

Every run (one pipeline, or one worker's probes) has its own `Trace` directory, so calls, usage and cost
are recorded like minpilot runs (llm_calls.jsonl, messages.jsonl), plus a `record.json` with the node answers.
A node without an answer line, cut off by the token limit, or failed by the API stops its pipeline: the pipeline has
no final answer (scored wrong). The same rule holds for every arm.
"""

from __future__ import annotations

import contextvars
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
    probe_depth: int = 1        # probe up to this many first nodes; later nodes only for workers still tied
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


def _parallel(thunks: list[Callable[[], dict]]) -> list[dict]:
    """Run the calls at once (one batch round under the batch transport); each thread keeps the caller's tags."""
    with ThreadPoolExecutor(max(1, len(thunks))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, f) for f in thunks]
        return [f.result() for f in futures]


def _consistency(samples: list[dict], n: int) -> dict:
    answers = [x["answer"] for x in samples]
    groups = [g for g in longcot_math.group(answers) if answers[g[0]] is not None]
    top = groups[0] if groups else []
    return {"groups": [[answers[g[0]], len(g)] for g in groups], "modal_answer": answers[top[0]] if top else None,
            "modal_variants": sorted(top), "consistency": len(top) / n}


def run_probes(chain: Chain, out: Path, s: Settings) -> dict:
    """Consistency probes on the first `s.probe_depth` nodes, then the worker choice.

    Each worker solves the first node once per instruction variant; variant v's chain passes its own answer on to
    the next node, so a disagreement or a failed node propagates. After each node only the workers tied for the
    highest consistency (largest equivalent group / n) go on to the next node. A tie left after the last probed
    node is broken by a seed per question. The routed pipeline starts from the chosen worker's lowest variant chain
    in its final modal group."""
    n = s.n_variants
    t0 = time.time()
    traces = {w: Trace(out / f"consistency_probe_{w}", Limits(max_cost_usd=s.run_cost_usd)) for w in s.workers}
    clients = {w: s.client(w, traces[w]) for w in s.workers}
    paths = {w: [{} for _ in range(n)] for w in s.workers}  # variant chain -> {node: answer}
    alive = {w: [True] * n for w in s.workers}
    rounds: dict[str, list[dict]] = {w: [] for w in s.workers}
    history, contenders = [], list(s.workers)

    def one(w: str, v: int, node: str) -> dict:
        if not alive[w][v]:
            return {"node": node, "variant": v, "answer": None, "status": "chain_stopped"}
        with traces[w].tags(stage="consistency_probe", worker=w):
            return _call(clients[w], traces[w], chain, node, paths[w][v], v)

    for node in [x.name for x in chain.nodes[:s.probe_depth]]:
        jobs = [(w, v) for w in contenders for v in range(n)]
        results = dict(zip(jobs, _parallel([lambda w=w, v=v: one(w, v, node) for w, v in jobs])))
        cons = {}
        for w in contenders:
            samples = [results[(w, v)] for v in range(n)]
            for v, r in enumerate(samples):
                if r["status"] == "ok":
                    paths[w][v][node] = r["answer"]
                else:
                    alive[w][v] = False
            rounds[w].append({"node": node, "samples": samples, **_consistency(samples, n)})
            cons[w] = rounds[w][-1]["consistency"]
        best = max(cons.values())
        after = [w for w in contenders if cons[w] == best]
        history.append({"node": node, "consistency": cons, "contenders": contenders, "kept": after})
        contenders = after
        if len(contenders) == 1:
            break

    for w in s.workers:
        first = rounds[w][0]
        record = {"question_id": chain.question_id, "arm": "consistency_probe", "worker": w, "rounds": rounds[w],
                  # node-0 fields as in the single-node probe
                  "node": first["node"], "samples": first["samples"], "groups": first["groups"],
                  "modal_answer": first["modal_answer"], "consistency": first["consistency"]}
        _finish(traces[w], out / f"consistency_probe_{w}", record, t0)

    tied = sorted(contenders)
    chosen = random.Random(f"tie:{chain.question_id}").choice(tied)
    last = rounds[chosen][-1]
    variant = last["modal_variants"][0] if last["modal_variants"] else None
    pick = {"chosen": chosen, "tied": tied, "consistency": {w: rounds[w][0]["consistency"] for w in s.workers},
            "rounds": history, "probed_nodes": len(history), "path_variant": variant,
            "given": dict(paths[chosen][variant]) if variant is not None else {},
            "modal_answer": last["modal_answer"]}
    (out / "choice.json").write_text(json.dumps(pick, indent=1, ensure_ascii=False))
    return pick


def run_routed(chain: Chain, out: Path, s: Settings) -> dict:
    """Consistency probes, then the chosen worker solves the rest from its probe chain's answers."""
    pick = run_probes(chain, out, s)
    if not pick["given"]:  # the chosen worker produced no answer on the probed nodes: nothing to route
        record = {"question_id": chain.question_id, "arm": "consistency_routed", "worker": pick["chosen"], "rep": 0,
                  "given": {}, "nodes": [], "status": "no_first_answer", "final": None, "cost_usd": 0.0}
        (out / "consistency_routed_r0").mkdir(parents=True, exist_ok=True)
        (out / "consistency_routed_r0" / "record.json").write_text(json.dumps(record, indent=1))
        return {"choice": pick, "routed": record}
    routed = run_pipeline(chain, pick["chosen"], out / "consistency_routed_r0", s, arm="consistency_routed", rep=0,
                          given=pick["given"])
    return {"choice": pick, "routed": routed}
