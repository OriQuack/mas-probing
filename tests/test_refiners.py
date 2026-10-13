import json
import pytest
from fakes import Raw
from test_harness import action, evaluation, make_run


def probe_script(**extra):
    return {"orchestrator": [action("probe", wid=None), *extra.pop("orchestrator_select", [action("execute", wid="gen_haiku", instruction=None, instruction_id="a00004")]), action("finish")],
            "worker": ["Title: Luna\nprobe marker one", "Title: Haiku\nprobe marker two", "Title: Execution\n2"],
            "evaluator_probe": [evaluation(changes="Keep unique order scope")],
            "refiner": [{"action": "refine", "can_refine": True, "instruction": "Count distinct order IDs.",
                         "context_notes": "", "rationale": "Clarified counting unit."}],
            "evaluator_execution": [evaluation()], **extra}


def test_probe_evaluation_selection_refiner_execution_order(tmp_path, task):
    run, llm = make_run(tmp_path, task, probe_script(), "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    from fakes import kind_of
    assert [kind_of(b) for b in llm.bodies] == ["orchestrator", "worker", "worker", "evaluator_probe",
                                             "refiner", "orchestrator", "worker", "evaluator_execution", "orchestrator"]
    assert "probe marker one" in json.dumps(llm.by_kind["evaluator_probe"][0])
    assert "probe marker one" not in json.dumps(llm.by_kind["refiner"][0])
    assert "probe marker" not in json.dumps(llm.by_kind["worker"][-1])
    assert "Count distinct order IDs." in json.dumps(llm.by_kind["worker"][-1])


@pytest.mark.parametrize("replies", [[Raw("{"), Raw("{")], [{"action": "refine", "can_refine": False,
    "instruction": "", "context_notes": "", "rationale": "New criterion needs a decision."}]])
def test_refiner_failure_or_unavailable_edit_keeps_selected_draft(tmp_path, task, replies):
    script = probe_script(refiner=replies, orchestrator_select=[action(instruction=None, instruction_id="a00000")])
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert info["delegations"][0]["final"] == "Count unique orders in 2025."
    assert len(llm.by_kind["refiner"]) <= 2
    assert len(llm.by_kind["orchestrator"]) == 3


def test_probe_observations_forwarded_without_rewrite(tmp_path, task):
    script = probe_script(orchestrator_select=[action("execute", instruction=None, instruction_id="a00000", artifact_ids=["a00002"])])
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    assert len(llm.by_kind["refiner"]) == 1
    assert "probe marker two" in json.dumps(llm.by_kind["worker"][-1])
    assert "probe marker one" not in json.dumps(llm.by_kind["worker"][-1])


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_probe_budget_returns_to_decision_without_execution(tmp_path, task, limit):
    from dataclasses import replace
    from minpilot.config import ConditionConfig
    from minpilot.runtime.trace import Limits
    script = probe_script(orchestrator=[action("probe", wid=None), action("finish")])
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    run.cfg = replace(run.cfg, condition=ConditionConfig("adaptive_probe", budget=Limits(max_llm_calls=limit)))
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert not run.delegations and not llm.by_kind["refiner"] and not llm.by_kind["evaluator_execution"]
    payload = json.loads(llm.by_kind["orchestrator"][-1]["messages"][1]["content"])
    assert payload["evaluation"]["error"] and payload["state"] == []
    assert run.memory.artifacts
