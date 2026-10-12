import pytest
from fakes import Raw
from test_harness import action, direct_script, make_run


def test_invalid_reference_repaired_once(tmp_path, task):
    script = direct_script(orchestrator=[action(artifact_ids=["missing"]), action(), action("finish")])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    assert "unknown artifact" in llm.by_kind["orchestrator"][1]["messages"][-1]["content"]


def test_repeated_invalid_decisions_stop(tmp_path, task):
    run, _ = make_run(tmp_path, task, direct_script(orchestrator=[Raw("{"), Raw("{")]))
    assert run.run_fresh()["status"] == "error"


def test_reads_limited_to_three_rounds_with_one_repair(tmp_path, task):
    script = direct_script(orchestrator=[action()] + [{"action": "read_memory", "refs": ["a00000"]}] * 5)
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "error"
    events = (run.run_dir / "events.jsonl").read_text()
    assert events.count('"event": "read_memory"') == 3


def test_delegation_cap_requires_finish(tmp_path, task):
    run, llm = make_run(tmp_path, task, {"orchestrator": [action(), action("finish")]}, max_delegations=0)
    assert run.run_fresh()["status"] == "ok"
    assert not run.delegations
    assert "return finish" in llm.by_kind["orchestrator"][1]["messages"][-1]["content"]


def test_finish_accepts_nullable_unused_schema_fields(tmp_path, task):
    reply = action("finish", instruction=None, worker_id=None, artifact_ids=None, state_rows=None)
    run, _ = make_run(tmp_path, task, {"orchestrator": [reply]})
    assert run.run_fresh()["status"] == "ok"
