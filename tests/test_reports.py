"""Worker reports reach the orchestrator verbatim, including failed, empty and partial ones (offline)."""
import pytest
from test_harness import action, direct_script, make_run, probe_script, tool_results


@pytest.mark.parametrize("failures", [1, 2])
def test_partial_and_total_probe_failure_are_reported(tmp_path, task, failures):
    script = probe_script(worker=[RuntimeError("blocked") if i < failures else "plan: read" for i in range(2)]
                                 + ["Execution: 2"],
                          orchestrator_select=[action("execute")])
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    info = run.run_fresh()
    assert info["status"] == "ok", info
    result = tool_results(llm.by_kind["orchestrator"][1])[0]
    assert result.count("status failed") == failures and "blocked" in result
    assert len(llm.by_kind["worker"][-1]["messages"]) == 2


def test_empty_execution_report_is_preserved(tmp_path, task):
    run, llm = make_run(tmp_path, task, direct_script(worker=[""]))
    assert run.run_fresh()["status"] == "ok"
    artifact = run.records.artifacts[1]
    assert artifact["body"] == "" and artifact["status"] == "empty"
    assert "(execution request, status empty):\n(no text)" in tool_results(llm.by_kind["orchestrator"][1])[0]


def test_failed_probe_keeps_partial_tool_evidence(tmp_path, task):
    script = probe_script(worker=[{"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]},
                                  RuntimeError("model failed after tool"), "plan: read", "Execution: 2"],
                          orchestrator_select=[action("execute")])
    run, _ = make_run(tmp_path, task, script, "adaptive_probe")
    info = run.run_fresh()
    assert info["status"] == "ok", info
    failed = run.records.artifacts[1]
    assert failed["status"] == "failed"
    assert "order_id,date,amount" in run.records.read(failed["tool_ids"][0])["content"]


def test_reports_and_instructions_preserve_exact_text(tmp_path, task):
    report = "  Padded\nResult: 2\n  "
    instruction = "  Count unique orders.\n"
    run, llm = make_run(tmp_path, task, direct_script(worker=[report],
                                                      orchestrator=[action(instruction=instruction), action("finish")]))
    assert run.run_fresh()["status"] == "ok"
    assert run.records.artifacts[0]["body"] == instruction and run.records.artifacts[0]["stage"] == "instruction"
    assert run.records.artifacts[1]["body"] == report
    assert run.delegations[0]["instruction"] == instruction
