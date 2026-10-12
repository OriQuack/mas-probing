import json
import pytest
from minpilot.config import load_condition, load_pool, load_refiner
from test_harness import action, evaluation, make_run


@pytest.mark.parametrize("condition", ["direct_execution", "adaptive_probe"])
@pytest.mark.parametrize("wid", ["gen_luna", "gen_haiku"])
def test_all_registered_workers_are_executors(tmp_path, task, condition, wid):
    script = {"orchestrator": [action(wid=wid), action("finish")],
              "worker": ["Title: Execution\nResult: 2"], "evaluator_execution": [evaluation()]}
    if condition == "adaptive_probe":
        script.update(worker=["Title: Luna probe\nunderstanding: count\nplan: read\nassumptions:\nrisks:",
                              "Title: Haiku probe\nunderstanding: count\nplan: read\nassumptions:\nrisks:",
                              "Title: Execution\nResult: 2"],
                      evaluator_probe=[evaluation()], orchestrator=[action("probe", wid=None), action(wid=wid), action("finish")])
    run, llm = make_run(tmp_path, task, script, condition)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert info["delegations"][0]["worker"] == wid
    payload = json.loads(llm.by_kind["orchestrator"][0]["messages"][1]["content"])
    assert {w["id"] for w in payload["workers"]} == {"gen_luna", "gen_haiku"}
    assert len([a for a in run.memory.artifacts if a["stage"] == "probe"]) == (2 if condition == "adaptive_probe" else 0)
    assert len(llm.by_kind["refiner"]) == (2 if condition == "adaptive_probe" else 0)


def test_legacy_presets_rejected():
    for name in ["baseline", "self_review", "executor_probe", "adaptive_probe", "variants/probe_connected"]:
        with pytest.raises(ValueError, match="retired"):
            load_refiner(name)
    assert load_condition("direct_execution").name == "direct_execution"
    assert set(load_pool("multi").workers) == {"gen_luna", "gen_haiku"}
