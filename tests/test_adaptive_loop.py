"""Unified action loop contracts, entirely offline."""
import json
from dataclasses import replace
import pytest
from fakes import ScriptedLLM, fake_web
from minpilot.config import ConditionConfig
from minpilot.harness import Run
from minpilot.runtime.trace import Limits
from test_harness import action, make_run, probe_script, tool_results


def test_probe_can_finish_without_execution(tmp_path, task):
    script = {"orchestrator": [action("probe"), action("finish")],
              "worker": ["plan: observed: answer 2 (sheet.csv)", "plan: Independent evidence"]}
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    info = run.run_fresh()
    assert info["status"] == "ok" and info["n_delegations"] == 0 and info["n_probes"] == 1
    probe_result = tool_results(llm.by_kind["orchestrator"][1])[0]
    assert probe_result.startswith("Report a00001 from worker_1 (probe request, status ok):\nplan: observed: answer 2")
    assert "Report a00002 from worker_2 (probe request, status ok):" in probe_result
    assert "Remaining executions: 12." in probe_result
    assert run.actions[0]["report_ids"] == ["a00001", "a00002"]


def test_restore_after_probe_keeps_both_conversations(tmp_path, task):
    run, llm = make_run(tmp_path, task, probe_script(), "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    events = [json.loads(line) for line in (run.run_dir / "events.jsonl").read_text().splitlines()]
    assert next(e for e in events if e["event"] == "probe_round")["report_ids"] == ["a00001", "a00002"]
    checkpoint = run.run_dir / "checkpoints/a1"
    saved = json.loads((checkpoint / "state.json").read_text())
    assert saved["sessions"]["gen_haiku"]["report_ids"] == ["a00002"]
    restored_llm = ScriptedLLM({"worker": ["Execution: 2"], "orchestrator": [action("finish")]})
    restored = Run.restore(checkpoint, tmp_path / "restored", task=task, web=fake_web(tmp_path),
                           tool_cfg=run.tool_cfg, transport=restored_llm)
    assert restored.run_restored()["status"] == "ok"
    sent = restored_llm.by_kind["worker"][0]["messages"]
    assert sent == llm.by_kind["worker"][-1]["messages"]
    assert "probe marker two" in json.dumps(sent) and "probe marker one" not in json.dumps(sent)
    assert restored.delegations[0]["conversation_report_ids"] == ["a00002"]
    assert restored_llm.by_kind["orchestrator"][0]["messages"] == llm.by_kind["orchestrator"][-1]["messages"]


def test_mixed_actions_share_loop_and_probe_does_not_consume_execution_cap(tmp_path, task):
    choices = [action(), action("probe", artifact_ids=["a00001"]), action("probe"), action(wid="worker_2"),
               action("finish")]
    script = {"orchestrator": choices, "worker": ["Report: 2"] * 6}
    run, llm = make_run(tmp_path, task, script, "adaptive_probe", max_delegations=2)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert [a["action"] for a in run.actions] == ["execute", "probe", "probe", "execute"]
    assert info["n_delegations"] == 2 and info["n_probes"] == 2
    remaining = [next(line for line in tool_results(b)[-1].splitlines() if line.startswith("Remaining executions"))
                 for b in llm.by_kind["orchestrator"][1:]]
    assert remaining == ["Remaining executions: 1."] * 3 + ["Remaining executions: 0."]
    assert run.actions[1]["context"].startswith("Report a00001 from worker_1")
    assert sorted(p.name for p in (run.run_dir / "checkpoints").iterdir()) == ["a0", "a1", "a2", "a3"]
    ck = run.run_dir / "checkpoints/a2"
    saved = json.loads((ck / "state.json").read_text())
    assert saved["delegation"] == 1 and saved["action_index"] == 2
    restored_llm = ScriptedLLM({"worker": ["Probe: 2"] * 2, "orchestrator": [action("finish")]})
    restored = Run.restore(ck, tmp_path / "restored", task=task, web=fake_web(tmp_path),
                           transport=restored_llm, tool_cfg=run.tool_cfg)
    assert restored.trace.run_scope.llm_calls == saved["trace"]["counters"]["llm_calls"]
    assert restored.run_restored()["status"] == "ok"


def test_old_condition_rejected():
    with pytest.raises(ValueError, match='unsupported'):
        ConditionConfig('multi_worker_probe')
    from minpilot.config import load_condition
    with pytest.raises(ValueError, match='retired'):
        load_condition('multi_worker_probe')


def test_probe_round_budget_stops_the_round_but_not_the_run(tmp_path, task):
    script = {"orchestrator": [action("probe"), action(), action("finish")], "worker": ["plan: read", "Execution: 2"]}
    run, llm = make_run(tmp_path, task, script, "adaptive_probe")
    run.cfg = replace(run.cfg, condition=ConditionConfig('adaptive_probe', budget=Limits(max_llm_calls=1)))
    info = run.run_fresh()
    assert info["status"] == "ok", info
    result = tool_results(llm.by_kind["orchestrator"][1])[0]
    assert "Report a00001 from worker_1" in result and "The probe stopped at its budget" in result
    assert run.actions[0]["report_ids"] == ["a00001", "a00002"]
    assert run.records.artifacts[2]["status"] == "budget_exceeded"


def test_probe_round_budget_does_not_limit_execution(tmp_path, task):
    script = {"orchestrator": [action(), action("finish")], "worker": ["Count: 2"]}
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    run.cfg = replace(run.cfg, condition=ConditionConfig('adaptive_probe', budget=Limits(max_llm_calls=0)))
    assert run.run_fresh()['status'] == 'ok'
    assert run.delegations[0]['instruction'] == run.actions[0]['instruction']
