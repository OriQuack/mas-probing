"""Harness: the orchestrator loop, call_worker, checkpoints and restores (scripted models, no network)."""

from __future__ import annotations

import json

import pytest

from fakes import ScriptedLLM, delegate, fake_web, finish
from minpilot.config import RunConfig, load_pool, load_refiner
from minpilot.harness import Run
from minpilot.runtime.trace import Limits
from minpilot.tools.config import ToolConfig


def make_run(tmp_path, task, llm, *, pool="role_routing", refiner="A_none", refine_at="first", name="run", **kw):
    cfg = RunConfig(pool=load_pool(pool), refiner=load_refiner(refiner), refine_at=refine_at, label=name, **kw)
    return Run(cfg, task, tmp_path / name, transport=llm, web=fake_web(tmp_path, task.question),
               tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))


def two_step_script():
    return {
        "orchestrator": [delegate("file_analyst", "Count unique order ids in attachments/sheet.csv for 2025."),
                         finish("2")],
        "worker": [{"tool_calls": [("read_file", {"path": "attachments/sheet.csv"})]},
                   "There are 2 unique order ids (1 and 2). Source: attachments/sheet.csv."],
    }


def events(run_dir):
    return [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]


def test_fresh_run_end_to_end(tmp_path, task):
    llm = ScriptedLLM(two_step_script())
    run = make_run(tmp_path, task, llm)
    info = run.run_fresh()
    assert info["status"] == "ok" and info["final_answer"] == "2"
    rd = run.run_dir
    assert (rd / "work" / "attachments" / "sheet.csv").exists()
    assert (rd / "checkpoints" / "d0" / "state.json").exists()
    req = json.loads((rd / "checkpoints" / "d0" / "request.json").read_text())
    assert req["target_worker"] == "file_luna" and "unique order" in req["draft_instruction"]
    # the worker received the original task + the instruction, and its tool result
    wbody = llm.by_kind["worker"][1]
    user = wbody["messages"][1]["content"]
    assert "Original task" in user and task.question in user and "Count unique order ids" in user
    assert any(m["role"] == "tool" and "order_id" in m["content"] for m in wbody["messages"])
    # orchestrator saw the report, never the tool output directly
    obody = llm.by_kind["orchestrator"][1]
    assert "Report from file_analyst" in obody["messages"][-1]["content"]
    assert not any("order_id,date" in json.dumps(m) for m in obody["messages"])
    # orchestrator requests carry no tools; workers carry their own tool set only
    assert all("tools" not in b for b in llm.by_kind["orchestrator"])
    assert {t["function"]["name"] for t in wbody["tools"]} == {"read_file", "view_image", "run_python"}
    kinds = [e["event"] for e in events(rd)]
    assert kinds.count("delegation") == 1 and "checkpoint" in kinds and kinds[-1] == "run_end"
    stages = {json.loads(l).get("stage") for l in (rd / "llm_calls.jsonl").read_text().splitlines()}
    assert stages == {"orchestrator", "execution"}


def test_invalid_action_retried_then_error(tmp_path, task):
    bad = {"rationale": "r", "action": "delegate", "worker_id": "nobody", "instruction": "x", "answer": None}
    llm = ScriptedLLM({"orchestrator": [bad, bad, bad]})
    info = make_run(tmp_path, task, llm).run_fresh()
    assert info["status"] == "error" and "invalid_action" in info["error"]
    assert "unknown worker_id" in llm.by_kind["orchestrator"][1]["messages"][-1]["content"]


def test_max_delegations_forces_finish(tmp_path, task):
    llm = ScriptedLLM({"orchestrator": [delegate("web_researcher", "look"), finish("x")], "worker": ["done"]})
    info = make_run(tmp_path, task, llm, max_delegations=1).run_fresh()
    assert info["status"] == "ok" and info["forced_finish"] is True
    assert "maximum number of delegations" in llm.by_kind["orchestrator"][1]["messages"][-1]["content"]


def test_worker_tool_limit_forces_report(tmp_path, task):
    calls = [{"tool_calls": [("web_search", {"query": f"q{i}"})]} for i in range(30)]
    llm = ScriptedLLM({"orchestrator": [delegate("web_researcher", "search"), finish("x")],
                       "worker": lambda b: calls.pop(0) if b.get("tool_choice") != "none" else "partial report"})
    run = make_run(tmp_path, task, llm)
    run.run_fresh()
    last = llm.by_kind["worker"][-1]
    assert last["tool_choice"] == "none" and "tool-call limit" in last["messages"][-1]["content"]
    assert run.delegations[0]["report_status"] == "tool_limit" and run.delegations[0]["n_tool_calls"] == 20


def test_run_budget_exceeded_is_recorded(tmp_path, task):
    llm = ScriptedLLM(two_step_script())
    info = make_run(tmp_path, task, llm, budget=Limits(max_llm_calls=2)).run_fresh()
    assert info["status"] == "budget_exceeded" and info["final_answer"] is None


def test_restore_matches_continuous_run(tmp_path, task):
    """Given the same responses, a run restored from d0 sends exactly the requests the continuous run sent after
    the checkpoint."""
    llm1 = ScriptedLLM(two_step_script())
    run1 = make_run(tmp_path, task, llm1, name="cont")
    run1.run_fresh()
    after = [b for b in llm1.bodies[1:]]  # everything after the first orchestrator call (the checkpoint)
    script = two_step_script()
    script["orchestrator"] = script["orchestrator"][1:]
    llm2 = ScriptedLLM(script)
    run2 = Run.restore(run1.run_dir / "checkpoints" / "d0", tmp_path / "restored", task=task, transport=llm2,
                       web=fake_web(tmp_path, task.question), tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))
    info = run2.run_restored()
    assert info["status"] == "ok" and info["final_answer"] == "2"
    assert json.loads((tmp_path / "restored" / "restore_check.json").read_text())["match"] is True
    assert llm2.bodies == after
    assert run2.trace.run_scope.llm_calls == run1.trace.run_scope.llm_calls


def test_restore_refuses_tampered_workspace(tmp_path, task):
    run1 = make_run(tmp_path, task, ScriptedLLM(two_step_script()), name="cont")
    run1.run_fresh()
    ck = run1.run_dir / "checkpoints" / "d0"
    (ck / "work" / "attachments" / "sheet.csv").write_text("changed")
    with pytest.raises(ValueError, match="fingerprint"):
        Run.restore(ck, tmp_path / "r", task=task, transport=ScriptedLLM({}), web=fake_web(tmp_path),
                    tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))


def test_restore_with_override(tmp_path, task):
    run1 = make_run(tmp_path, task, ScriptedLLM(two_step_script()), name="cont")
    run1.run_fresh()
    script = two_step_script()
    script["orchestrator"] = script["orchestrator"][1:]
    llm2 = ScriptedLLM(script)
    run2 = Run.restore(run1.run_dir / "checkpoints" / "d0", tmp_path / "ov", task=task, transport=llm2,
                       override="Count unique order ids; rows with the same id are one order.",
                       override_source="post_hoc", web=fake_web(tmp_path),
                       tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))
    info = run2.run_restored()
    assert info["override_source"] == "post_hoc"
    assert "same id are one order" in llm2.by_kind["worker"][0]["messages"][1]["content"]
    assert "revised in a pre-delegation review" in llm2.by_kind["orchestrator"][0]["messages"][-1]["content"]


def test_recovered_invalid_action_is_logged(tmp_path, task):
    bad = {"rationale": "r", "action": "delegate", "worker_id": "nobody", "instruction": "x", "answer": None}
    llm = ScriptedLLM({"orchestrator": [bad, finish("7")]})
    run = make_run(tmp_path, task, llm)
    assert run.run_fresh()["final_answer"] == "7"
    act = [e for e in events(run.run_dir) if e["event"] == "action"][0]
    assert len(act["invalid_before"]) == 1 and "unknown worker_id" in act["invalid_before"][0]


def test_restore_allows_newer_blocklist_but_not_older(tmp_path, task):
    run1 = make_run(tmp_path, task, ScriptedLLM(two_step_script()), name="cont")
    run1.run_fresh()
    ck = run1.run_dir / "checkpoints" / "d0"
    state = json.loads((ck / "state.json").read_text())
    kw = dict(task=task, transport=ScriptedLLM({}), web=fake_web(tmp_path),
              tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))
    state["tools"]["blocklist_version"] = "v1"          # an older checkpoint: allowed
    (ck / "state.json").write_text(json.dumps(state))
    run = Run.restore(ck, tmp_path / "newer", **kw)
    assert run.info["checkpoint_blocklist_version"] == "v1"
    state["tools"]["blocklist_version"] = "v99"         # a checkpoint newer than the code: refused
    (ck / "state.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="blocklist_version is older"):
        Run.restore(ck, tmp_path / "older", **kw)


def _checkpoint(tmp_path, task):
    run1 = make_run(tmp_path, task, ScriptedLLM(two_step_script()), name="cont")
    run1.run_fresh()
    return run1.run_dir / "checkpoints" / "d0"


@pytest.mark.parametrize("change", [{"page_chars": 7}, {"reader_chain": ("direct",)}, {"code_timeout_s": 1.0}])
def test_restore_refuses_other_tool_settings(tmp_path, task, change):
    ck = _checkpoint(tmp_path, task)
    with pytest.raises(ValueError, match="tool settings differ"):
        Run.restore(ck, tmp_path / "r", task=task, transport=ScriptedLLM({}), web=fake_web(tmp_path),
                    tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite", **change))


def test_restore_refuses_other_reader_identity(tmp_path, task):
    ck = _checkpoint(tmp_path, task)
    state = json.loads((ck / "state.json").read_text())
    state["reader_identity"] = {"tag": "x", "docker_digest": "sha256:a", "sif_sha256": "b", "version": "1"}
    (ck / "state.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="page-reader service identity"):
        Run.restore(ck, tmp_path / "r", task=task, transport=ScriptedLLM({}), web=fake_web(tmp_path),
                    tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"),
                    reader_identity={"tag": "x", "docker_digest": "sha256:other", "sif_sha256": "b", "version": "1"})


def test_symlinks_are_part_of_the_fingerprint(tmp_path, task):
    import os

    run1 = make_run(tmp_path, task, ScriptedLLM(two_step_script()), name="cont")
    (run1.run_dir / "work" / "attachments").mkdir(parents=True)
    for n in ("one.txt", "two.txt"):
        (run1.run_dir / "work" / n).write_text(n)
    os.symlink("one.txt", run1.run_dir / "work" / "alias.txt")
    run1.run_fresh()
    ck = run1.run_dir / "checkpoints" / "d0"
    os.remove(ck / "work" / "alias.txt")
    os.symlink("two.txt", ck / "work" / "alias.txt")
    with pytest.raises(ValueError, match="fingerprint"):
        Run.restore(ck, tmp_path / "r", task=task, transport=ScriptedLLM({}), web=fake_web(tmp_path),
                    tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))
    os.remove(ck / "work" / "alias.txt")
    os.symlink("/etc/passwd", ck / "work" / "alias.txt")
    with pytest.raises(ValueError, match="symlinks leading outside"):
        Run.restore(ck, tmp_path / "r2", task=task, transport=ScriptedLLM({}), web=fake_web(tmp_path),
                    tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))


def test_answer_rules_come_from_the_benchmark_and_answer_is_kept(tmp_path, task):
    from minpilot.data.gaia import ANSWER_FORMAT

    llm = ScriptedLLM({"orchestrator": [{**finish("2"), "rationale": "two ids, if 2025 means the calendar year"}]})
    run = make_run(tmp_path, task, llm)
    info = run.run_fresh()
    system = llm.by_kind["orchestrator"][0]["messages"][0]["content"]
    assert ANSWER_FORMAT in system and "Do not add explanations, conditions, caveats" in system
    assert info["final_answer"] == "2" and info["final_rationale"].startswith("two ids")
    assert set(info["models"]) == {"luna-high"}  # every role, the page reader included (M1)
