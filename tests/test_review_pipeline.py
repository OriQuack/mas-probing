import json
import pytest
from fakes import Raw
from test_harness import action, evaluation, direct_script, make_run, row
from test_refiners import probe_script


def test_evaluator_failure_preserves_prior_state_and_original_reports(tmp_path, task):
    script = direct_script(orchestrator=[action(), action(), action("finish")],
                           worker=["Title: First\n2", "UNTITLED ORIGINAL SECOND REPORT"],
                           evaluator_execution=[evaluation([row()]), Raw("{"), evaluation([row(ref="missing")])])
    run, llm = make_run(tmp_path, task, script)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert info["state"] == [row()]
    assert run.memory.artifacts[4]["body"] == "UNTITLED ORIGINAL SECOND REPORT"
    assert run.memory.artifacts[-1]["status"] == "failed"
    assert run.memory.artifacts[-2]["body"] == "{"
    assert json.loads(run.memory.artifacts[-1]["body"])["state"][0]["refs"] == ["missing"]
    payload = json.loads(llm.by_kind["orchestrator"][-1]["messages"][1]["content"])
    assert payload["evaluation"]["error"] and payload["evaluation"]["new_report_ids"] == ["a00004"]


def test_probe_evaluator_updates_state_before_executor_selection(tmp_path, task):
    updated = row("a00000", type="assumption", status="rejected", content="Exclude canceled orders: not required by the question.")
    script = probe_script(evaluator_probe=[evaluation([updated])],
                          orchestrator_select=[action("execute", state_rows=[0])])
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    selection = json.loads(llm.by_kind["orchestrator"][1]["messages"][1]["content"])
    assert selection["state"] == [updated]
    context = json.loads(run.delegations[0]["context"])
    assert context["state"][0]["status"] == "rejected"
    execution_eval = json.loads(llm.by_kind["evaluator_execution"][0]["messages"][1]["content"])
    assert execution_eval["state"] == [updated]


@pytest.mark.parametrize("failures", [1, 2])
def test_partial_and_total_probe_failure_are_evaluated(tmp_path, task, failures):
    script = probe_script(worker=[RuntimeError("blocked") if i < failures else "Title: Probe\nplan: read" for i in range(2)]
                                 + ["Title: Execution\nResult: 2"],
                          orchestrator_select=[action("execute")])
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    info = run.run_fresh()
    assert info["status"] == "ok", info
    payload = json.loads(llm.by_kind["evaluator_probe"][0]["messages"][1]["content"])
    assert sum(r["status"] == "failed" for r in payload["reports"]) == failures
    assert len(llm.by_kind["worker"][-1]["messages"]) == 2


def test_empty_execution_report_is_preserved(tmp_path, task):
    run, llm = make_run(tmp_path, task, direct_script(worker=[""]))
    assert run.run_fresh()["status"] == "ok"
    artifact = run.memory.artifacts[1]
    assert artifact["body"] == "" and artifact["status"] == "empty" and artifact["missing_title"]
    ev = json.loads(llm.by_kind["evaluator_execution"][0]["messages"][1]["content"])
    assert ev["reports"][0]["body"] == "" and ev["reports"][0]["status"] == "empty"


def test_state_supports_conditional_results_unverified_assumptions_and_blocked_progress(tmp_path, task):
    state = [row(type="observation", content="The sheet was read for 2025."),
             row(type="assumption", status="unverified", content="Treat recipient as the second column."),
             row(content="If the second column identifies recipient, candidate is Fred."),
             row(type="progress", status="incomplete", content="Check column meaning against story."),
             row(type="progress", status="blocked", content="Query X: source Y inaccessible; abstract read, body blocked; next clue Z.")]
    run, _ = make_run(tmp_path, task, direct_script(evaluator_execution=[evaluation(state)]))
    assert run.run_fresh()["state"] == state


def test_failed_probe_keeps_partial_tool_evidence(tmp_path, task):
    script = probe_script(worker=[{"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]},
                                  RuntimeError("model failed after tool"), "Title: Other probe\nplan: read", "Title: Execution\n2"],
                          orchestrator_select=[action("execute")])
    run, _ = make_run(tmp_path, task, script, "adaptive_probe")
    info = run.run_fresh()
    assert info["status"] == "ok", info
    failed = run.memory.artifacts[1]
    assert failed["status"] == "failed"
    assert "order_id,date,amount" in run.memory.read(failed["tool_ids"][0])["content"]


def test_artifacts_preserve_exact_response_text(tmp_path, task):
    report = "  Title: Padded\nResult: 2\n  "
    raw_eval = "\n" + json.dumps(evaluation()) + "  "
    run, _ = make_run(tmp_path, task, direct_script(worker=[report], evaluator_execution=[Raw(raw_eval)]))
    assert run.run_fresh()["status"] == "ok"
    assert run.memory.artifacts[1]["body"] == report
    assert run.memory.artifacts[2]["body"] == raw_eval
    assert run.memory.artifacts[2]["title"] == "Order evidence"
