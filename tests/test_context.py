import json
import pytest
from minpilot.memory import Memory
from minpilot.runtime.trace import Trace
from test_harness import action, evaluation, direct_script, make_run, row


def test_memory_preserves_missing_title_and_validates_state(tmp_path):
    memory = Memory(tmp_path / "artifacts", Trace(tmp_path))
    record = memory.add("worker", "probe", "no title\nfull original text")
    assert record["missing_title"] and memory.read(record["id"])["body"] == "no title\nfull original text"
    memory.replace([row()], evaluation="e", decision="ok")
    assert json.loads(memory.context([], [0]))["state"][0]["status"] == "supported"
    for invalid in [[row(status="complete")], [row(ref="missing")], [row(type="unknown")]]:
        with pytest.raises(ValueError):
            memory.replace(invalid, evaluation="e", decision="bad")
    assert memory.state == [row()]
    for selected in [[-1], [True], [1]]:
        with pytest.raises(ValueError):
            memory.context([], selected)


def test_old_reports_and_linked_tool_results_are_read_only(tmp_path, task):
    script = direct_script(orchestrator=[action(), {"action": "read_memory", "refs": ["a00000/tool/0"]}, action("finish")],
                           worker=[{"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]},
                                   "Title: Count\nResult: 2"],
                           evaluator_execution=[{"action": "read_memory", "refs": ["a00000/tool/0"]}, evaluation([row()])])
    run, llm = make_run(tmp_path, task, script)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert "order_id,date,amount" in json.dumps(llm.by_kind["orchestrator"][-1])
    assert "order_id,date,amount" not in json.dumps(llm.by_kind["evaluator_execution"][0])
    assert "order_id,date,amount" in json.dumps(llm.by_kind["evaluator_execution"][1])


def test_selection_uses_pre_update_snapshot(tmp_path, task):
    script = direct_script(orchestrator=[action(), action(artifact_ids=[], state_rows=[]), action("finish")],
                           worker=["Title: First\n2", "Title: Second\n2"],
                           evaluator_execution=[evaluation([row()]), evaluation([row()])])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    assert "Context (" not in json.dumps(llm.by_kind["worker"][1])
    assert run.memory.state == [row()]


def test_artifacts_cannot_be_overwritten_and_invalid_ids_cannot_restore(tmp_path):
    memory = Memory(tmp_path / "artifacts", Trace(None))
    memory.add("worker", "execution", "Title: Original\nORIGINAL")
    other = Memory(tmp_path / "artifacts", Trace(None))
    with pytest.raises(FileExistsError):
        other.add("worker", "execution", "REPLACEMENT")
    assert "ORIGINAL" in (tmp_path / "artifacts/a00000.json").read_text()
    with pytest.raises(ValueError, match="invalid artifact"):
        memory.load({"artifacts": [{"id": "../../escape"}], "state": []})
