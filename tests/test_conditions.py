"""The three refinement conditions on the `multi` pool (decisions P7, E7): who answers, the shared steps after
collection, the fixed executor, and the cost columns of score_runs."""

from __future__ import annotations

import json

from fakes import ScriptedLLM, delegate, finish
from minpilot.config import load_pool, load_refiner
from minpilot.llm.specs import get_spec
from test_harness import make_run

LUNA, HAIKU = "openai/gpt-6-luna-20260922", "anthropic/claude-haiku-5.5-20261007"
DRAFT = "Count the orders in attachments/sheet.csv for 2025."
REWRITTEN = "Count UNIQUE order ids in attachments/sheet.csv for 2025."
ISSUE = {"id": "i1", "kind": "assumption", "summary": "rows vs unique ids", "evidence": "r1 counts rows",
         "decision": "clarify", "resolution": "count unique ids"}


def script(**extra):
    s = {"orchestrator": [delegate("worker", DRAFT), finish("2")],
         "analyze": [{"issues": [ISSUE], "followups": [], "verifications": []}],
         "rewrite": [{"instruction": REWRITTEN, "changes": ["unique ids"], "unchanged": False}]}
    s.update(extra)
    return s


def ok_stages(run) -> list[str]:
    return [json.loads(l).get("stage") for l in (run.run_dir / "llm_calls.jsonl").read_text().splitlines()
            if '"status": "ok"' in l]


def test_multi_pool_has_a_fixed_executor_and_a_probe_only_haiku():
    pool = load_pool("multi")
    role = pool.roles["worker"]
    assert list(pool.roles) == ["worker"] and role.executor == "gen_luna"
    assert role.probe_workers == ("gen_luna", "gen_haiku")
    assert pool.workers["gen_haiku"].tools == pool.workers["gen_luna"].tools
    assert pool.workers["gen_haiku"].system_prompt == pool.workers["gen_luna"].system_prompt
    spec = get_spec("haiku-high")
    assert spec.model == HAIKU and spec.provider == "anthropic" and spec.reasoning == {"effort": "high"}
    assert spec.tools_allowed and spec.preserve_reasoning and not spec.sampling
    assert [load_refiner(c).probe_workers_for(role, pool) for c in
            ("c1_self_review", "c2_probe_executor", "c3_probe_multi")] == \
        [("gen_luna",), ("gen_luna",), ("gen_luna", "gen_haiku")]


def test_orchestrator_does_not_see_the_probe_only_worker(tmp_path, task):
    llm = ScriptedLLM({"orchestrator": [delegate("worker", DRAFT), finish("3")], "worker": ["3 orders"]})
    run = make_run(tmp_path, task, llm, pool="multi", refiner="A_none")
    run.run_fresh()
    system = llm.by_kind["orchestrator"][0]["messages"][0]["content"]
    assert "gen_haiku" not in system and "haiku" not in system.lower()
    assert [b["model"] for b in llm.by_kind["worker"]] == [LUNA]


def test_c1_predicts_the_executor_once_without_worker_calls(tmp_path, task):
    llm = ScriptedLLM(script(simulate=["predicted answers"], worker=["2 unique orders"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c1_self_review")
    run.run_fresh()
    assert len(llm.by_kind["simulate"]) == 1
    assert [b["model"] for b in llm.by_kind["worker"]] == [LUNA]  # execution only
    assert REWRITTEN in llm.by_kind["worker"][0]["messages"][1]["content"]
    assert ok_stages(run) == ["orchestrator", "refine.review", "refine.analyze", "refine.rewrite", "execution",
                              "orchestrator"]


def test_c2_probes_only_the_executor(tmp_path, task):
    llm = ScriptedLLM(script(worker=["probe answer luna", "2 unique orders"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c2_probe_executor")
    run.run_fresh()
    assert [b["model"] for b in llm.by_kind["worker"]] == [LUNA, LUNA]
    assert ok_stages(run) == ["orchestrator", "refine.probe", "refine.analyze", "refine.rewrite", "execution",
                              "orchestrator"]


def test_c3_probes_luna_and_haiku_independently_and_executes_on_luna(tmp_path, task):
    llm = ScriptedLLM(script(**{f"worker:{LUNA}": ["probe answer luna", "2 unique orders"],
                                f"worker:{HAIKU}": ["probe answer haiku"]}))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c3_probe_multi")
    info = run.run_fresh()
    assert info["status"] == "ok"
    probes, execution = llm.by_kind["worker"][:2], llm.by_kind["worker"][2]
    assert [b["model"] for b in probes] == [LUNA, HAIKU]
    assert not any("probe answer" in json.dumps(b["messages"]) for b in probes)  # neither sees the other
    a = llm.by_kind["analyze"][0]["messages"][-1]["content"]
    assert "probe answer luna" in a and "probe answer haiku" in a
    assert execution["model"] == LUNA and len(execution["messages"]) == 2
    assert REWRITTEN in execution["messages"][1]["content"]
    assert ok_stages(run) == ["orchestrator", "refine.probe", "refine.probe", "refine.analyze", "refine.rewrite",
                              "execution", "orchestrator"]


def test_c3_checks_run_through_the_executor(tmp_path, task):
    issue = {**ISSUE, "decision": "needs_verification"}
    llm = ScriptedLLM(script(
        analyze=[{"issues": [issue], "followups": [],
                  "verifications": [{"issue_id": "i1", "worker_id": "worker", "instruction": "check ids"}]}],
        **{f"worker:{LUNA}": ["probe answer luna", "ids repeat", "2 unique orders"],
           f"worker:{HAIKU}": ["probe answer haiku"]}))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c3_probe_multi")
    run.run_fresh()
    log = json.loads((run.run_dir / "refine" / "d0.json").read_text())
    assert [v["executed_by"] for v in log["verifications"]] == ["gen_luna"]
    assert [b["model"] for b in llm.by_kind["worker"]] == [LUNA, HAIKU, LUNA, LUNA]


def test_score_runs_cost_columns():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("score_runs", Path(__file__).parents[1] / "scripts" / "score_runs.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    usage = {"orchestrator": {"cost_usd": 0.5}, "refine.probe": {"cost_usd": 0.1},
             "refine.verify": {"cost_usd": 0.2, "tool_usd": 0.03}, "execution": {"cost_usd": 1.0, "tool_usd": 0.4}}
    assert abs(sr.refine_usd(usage) - 0.33) < 1e-12
    assert sr.checkpoint_usd(None) == 0.0


def test_one_role_is_named_the_worker_in_prompts(tmp_path, task):
    llm = ScriptedLLM(script(**{f"worker:{LUNA}": ["probe answer luna", "2 unique orders"],
                                f"worker:{HAIKU}": ["probe answer haiku"]}))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c3_probe_multi")
    run.run_fresh()
    report = llm.by_kind["orchestrator"][1]["messages"][-1]["content"]
    assert "Report from the worker (delegation 1)" in report and "actually sent to the worker" in report
    assert "sent to the worker, review its instruction" in llm.by_kind["analyze"][0]["messages"][-1]["content"]
    assert "executed by the worker," in llm.by_kind["rewrite"][0]["messages"][-1]["content"]
