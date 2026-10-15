"""The orchestrator's tool calls: validation feedback, one action per message, forced finish (offline)."""
import pytest
from test_harness import action, direct_script, make_run, probe_script, tool_results


def test_invalid_call_gets_error_feedback_once(tmp_path, task):
    script = direct_script(orchestrator=[action(artifact_ids=["missing"]), action(), action("finish")])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    assert tool_results(llm.by_kind["orchestrator"][1])[-1].startswith("Error: unknown report ID 'missing'")
    assert len(run.delegations) == 1


@pytest.mark.parametrize("bad", [action(wid="gen_luna"), action(instruction=" "), action(extra="x"), action(rationale=""),
                                 action("probe", rationale=None),
                                 action("finish", answer=""), {"tool_calls": [("read_memory", {"refs": []})]}])
def test_two_invalid_calls_in_a_row_stop_the_run(tmp_path, task, bad):
    run, llm = make_run(tmp_path, task, direct_script(orchestrator=[bad, bad]))
    info = run.run_fresh()
    assert info["status"] == "error" and "invalid tool call" in info["error"]
    assert not llm.by_kind["worker"]


def test_reply_without_tool_call_gets_one_reminder(tmp_path, task):
    run, llm = make_run(tmp_path, task, direct_script(orchestrator=["thinking aloud", action(), action("finish")]))
    assert run.run_fresh()["status"] == "ok"
    assert llm.by_kind["orchestrator"][1]["messages"][-1]["content"].startswith("Call one of the available tools")
    run, _ = make_run(tmp_path / "again", task, direct_script(orchestrator=["one", "two"]))
    assert run.run_fresh()["status"] == "error"


def test_several_executes_in_one_message_run_in_order_and_finish_must_be_alone(tmp_path, task):
    both = {"tool_calls": [("execute", action(wid="worker_1")["tool_calls"][0][1]),
                           ("execute", action(wid="worker_2")["tool_calls"][0][1]),
                           ("finish", {"answer": "9", "rationale": "r"})]}
    run, llm = make_run(tmp_path, task, direct_script(orchestrator=[both, action("finish")], worker=["One: 2", "Two: 2"]))
    info = run.run_fresh()
    assert info["status"] == "ok" and info["final_answer"] == "2"
    assert [d["worker"] for d in run.delegations] == ["gen_luna", "gen_haiku"]
    # Each worker gets only its own request: the second does not see the first's report.
    assert "One: 2" not in str(llm.by_kind["worker"][1]["messages"])
    results = tool_results(llm.by_kind["orchestrator"][1])
    assert results[0].startswith("Error: call `finish` alone in its own message")
    assert results[1].startswith("Report a00001 from worker_1") and results[2].startswith("Report a00003 from worker_2")
    assert sorted(p.name for p in (run.run_dir / "checkpoints").iterdir()) == ["a0", "a1"]


def test_restore_inside_a_message_runs_its_remaining_calls(tmp_path, task):
    from fakes import ScriptedLLM, fake_web
    from minpilot.harness import Run
    both = {"tool_calls": [("execute", action(wid="worker_1")["tool_calls"][0][1]),
                           ("execute", action(wid="worker_2")["tool_calls"][0][1])]}
    run, llm = make_run(tmp_path, task, direct_script(orchestrator=[both, action("finish")], worker=["One: 2", "Two: 2"]))
    assert run.run_fresh()["status"] == "ok"
    restored_llm = ScriptedLLM({"worker": ["Two: 2"], "orchestrator": [action("finish")]})
    restored = Run.restore(run.run_dir / "checkpoints/a1", tmp_path / "restored", task=task, web=fake_web(tmp_path),
                           tool_cfg=run.tool_cfg, transport=restored_llm)
    assert restored.run_restored()["status"] == "ok"
    assert [d["worker"] for d in restored.delegations] == ["gen_luna", "gen_haiku"]
    assert restored_llm.by_kind["orchestrator"][0]["messages"] == llm.by_kind["orchestrator"][1]["messages"]


def test_executions_beyond_the_limit_in_one_message_are_not_run(tmp_path, task):
    both = {"tool_calls": [("execute", action(wid="worker_1")["tool_calls"][0][1]),
                           ("execute", action(wid="worker_2")["tool_calls"][0][1])]}
    run, llm = make_run(tmp_path, task, direct_script(orchestrator=[both, action("finish")], worker=["One: 2"]),
                        max_delegations=1)
    assert run.run_fresh()["status"] == "ok" and len(run.delegations) == 1
    assert tool_results(llm.by_kind["orchestrator"][1])[0].startswith("Error: no executions remain for this call")


def test_execution_cap_offers_only_finish(tmp_path, task):
    run, llm = make_run(tmp_path, task, direct_script(orchestrator=[action(), action("finish")]), max_delegations=1)
    assert run.run_fresh()["status"] == "ok"
    first, last = llm.by_kind["orchestrator"]
    assert [t["function"]["name"] for t in first["tools"]] == ["execute", "finish"] and "tool_choice" not in first
    assert [t["function"]["name"] for t in last["tools"]] == ["finish"] and last["tool_choice"] == "required"
    assert "No executions remain" in tool_results(last)[-1]


def test_direct_does_not_offer_probe_and_rejects_it(tmp_path, task):
    run, llm = make_run(tmp_path, task, direct_script(orchestrator=[action("probe"), action(), action("finish")]))
    assert run.run_fresh()["status"] == "ok"
    assert "probe" not in [t["function"]["name"] for t in llm.by_kind["orchestrator"][0]["tools"]]
    assert "'probe' is not available" in tool_results(llm.by_kind["orchestrator"][1])[-1]


def test_finish_records_rationale_and_text(tmp_path, task):
    run, _ = make_run(tmp_path, task, {"orchestrator": [action("finish", content="Reading A fits best.")]})
    info = run.run_fresh()
    assert info["status"] == "ok" and info["final_rationale"] == "Use reported order IDs."
    assert info["final_note"] == "Reading A fits best."


def test_adaptive_offers_all_three_tools(tmp_path, task):
    run, llm = make_run(tmp_path, task, probe_script(), "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    assert [t["function"]["name"] for t in llm.by_kind["orchestrator"][0]["tools"]] == ["probe", "execute", "finish"]


def test_second_probe_in_one_message_is_not_run(tmp_path, task):
    twice = {"tool_calls": [("probe", action("probe")["tool_calls"][0][1])] * 2}
    run, llm = make_run(tmp_path, task, probe_script(orchestrator=[twice, action("finish")]), "adaptive_probe")
    info = run.run_fresh()
    assert info["status"] == "ok" and info["n_probes"] == 1
    assert len(llm.by_kind["worker"]) == 2  # one probe request per worker
    results = tool_results(llm.by_kind["orchestrator"][1])
    assert results[0].startswith("Error: a single `probe` call already sends the assignment to every worker")

