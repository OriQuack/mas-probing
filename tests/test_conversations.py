"""Each worker keeps one conversation and one workspace for the run (offline)."""
import json

import pytest
from fakes import ScriptedLLM, fake_web
from minpilot.harness import Run
from minpilot.llm.client import HTTPError
from test_harness import action, direct_script, make_run, probe_script


def user_texts(body):
    return [m["content"] for m in body["messages"] if m["role"] == "user" and isinstance(m["content"], str)]


def test_probe_then_execution_continue_the_same_conversation(tmp_path, task):
    from fakes import kind_of
    run, llm = make_run(tmp_path, task, probe_script(), "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    assert [kind_of(b) for b in llm.bodies] == ["orchestrator", "worker", "worker", "orchestrator", "worker",
                                                "orchestrator"]
    execution = llm.by_kind["worker"][-1]
    assert execution["messages"][0]["content"].startswith("You are a generalist worker")
    assert "You carry out work delegated" in execution["messages"][0]["content"]
    texts = user_texts(execution)
    assert sum(t.startswith("Original task:") for t in texts) == 1
    assert texts[-1].startswith("Your instruction:") and "year 2025 is fixed" in texts[-1]
    assert "probe marker two" in json.dumps(execution) and "probe marker one" not in json.dumps(execution)
    assert run.delegations[0]["conversation_report_ids"] == ["a00002"]
    # The saved execution report holds only its own turn, so tool records are not duplicated.
    assert run.records.read("a00004")["body"] == "Execution: 2"


def test_other_workers_findings_arrive_only_as_context(tmp_path, task):
    script = probe_script(orchestrator_select=[action("execute", wid="worker_2", artifact_ids=["a00001"])])
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    last = llm.by_kind["worker"][-1]
    assert "probe marker two" in json.dumps(last)
    assert "Report a00001 from worker_1 (probe request, status ok):" in user_texts(last)[-1]
    assert "probe marker one" in user_texts(last)[-1]


def test_later_execution_requests_continue_and_skip_the_original_task(tmp_path, task):
    script = direct_script(orchestrator=[action(), action(), action("finish")], worker=["FIRST REPORT", "Second: 2"])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    second = llm.by_kind["worker"][1]
    assert "FIRST REPORT" in json.dumps(second["messages"])
    assert sum(t.startswith("Original task:") for t in user_texts(second)) == 1
    assert run.delegations[1]["conversation_report_ids"] == ["a00001"]
    assert len(run.workers["gen_luna"].messages) == 5 and not run.workers["gen_haiku"].messages


def test_workspace_belongs_to_one_worker(tmp_path, task):
    def worker(body):
        text = json.dumps(body["messages"])
        if "Before carrying out this assignment" in text and len(body["messages"]) == 2:
            if not (run.work_dir / "gen_luna/made.txt").exists():
                (run.work_dir / "gen_luna/made.txt").write_text("PROBE FILE")
            return "plan: read"
        if body["messages"][-1]["role"] == "tool":
            return "Execution: read"
        return {"tool_calls": [("read_file", {"path": "made.txt"})]}

    script = probe_script(worker=worker, orchestrator_select=[action("execute", wid="worker_1"),
                                                              action("execute", wid="worker_2")])
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    luna, haiku = run.delegations
    assert "PROBE FILE" in run.records.read(run.records.read(luna["report_id"])["tool_ids"][0])["body"]
    assert "PROBE FILE" not in run.records.read(run.records.read(haiku["report_id"])["tool_ids"][0])["body"]


def test_failed_request_leaves_conversation_unchanged_and_run_continues(tmp_path, task):
    script = direct_script(orchestrator=[action(), action(), action("finish")],
                           worker=[HTTPError(400, "maximum context length exceeded"), "Retry: 2"])
    run, llm = make_run(tmp_path, task, script)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert [d["report_status"] for d in info["delegations"]] == ["failed", "ok"]
    assert info["delegations"][1]["conversation_report_ids"] == []
    retry = llm.by_kind["worker"][1]
    assert len(retry["messages"]) == 2 and user_texts(retry)[0].startswith("Original task:")
    failed = [m["content"] for m in llm.by_kind["orchestrator"][1]["messages"] if m["role"] == "tool"][0]
    assert "status failed" in failed and "maximum context length" in failed


def test_restore_rejects_checkpoint_without_matching_sessions(tmp_path, task):
    run, _ = make_run(tmp_path, task, direct_script())
    assert run.run_fresh()["status"] == "ok"
    ck = run.run_dir / "checkpoints/a0"
    state = json.loads((ck / "state.json").read_text())
    del state["sessions"]["gen_haiku"]
    (ck / "state.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="workers mismatch"):
        Run.restore(ck, tmp_path / "restored", task=task, web=fake_web(tmp_path), tool_cfg=run.tool_cfg,
                    transport=ScriptedLLM({}))


@pytest.mark.parametrize('wid,real', [('worker_1', 'gen_luna'), ('worker_2', 'gen_haiku')])
def test_consecutive_probes_join_each_conversation(tmp_path, task, wid, real):
    script = {'orchestrator': [action('probe'), action('probe', instruction='Check another result.'),
                               action(instruction='Carry out the second assignment.', wid=wid), action('finish')],
              'worker': [f'plan: step {i}' for i in range(5)]}
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    info = run.run_fresh()
    assert info['status'] == 'ok', info
    second_probes = llm.by_kind['worker'][2:4]
    assert all(sum(t.startswith('Original task:') for t in user_texts(b)) == 1 for b in second_probes)
    assert all('Check another result.' in user_texts(b)[-1] for b in second_probes)
    execution = llm.by_kind['worker'][4]
    assert len(user_texts(execution)) == 3
    assert run.delegations[0]['worker'] == real
    assert run.delegations[0]['conversation_report_ids'] == (['a00001', 'a00004'] if real == 'gen_luna'
                                                             else ['a00002', 'a00005'])


def test_haiku_reservation_uses_long_context_price_above_threshold():
    from minpilot.llm.specs import get_spec, reserve_usd
    spec = get_spec("haiku-high")
    short = {"messages": [{"role": "user", "content": "x" * 1000}]}
    medium = {"messages": [{"role": "user", "content": "x" * 120_000}]}
    long = {"messages": [{"role": "user", "content": "x" * 200_000}]}
    assert reserve_usd(spec, short) < 0.02
    assert reserve_usd(spec, medium) < 0.03
    assert reserve_usd(spec, long) >= 200_000 * 5e-7 + spec.max_tokens * 2.5e-6
    assert spec.identity() == {**spec.identity()} and "price_prompt_long" not in spec.identity()
