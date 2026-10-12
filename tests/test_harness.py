"""Offline contracts for the current shared-state runtime (historical runtime tests live in snapshots)."""
import json

import pytest

from fakes import ScriptedLLM, fake_web
from minpilot.config import ConditionConfig, RunConfig, load_pool
from minpilot.harness import Run
from minpilot.runtime.trace import Limits
from minpilot.tools.config import ToolConfig


def action(kind="delegate", wid="gen_luna", **extra):
    return {"action": kind, "worker_id": wid, "instruction": "Count unique orders in 2025.",
            "answer": "2", "rationale": "Use reported order IDs.", "artifact_ids": [], "state_rows": [],
            "accept_state": True, "state_reason": "Evidence matches original scope.",
            "refine": False, "changes": "", **extra}


def evaluation(state=None, **extra):
    return {"action": "evaluate", "title": "Order evidence", "state": state or [],
            "rationale": "Evidence matches scope.", "changes": "", "requires_decision": False, **extra}


def row(ref="a00000", **extra):
    return {"type": "result", "content": "Two unique order IDs in the 2025 sheet.",
            "status": "supported", "refs": [ref], **extra}


def make_run(tmp_path, task, script, condition="direct_execution", **extra):
    llm = script if isinstance(script, ScriptedLLM) else ScriptedLLM(script)
    cfg = RunConfig(load_pool("multi"), ConditionConfig(condition), **extra)
    web = fake_web(tmp_path, task.question)
    run = Run(cfg, task, tmp_path / "run", transport=llm, web=web,
              tool_cfg=ToolConfig(cache_path=web.cfg.cache_path))
    return run, llm


def direct_script(**extra):
    return {"orchestrator": [action(), action("finish")], "worker": ["Title: Count\nResult: 2\nEvidence: sheet.csv"],
            "evaluator_execution": [evaluation([row()])], **extra}


def test_two_delegations_use_selected_context_and_keep_state(tmp_path, task):
    script = direct_script(orchestrator=[action(), action(wid="gen_haiku", artifact_ids=["a00000"], state_rows=[]),
                                         action("finish")],
                           worker=["Title: Count\nFIRST FULL REPORT", "Title: Check\nSECOND FULL REPORT"],
                           evaluator_execution=[evaluation([row()]), evaluation([row(), row("a00002")])])
    run, llm = make_run(tmp_path, task, script)
    info = run.run_fresh()
    assert info["status"] == "ok", info
    assert [d["worker"] for d in info["delegations"]] == ["gen_luna", "gen_haiku"]
    assert len(info["state"]) == 2
    second = llm.by_kind["worker"][1]["messages"]
    assert "FIRST FULL REPORT" in json.dumps(second)
    # Fresh controller inputs have catalog/state; old report bodies do not accumulate.
    for body in llm.by_kind["orchestrator"]:
        assert "FIRST FULL REPORT" not in json.dumps(body)
    ev = llm.by_kind["evaluator_execution"]
    assert "FIRST FULL REPORT" in json.dumps(ev[0])
    assert "SECOND FULL REPORT" in json.dumps(ev[1])
    assert "FIRST FULL REPORT" not in json.dumps(json.loads(ev[1]["messages"][1]["content"])["reports"])


def test_restore_preserves_memory_context_and_budget(tmp_path, task):
    run, _ = make_run(tmp_path, task, direct_script())
    assert run.run_fresh()["status"] == "ok"
    ck = run.run_dir / "checkpoints/d0"
    web = fake_web(tmp_path, task.question)
    llm = ScriptedLLM({"worker": ["Title: Count\n2"], "evaluator_execution": [evaluation([row()])],
                       "orchestrator": [action("finish")]})
    restored = Run.restore(ck, tmp_path / "restored", task=task, web=web, transport=llm,
                           tool_cfg=run.tool_cfg)
    assert restored.run_restored()["status"] == "ok"
    assert restored.trace.run_scope.llm_calls == run.trace.run_scope.llm_calls
    assert json.loads((restored.run_dir / "restore_check.json").read_text())["match"]


def test_old_checkpoint_and_tamper_rejected(tmp_path, task):
    ck = tmp_path / "old"
    ck.mkdir()
    (ck / "state.json").write_text('{"format": 1}')
    with pytest.raises(ValueError, match="historical"):
        Run.restore(ck, tmp_path / "restore", task=task)
    run, _ = make_run(tmp_path, task, direct_script())
    run.run_fresh()
    ck = run.run_dir / "checkpoints/d0"
    (ck / "work/attachments/sheet.csv").write_text("tampered")
    with pytest.raises(ValueError, match="fingerprint"):
        Run.restore(ck, tmp_path / "tampered", task=task, web=fake_web(tmp_path), tool_cfg=run.tool_cfg, transport=ScriptedLLM({}))


def test_run_budget_is_terminal(tmp_path, task):
    run, _ = make_run(tmp_path, task, direct_script(), budget=Limits(max_llm_calls=1))
    assert run.run_fresh()["status"] == "budget_exceeded"


@pytest.mark.parametrize("original,target", [("direct_execution", "multi_worker_probe"), ("multi_worker_probe", "direct_execution")])
def test_current_checkpoints_restore_across_conditions(tmp_path, task, original, target):
    from test_refiners import probe_script
    run, _ = make_run(tmp_path, task, direct_script() if original == "direct_execution" else probe_script(), original)
    assert run.run_fresh()["status"] == "ok"
    script = {"orchestrator": [action("finish")], "worker": ["Title: Report\n2"],
              "evaluator_execution": [evaluation()], "orchestrator_select": [action("select", wid="gen_haiku")]}
    if target == "multi_worker_probe":
        script.update(worker=["Title: Probe\nplan: read", "Title: Probe\nplan: read", "Title: Report\n2"],
                      evaluator_probe=[evaluation()])
    restored = Run.restore(run.run_dir / "checkpoints/d0", tmp_path / "restored", task=task,
                           condition=ConditionConfig(target), web=fake_web(tmp_path), tool_cfg=run.tool_cfg,
                           transport=ScriptedLLM(script))
    info = restored.run_restored()
    assert info["status"] == "ok", info
    assert info["delegations"][0]["worker"] == "gen_haiku"


def test_checkpoint_after_two_delegations_has_state_and_artifact_pool(tmp_path, task):
    script = direct_script(orchestrator=[action(), action(), action(state_rows=[0]), action("finish")],
                           worker=["Title: First\n2", "Title: Second\n2", "Title: Third\n2"],
                           evaluator_execution=[evaluation([row()]), evaluation([row()]), evaluation([row()])])
    run, llm = make_run(tmp_path, task, script)
    assert run.run_fresh()["status"] == "ok"
    checkpoint = run.run_dir / "checkpoints/d2"
    saved = json.loads((checkpoint / "state.json").read_text())
    assert saved["memory"]["state"] == [row()]
    assert len(saved["memory"]["artifacts"]) == 4
    assert saved["pending_action"]["context_snapshot"] == [row()]
    context = json.loads(saved["pending_action"]["context"])
    assert context["state"][0]["status"] == "supported"
    assert [a["id"] for a in context["artifacts"]] == ["a00000"]
    restored = Run.restore(checkpoint, tmp_path / "restored", task=task, web=fake_web(tmp_path),
        tool_cfg=run.tool_cfg, transport=ScriptedLLM({"worker": ["Title: Restored\n2"],
        "evaluator_execution": [evaluation([row()])], "orchestrator": [action("finish")]}))
    assert restored.run_restored()["status"] == "ok"
    assert len(restored.memory.artifacts) == 6


def test_restore_rejects_tool_version_and_prompt_tamper(tmp_path, task):
    from dataclasses import replace
    run, _ = make_run(tmp_path, task, direct_script())
    run.run_fresh()
    ck = run.run_dir / "checkpoints/d0"
    for change in [{"tools_version": "v5"}, {"page_chars": 1}, {"reader_chain": ("direct",)}]:
        with pytest.raises(ValueError, match="tool settings"):
            Run.restore(ck, tmp_path / str(len(change)) / str(change), task=task, web=fake_web(tmp_path),
                        tool_cfg=replace(run.tool_cfg, **change), transport=ScriptedLLM({}))
    path = ck / "state.json"
    state = json.loads(path.read_text())
    state["evaluator_prompts_version"] = "old"
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="prompt version"):
        Run.restore(ck, tmp_path / "wrongprompt", task=task, web=fake_web(tmp_path), tool_cfg=run.tool_cfg,
                    transport=ScriptedLLM({}))


def test_trace_connects_artifacts_state_choices_tools_and_final_answer(tmp_path, task):
    import importlib.util
    from minpilot.tools.config import REPO_ROOT
    run, _ = make_run(tmp_path, task, direct_script(worker=[
        {"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]}, "Title: Count\n2"]))
    assert run.run_fresh()["status"] == "ok"
    events = [json.loads(line) for line in (run.run_dir / "events.jsonl").read_text().splitlines()]
    assert next(e for e in events if e["event"] == "report")["artifact_id"] == "a00000"
    state = next(e for e in events if e["event"] == "state_replace")
    assert state["before"] == [] and state["after"] == [row()] and state["evaluation"] == "a00001"
    assert next(e for e in events if e["event"] == "action" and e["action"] == "finish")["rationale"]
    spec = importlib.util.spec_from_file_location("render_trace", REPO_ROOT / "scripts/render_trace.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.render(run.run_dir, 100000)
    for expected in ["a00000", "state_replace", "context_selection", "order_id,date,amount", "FINAL ANSWER"]:
        assert expected in text
