import pytest
from minpilot.config import load_condition, load_pool, load_refiner
from test_harness import action, make_run


@pytest.mark.parametrize("condition", ["direct_execution", "adaptive_probe"])
@pytest.mark.parametrize("alias,wid", [("worker_1", "gen_luna"), ("worker_2", "gen_haiku")])
def test_all_registered_workers_are_executors(tmp_path, task, condition, alias, wid):
    script = {"orchestrator": [action(wid=alias), action("finish")], "worker": ["Execution: 2"]}
    if condition == "adaptive_probe":
        script.update(worker=["understanding: count\nplan: read", "understanding: count\nplan: read", "Execution: 2"],
                      orchestrator=[action("probe"), action(wid=alias), action("finish")])
    run, llm = make_run(tmp_path, task, script, condition)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert info["delegations"][0]["worker"] == wid and info["worker_aliases"][wid] == alias
    opening = llm.by_kind["orchestrator"][0]["messages"][1]["content"]
    assert "- worker_1:" in opening and "- worker_2:" in opening and wid not in opening
    assert len([a for a in run.records.artifacts if a["stage"] == "probe"]) == (2 if condition == "adaptive_probe" else 0)
    assert set(llm.by_kind) == {"orchestrator", "worker"}


def test_legacy_presets_rejected():
    for name in ["baseline", "self_review", "executor_probe", "adaptive_probe", "variants/probe_connected"]:
        with pytest.raises(ValueError, match="retired"):
            load_refiner(name)
    assert load_condition("direct_execution").name == "direct_execution"
    assert set(load_pool("multi").workers) == {"gen_luna", "gen_haiku"}
