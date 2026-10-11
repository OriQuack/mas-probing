"""Request texts by kind, B's reference to the real probe, the run reference date and delegation records
(decisions F18-F20, R20)."""

import json

from fakes import ScriptedLLM, delegate, finish
from minpilot import prompts
from minpilot.harness import Run
from minpilot.tools.config import ToolConfig
from test_harness import fake_web, make_run

DRAFT = "Count the orders in attachments/sheet.csv for 2025."
NO_QUESTION = "Do not end by asking the orchestrator for clarification or permission."


def test_execution_and_check_requests_state_the_limit_probes_do_not(tmp_path, task):
    issue = {"id": "i1", "kind": "assumption", "summary": "s", "evidence": "e", "decision": "needs_verification",
             "resolution": ""}
    llm = ScriptedLLM({"orchestrator": [delegate("worker", DRAFT), finish("2")],
                       "analyze": [{"issues": [issue], "followups": [],
                                    "verifications": [{"issue_id": "i1", "worker_id": "worker",
                                                       "instruction": "check ids"}]}],
                       "rewrite": [{"instruction": "new", "changes": [], "unchanged": False}],
                       "worker": ["probe answers", "checked", "2"]})
    run = make_run(tmp_path, task, llm, pool="single", refiner="variants/pool_probe")
    run.run_fresh()
    probe, check, execution = (b["messages"][1]["content"] for b in llm.by_kind["worker"])
    assert NO_QUESTION not in probe and "tool calls for this request" not in probe
    assert NO_QUESTION in check and "at most 10 tool calls for this request" in check
    assert NO_QUESTION in execution and "at most 20 tool calls for this request" in execution
    assert NO_QUESTION not in llm.by_kind["worker"][0]["messages"][0]["content"]  # not in the system prompt
    worker = run.workers["gen_luna"]
    systems = [body["messages"][0]["content"] for body in llm.by_kind["worker"]]
    assert systems == [worker.system_message("probe")["content"],
                       worker.system_message()["content"], worker.system_message()["content"]]
    assert "\nResult:" not in systems[0] and "\nResult:" in systems[2]


def test_self_review_sees_the_real_system_prompt_and_probe_message(tmp_path, task):
    llm = ScriptedLLM({"orchestrator": [delegate("worker", DRAFT), finish("2")], "simulate": ["predicted"],
                       "analyze": [{"issues": [], "followups": [], "verifications": []}], "worker": ["2"]})
    run = make_run(tmp_path, task, llm, pool="single", refiner="variants/pool_self_review")
    run.run_fresh()
    sim = llm.by_kind["simulate"][0]["messages"][-1]["content"]
    worker = run.workers["gen_luna"]
    assert worker.system_message("probe")["content"] in sim
    real_probe = prompts.worker_request(run.original_task, prompts.probe_instruction(DRAFT, False, 0), kind="probe")
    assert real_probe in sim and "model" not in sim.lower().replace("reader model", "")


def test_reference_date_is_kept_by_checkpoints(tmp_path, task):
    script = {"orchestrator": [delegate("worker", DRAFT), finish("2")], "worker": ["2"]}
    run1 = make_run(tmp_path, task, ScriptedLLM(script), pool="single", name="rec")
    run1.run_fresh()
    assert f"Run date: {run1.reference_date} (the day this run takes place)" in run1.original_task
    assert "not take the run date as the task's time reference" in run1.original_task
    ck = run1.run_dir / "checkpoints" / "d0"
    state = json.loads((ck / "state.json").read_text())
    assert state["reference_date"] == run1.reference_date
    state["reference_date"] = "2001-02-03"  # e.g. recorded on another day: the restore must use it, not today
    (ck / "state.json").write_text(json.dumps(state))
    llm2 = ScriptedLLM({"orchestrator": [finish("2")], "worker": ["2"]})
    try:
        Run.restore(ck, tmp_path / "r", task=task, transport=llm2, web=fake_web(tmp_path),
                    tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))
    except ValueError as e:  # the fingerprint covers the task text, so a changed date is caught
        assert "original_task" in str(e)
    else:
        raise AssertionError("a changed reference date must not restore silently")
    state["reference_date"] = run1.reference_date
    (ck / "state.json").write_text(json.dumps(state))
    run2 = Run.restore(ck, tmp_path / "r2", task=task, transport=llm2, web=fake_web(tmp_path),
                       tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))
    assert run2.original_task == run1.original_task and run2.info["reference_date"] == run1.reference_date


def test_delegation_records_lengths_and_repeats(tmp_path, task):
    llm = ScriptedLLM({"orchestrator": [delegate("worker", DRAFT), delegate("worker", DRAFT + "  "),
                                        finish("2")], "worker": ["a", "b"]})
    run = make_run(tmp_path, task, llm, pool="single")
    info = run.run_fresh()
    d0, d1 = info["delegations"]
    assert d0["draft_chars"] == len(DRAFT) and d0["final_chars"] == len(DRAFT) and d0["repeat_of"] is None
    assert d1["repeat_of"] == 0 and info["n_repeated_delegations"] == 1


def test_probe_tool_limit_requests_review_answers_not_execution_report(tmp_path, task):
    llm = ScriptedLLM({"orchestrator": [finish("2")], "worker": [
        {"tool_calls": [("web_search", {"query": "orders"})]},
        "understanding: Count orders\nassumptions: none\nrisks: none\nplan: inspect IDs",
        "2",
    ]})
    run = make_run(tmp_path, task, llm, pool="single")
    assert run.run_fresh()["status"] == "ok"
    call = run.workers["gen_luna"].run(
        run.original_task, prompts.probe_instruction(DRAFT, True, 1), run.toolbox,
        kind="probe", max_tool_calls=1)
    final = llm.by_kind["worker"][-1]
    assert call.status == "tool_limit" and call.n_tool_calls == 1
    assert final["tool_choice"] == "none"
    assert final["messages"][-1]["content"] == prompts.PROBE_TOOL_LIMIT_REACHED
    assert prompts.parse_probe(call.report)["assumptions"] == []
    worker = run.workers["gen_luna"]
    execution = worker.run(run.original_task, DRAFT, run.toolbox, allow_tools=False, history=call.messages)
    assert execution.messages[0] == worker.system_message()
    assert call.messages[0] == worker.system_message("probe")
    assert any(m.get("role") == "assistant" and m.get("content") == call.report
               for m in execution.messages)
