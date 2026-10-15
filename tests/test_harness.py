"""Offline contracts for the current shared-state runtime (historical runtime tests live in snapshots)."""
import json

import pytest

from fakes import ScriptedLLM, fake_web
from minpilot.config import ConditionConfig, RunConfig, load_pool
from minpilot.harness import Run
from minpilot.runtime.trace import Limits
from minpilot.tools.config import ToolConfig


def action(kind="execute", wid="worker_1", content="", **extra):
    """A scripted orchestrator reply: one tool call with complete arguments (extra keys override or add)."""
    args = {"probe": {"instruction": "Count unique orders in 2025.", "artifact_ids": [], "rationale": "Compare plans."},
            "execute": {"worker_id": wid, "instruction": "Count unique orders in 2025.", "artifact_ids": [],
                        "rationale": "The count is still open."},
            "finish": {"answer": "2", "rationale": "Use reported order IDs."}}[kind]
    return {"content": content, "tool_calls": [(kind, {**args, **extra})]}


def make_run(tmp_path, task, script, condition="direct_execution", **extra):
    llm = script if isinstance(script, ScriptedLLM) else ScriptedLLM(script)
    cfg = RunConfig(load_pool("multi"), ConditionConfig(condition), **extra)
    web = fake_web(tmp_path, task.question)
    run = Run(cfg, task, tmp_path / "run", transport=llm, web=web,
              tool_cfg=ToolConfig(cache_path=web.cfg.cache_path))
    return run, llm


def probe_script(**extra):
    """Probe by both workers, then worker_2 (gen_haiku) continues its conversation and executes."""
    return {"orchestrator": [action("probe"), *extra.pop("orchestrator_select", [action(
                "execute", wid="worker_2", instruction="Count distinct order IDs; the year 2025 is fixed by the task.")]),
                action("finish")],
            "worker": ["understanding: count\nplan: probe marker one", "understanding: count\nplan: probe marker two",
                       "Execution: 2"], **extra}


def direct_script(**extra):
    return {"orchestrator": [action(), action("finish")], "worker": ["Count: 2 (sheet.csv)"], **extra}


def tool_results(body):
    return [m["content"] for m in body["messages"] if m["role"] == "tool"]


def test_orchestrator_conversation_keeps_reports_and_passes_selected_report(tmp_path, task):
    script = direct_script(orchestrator=[action(), action(wid="worker_2", artifact_ids=["a00001"]), action("finish")],
                           worker=["FIRST FULL REPORT", "SECOND FULL REPORT"])
    run, llm = make_run(tmp_path, task, script)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert [d["worker"] for d in info["delegations"]] == ["gen_luna", "gen_haiku"]
    assert [d["worker_alias"] for d in info["delegations"]] == ["worker_1", "worker_2"]
    assert [d["rationale"] for d in info["delegations"]] == ["The count is still open."] * 2
    assert [a["rationale"] for a in info["actions"]] == ["The count is still open."] * 2
    second = llm.by_kind["worker"][1]["messages"]
    assert "Report a00001 from worker_1 (execution request, status ok):\nFIRST FULL REPORT" in second[-1]["content"]
    first, middle, last = llm.by_kind["orchestrator"]
    assert len(first["messages"]) == 2 and not tool_results(first)
    assert "FIRST FULL REPORT" in tool_results(middle)[0] and "Remaining executions: 11." in tool_results(middle)[0]
    assert [r.split("\n")[0] for r in tool_results(last)] == [
        "Report a00001 from worker_1 (execution request, status ok):",
        "Report a00003 from worker_2 (execution request, status ok):"]
    assert last["messages"][:len(middle["messages"])] == middle["messages"][:len(middle["messages"])]
    assert set(llm.by_kind) == {"orchestrator", "worker"} and "state" not in info
    for body in llm.by_kind["orchestrator"]:
        text = json.dumps(body["messages"])
        assert "gen_luna" not in text and "gen_haiku" not in text and "haiku-high" not in text
    opening = first["messages"][1]["content"]
    assert "- worker_1: tools" in opening and "price" not in opening.lower() and "Answer format" in opening
    conversation = [json.loads(line) for line in (run.run_dir / "orchestrator.jsonl").read_text().splitlines()]
    assert conversation == last["messages"] + [{k: v for k, v in conversation[-1].items()}]


def test_restore_continues_the_orchestrator_conversation(tmp_path, task):
    run, original = make_run(tmp_path, task, direct_script())
    assert run.run_fresh()["status"] == "ok"
    ck = run.run_dir / "checkpoints/a0"
    llm = ScriptedLLM({"worker": ["Count: 2 (sheet.csv)"], "orchestrator": [action("finish")]})
    restored = Run.restore(ck, tmp_path / "restored", task=task, web=fake_web(tmp_path, task.question),
                           transport=llm, tool_cfg=run.tool_cfg)
    assert restored.run_restored()["status"] == "ok"
    assert llm.by_kind["orchestrator"][0]["messages"] == original.by_kind["orchestrator"][1]["messages"]
    assert llm.by_kind["worker"][0]["messages"] == original.by_kind["worker"][0]["messages"]
    assert restored.trace.run_scope.llm_calls == run.trace.run_scope.llm_calls
    assert json.loads((restored.run_dir / "restore_check.json").read_text())["match"]


def test_old_checkpoint_and_tamper_rejected(tmp_path, task):
    ck = tmp_path / "old"
    ck.mkdir()
    (ck / "state.json").write_text('{"format": 5}')
    with pytest.raises(ValueError, match="historical"):
        Run.restore(ck, tmp_path / "restore", task=task)
    run, _ = make_run(tmp_path, task, direct_script())
    run.run_fresh()
    ck = run.run_dir / "checkpoints/a0"
    (ck / "work/gen_luna/attachments/sheet.csv").write_text("tampered")
    with pytest.raises(ValueError, match="fingerprint"):
        Run.restore(ck, tmp_path / "tampered", task=task, web=fake_web(tmp_path), tool_cfg=run.tool_cfg, transport=ScriptedLLM({}))


def test_run_budget_is_terminal(tmp_path, task):
    run, _ = make_run(tmp_path, task, direct_script(), budget=Limits(max_llm_calls=1))
    assert run.run_fresh()["status"] == "budget_exceeded"


def test_restore_rejects_pending_probe_under_direct(tmp_path, task):
    run, _ = make_run(tmp_path, task, probe_script(), "adaptive_probe")
    assert run.run_fresh()["status"] == "ok"
    with pytest.raises(ValueError, match="'probe' is not available"):
        Run.restore(run.run_dir / "checkpoints/a0", tmp_path / "restored", task=task,
                    condition=ConditionConfig("direct_execution"), web=fake_web(tmp_path),
                    tool_cfg=run.tool_cfg, transport=ScriptedLLM({}))


def test_checkpoint_after_two_delegations_keeps_records_and_selected_context(tmp_path, task):
    script = direct_script(orchestrator=[action(), action(), action(artifact_ids=["a00001"]), action("finish")],
                           worker=["First: 2", "Second: 2", "Third: 2"])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    checkpoint = run.run_dir / "checkpoints/a2"
    saved = json.loads((checkpoint / "state.json").read_text())
    assert [a["stage"] for a in saved["records"]["artifacts"]] == ["instruction", "execution"] * 2
    assert saved["pending_actions"][0]["context"].startswith("Report a00001 from worker_1")
    assert saved["orchestrator"][-1]["tool_calls"][0]["function"]["name"] == "execute"
    restored = Run.restore(checkpoint, tmp_path / "restored", task=task, web=fake_web(tmp_path),
        tool_cfg=run.tool_cfg, transport=ScriptedLLM({"worker": ["Third: 2"], "orchestrator": [action("finish")]}))
    assert restored.run_restored()["status"] == "ok"
    assert len(restored.records.artifacts) == 6


def test_restore_rejects_tool_version_and_prompt_tamper(tmp_path, task):
    from dataclasses import replace
    run, _ = make_run(tmp_path, task, direct_script())
    run.run_fresh()
    ck = run.run_dir / "checkpoints/a0"
    for change in [{"tools_version": "v5"}, {"page_chars": 1}, {"reader_chain": ("direct",)}]:
        with pytest.raises(ValueError, match="tool settings"):
            Run.restore(ck, tmp_path / str(len(change)) / str(change), task=task, web=fake_web(tmp_path),
                        tool_cfg=replace(run.tool_cfg, **change), transport=ScriptedLLM({}))
    path = ck / "state.json"
    state = json.loads(path.read_text())
    state["probe_prompts_version"] = "old"
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="prompt version"):
        Run.restore(ck, tmp_path / "wrongprompt", task=task, web=fake_web(tmp_path), tool_cfg=run.tool_cfg,
                    transport=ScriptedLLM({}))


def test_trace_connects_records_choices_tools_and_final_answer(tmp_path, task):
    import importlib.util
    from minpilot.tools.config import REPO_ROOT
    run, _ = make_run(tmp_path, task, direct_script(worker=[
        {"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]}, "Count: 2"]))
    assert run.run_fresh()["status"] == "ok"
    events = [json.loads(line) for line in (run.run_dir / "events.jsonl").read_text().splitlines()]
    assert next(e for e in events if e["event"] == "report")["artifact_id"] == "a00001"
    assert next(e for e in events if e["event"] == "action" and e["action"] == "finish")["rationale"]
    assert not any(e["event"] == "state_replace" for e in events)
    spec = importlib.util.spec_from_file_location("render_trace", REPO_ROOT / "scripts/render_trace.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.render(run.run_dir, 100000)
    for expected in ["a00000", "worker_1", "order_id,date,amount", "FINAL ANSWER"]:
        assert expected in text
