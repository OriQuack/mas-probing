import json
from test_harness import direct_script, make_run, probe_script


def test_reports_reach_the_orchestrator_in_full_without_tool_results(tmp_path, task):
    script = direct_script(worker=[{"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]},
                                   "Count\nUNIQUE FULL REPORT END"])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    result = [m["content"] for m in llm.by_kind["orchestrator"][1]["messages"] if m["role"] == "tool"][0]
    assert "Count\nUNIQUE FULL REPORT END" in result
    assert "order_id,date,amount" not in json.dumps(llm.by_kind["orchestrator"][1])


def test_first_probes_start_each_conversation_with_three_tool_limit(tmp_path, task):
    run, llm = make_run(tmp_path, task, probe_script(), "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    for body in llm.by_kind["worker"][:2]:
        assert len(body["messages"]) == 2
        assert body["messages"][1]["content"].startswith("Original task:")
        assert "up to 3 tool calls" in body["messages"][1]["content"]
        assert "Before carrying out this assignment" in body["messages"][1]["content"]
        assert "Title:" not in body["messages"][1]["content"]
    assert (run.work_dir / "gen_luna/attachments/sheet.csv").is_file()
    assert (run.work_dir / "gen_haiku/attachments/sheet.csv").is_file()
    assert not (run.run_dir / "scratch").exists()
