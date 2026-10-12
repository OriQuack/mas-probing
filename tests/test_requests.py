import json
from test_harness import direct_script, make_run
from test_refiners import probe_script


def test_new_reports_full_and_tool_results_not_auto_attached(tmp_path, task):
    script = direct_script(worker=[{"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]},
                                   "Title: Count\nUNIQUE FULL REPORT END"])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    ev = json.loads(llm.by_kind["evaluator_execution"][0]["messages"][1]["content"])
    assert "UNIQUE FULL REPORT END" in ev["reports"][0]["body"]
    assert "order_id,date,amount" not in json.dumps(ev)


def test_probes_are_isolated_with_three_tool_limit(tmp_path, task):
    run, llm = make_run(tmp_path, task, probe_script(), "multi_worker_probe")
    assert run.run_fresh()["status"] == "ok"
    for body in llm.by_kind["worker"][:2]:
        assert len(body["messages"]) == 2
        assert "up to 3 tool calls" in body["messages"][1]["content"]
    assert (run.run_dir / "scratch/d0/gen_luna").is_dir()
    assert (run.run_dir / "scratch/d0/gen_haiku").is_dir()
