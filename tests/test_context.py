import json
import pytest
from minpilot.memory import Memory
from minpilot.runtime.trace import Trace
from test_harness import action, evaluation, direct_script, make_run, row


def test_memory_preserves_missing_title_and_validates_state(tmp_path):
    memory = Memory(tmp_path / "artifacts", Trace(tmp_path))
    record = memory.add("worker", "probe", "no title\nfull original text")
    assert record["missing_title"] and memory.read(record["id"])["body"] == "no title\nfull original text"
    memory.replace([row()], evaluation="e", reason="Evidence supports the claim")
    assert json.loads(memory.context([], [0]))["state"][0]["status"] == "supported"
    for invalid in [[row(status="complete")], [row(ref="missing")], [row(type="unknown")]]:
        with pytest.raises(ValueError):
            memory.replace(invalid, evaluation="e", reason="Invalid update")
    assert memory.state == [row()]
    for selected in [[-1], [True], [1]]:
        with pytest.raises(ValueError):
            memory.context([], selected)


def test_old_reports_and_linked_tool_results_are_read_only(tmp_path, task):
    script = direct_script(orchestrator=[action(), {"action": "read_memory", "refs": ["t00000"]}, action("finish")],
                           worker=[{"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]},
                                   "Title: Count\nResult: 2"],
                           evaluator_execution=[{"action": "read_memory", "refs": ["t00000"]}, evaluation([row(ref="t00000")])])
    run, llm = make_run(tmp_path, task, script)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert run.memory.state == [row(ref="t00000")]
    assert "order_id,date,amount" in json.dumps(llm.by_kind["orchestrator"][-1])
    assert "order_id,date,amount" not in json.dumps(llm.by_kind["evaluator_execution"][0])
    assert "order_id,date,amount" in json.dumps(llm.by_kind["evaluator_execution"][1])


def test_context_selection_can_omit_current_state(tmp_path, task):
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


def test_tool_ids_work_for_reads_state_context_and_restore(tmp_path):
    memory = Memory(tmp_path / "original", Trace(None))
    report = memory.add("worker", "execution", "Title: Report\nPartial finding", status="tool_limit",
                        messages=[{"role": "tool", "tool_call_id": "call-1", "content": "SOURCE TEXT"}])
    tool_id = report["tool_ids"][0]
    assert memory.catalog()[0]["tool_ids"] == [tool_id]
    assert "SOURCE TEXT" not in json.dumps(memory.catalog())
    tool = memory.read(tool_id)
    assert tool["body"] == "SOURCE TEXT" and tool["parent_id"] == report["id"]
    assert tool["report_status"] == "tool_limit" and tool["tool_call_id"] == "call-1"
    tool["body"] = "MUTATED"
    assert memory.read(tool_id)["body"] == "SOURCE TEXT"
    memory.replace([row(ref=tool_id)], evaluation="evaluation", reason="Tool supports the claim")
    context = json.loads(memory.context([], [0]))
    assert context["state"][0]["refs"] == [tool_id]
    assert context["artifacts"][0]["body"] == "SOURCE TEXT"
    assert json.loads(memory.context([tool_id], []))["artifacts"][0]["id"] == tool_id
    restored = Memory(tmp_path / "restored", Trace(None))
    restored.load(memory.dump())
    assert restored.dump() == memory.dump()
    next_report = restored.add("other", "probe", "Title: Next\nPlan",
                               messages=[{"role": "tool", "content": "NEXT SOURCE"}])
    assert next_report["tool_ids"] == ["t00001"]
    assert restored.read(tool_id)["body"] == "SOURCE TEXT"
    with pytest.raises(ValueError, match="unknown memory ID"):
        restored.read(f"{report['id']}/tool/0")
    invalid = memory.dump()
    invalid["tool_artifacts"][0]["parent_id"] = "a99999"
    with pytest.raises(ValueError, match="invalid tool IDs/links"):
        Memory(tmp_path / "invalid", Trace(None)).load(invalid)


@pytest.mark.parametrize("updated", [
    [row(status="rejected")], [],
    [row(content="Corrected population contains three orders.")],
    [row(ref="a00002")],
])
def test_context_uses_latest_evaluator_state_without_approval(tmp_path, task, updated):
    script = direct_script(orchestrator=[action(), action(), action(state_rows=[0] if updated else []), action("finish")],
                           worker=["Title: Initial\n2", "Title: Correction\nNot 2", "Title: Follow-up\nDone"],
                           evaluator_execution=[evaluation([row()]), evaluation(updated), evaluation(updated)])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    payload = json.loads(llm.by_kind["orchestrator"][2]["messages"][1]["content"])
    assert payload["state"] == updated
    saved = json.loads((run.run_dir / "checkpoints/a2/state.json").read_text())
    assert saved["memory"]["state"] == updated
    assert saved["pending_action"]["context_snapshot"] == updated
    context = run.delegations[2]["context"]
    assert ([{k: v for k, v in r.items() if k != "row"} for r in json.loads(context)["state"]] if context else []) == updated
    events = (run.run_dir / "events.jsonl").read_text()
    assert '"event": "evaluation_decision"' not in events
    assert '"event": "decision_error"' not in events


def test_tool_record_preserves_call_arguments_and_original_result(tmp_path):
    memory = Memory(tmp_path / "artifacts", Trace(None))
    arguments = '{"code": "print(sum([2, 4, 6]))"}'
    report = memory.add("worker", "execution", "Title: Total\n12", messages=[
        {"role": "assistant", "tool_calls": [{"id": "call-1", "function": {
            "name": "run_python", "arguments": arguments}}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "12"},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "image payload"}}]},
    ])
    record = memory.read(report["tool_ids"][0])
    assert record["name"] == "run_python" and record["arguments"] == arguments
    assert record["body"] == "12" and record["content"] == "12"
    assert "image payload" not in json.dumps(record)
    restored = Memory(tmp_path / "restored", Trace(None))
    restored.load(memory.dump())
    assert restored.read(record["id"]) == record



def test_orchestrator_cannot_override_evaluator_state(tmp_path, task):
    script = direct_script(orchestrator=[action(), action("finish", state=[]), action("finish")])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["state"] == [row()]
    assert "unknown fields for orchestrator: state" in llm.by_kind["orchestrator"][2]["messages"][-1]["content"]
