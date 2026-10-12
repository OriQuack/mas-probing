import json
import pytest
from fakes import Raw
from test_harness import action, evaluation, make_run


def probe_script(**extra):
    return {"orchestrator": [action(wid=None), action("finish")],
            "worker": ["Title: Luna\nprobe marker one", "Title: Haiku\nprobe marker two", "Title: Execution\n2"],
            "evaluator_probe": [evaluation(changes="Keep unique order scope")],
            "orchestrator_select": [action("select", wid="gen_haiku", refine=True, changes="Keep unique order scope")],
            "refiner": [{"action": "refine", "reconsider": False, "instruction": "Count distinct order IDs.",
                         "context_notes": "", "rationale": "Clarified counting unit."}],
            "evaluator_execution": [evaluation()], **extra}


def test_probe_evaluation_selection_refiner_execution_order(tmp_path, task):
    run, llm = make_run(tmp_path, task, probe_script(), "multi_worker_probe")
    assert run.run_fresh()["status"] == "ok"
    from fakes import kind_of
    assert [kind_of(b) for b in llm.bodies] == ["orchestrator", "worker", "worker", "evaluator_probe",
                                             "orchestrator_select", "refiner", "worker", "evaluator_execution", "orchestrator"]
    assert "probe marker one" in json.dumps(llm.by_kind["evaluator_probe"][0])
    assert "probe marker one" not in json.dumps(llm.by_kind["refiner"][0])
    assert "probe marker" not in json.dumps(llm.by_kind["worker"][-1])
    assert "Count distinct order IDs." in json.dumps(llm.by_kind["worker"][-1])


@pytest.mark.parametrize("replies", [[Raw("{"), Raw("{")], [{"action": "refine", "reconsider": True,
    "instruction": "", "context_notes": "", "rationale": "New criterion needs a decision."}]])
def test_refiner_failure_or_reconsider_keeps_approved_draft(tmp_path, task, replies):
    script = probe_script(refiner=replies)
    if isinstance(replies[0], dict):
        script["orchestrator_select"].append(action("select", wid="gen_haiku"))
    run, llm = make_run(tmp_path, task, script, "multi_worker_probe")
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert info["delegations"][0]["final"] == "Count unique orders in 2025."
    assert len(llm.by_kind["refiner"]) <= 2


def test_probe_observations_forwarded_without_rewrite(tmp_path, task):
    script = probe_script(orchestrator_select=[action("select", artifact_ids=["a00001"])])
    run, llm = make_run(tmp_path, task, script, "multi_worker_probe")
    assert run.run_fresh()["status"] == "ok"
    assert not llm.by_kind["refiner"]
    assert "probe marker two" in json.dumps(llm.by_kind["worker"][-1])
    assert "probe marker one" not in json.dumps(llm.by_kind["worker"][-1])


def test_pre_execution_budget_does_not_escape_to_more_calls(tmp_path, task):
    from dataclasses import replace
    from minpilot.config import ConditionConfig
    from minpilot.runtime.trace import Limits
    script = probe_script()
    run, llm = make_run(tmp_path, task, script, "multi_worker_probe")
    run.cfg = replace(run.cfg, condition=ConditionConfig("multi_worker_probe", budget=Limits(max_llm_calls=0)))
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert len(llm.by_kind["worker"]) == 1  # execution only; scope prevents probe request
    assert not llm.by_kind["evaluator_probe"] and not llm.by_kind["orchestrator_select"]
    assert not llm.by_kind["refiner"]
    assert info["delegations"][0]["refine_status"] == "pre_execution_budget_exceeded"
