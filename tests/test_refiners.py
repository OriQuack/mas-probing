"""Refiners A/B/C through the harness: what each sees, what it calls, isolation, budgets."""

from __future__ import annotations

import json

import pytest

from fakes import ScriptedLLM, delegate, finish
from minpilot.config import RefinerConfig, load_refiner
from minpilot.runtime.trace import Limits
from test_harness import make_run

DRAFT = "Count the orders in attachments/sheet.csv for 2025."
REWRITTEN = "Task: count UNIQUE order ids in attachments/sheet.csv for 2025.\nCriteria: rows with the same id are one order."

ISSUE = {"id": "i1", "kind": "assumption", "summary": "rows vs unique ids", "evidence": "r1 counts rows",
         "decision": "resolved_from_task", "resolution": "count unique ids"}


def analysis(issues=(ISSUE,), followups=(), verifications=()):
    return {"issues": list(issues), "followups": list(followups), "verifications": list(verifications)}


def rewrite(instr=REWRITTEN):
    return {"instruction": instr, "changes": ["unique ids"], "unchanged": False}


def base_script(**extra):
    s = {"orchestrator": [delegate("generalist", DRAFT), finish("2")],
         "analyze": [analysis()], "rewrite": [rewrite()]}
    s.update(extra)
    return s


def refine_log(run):
    return json.loads((run.run_dir / "refine" / "d0.json").read_text())


def test_A_executes_draft_without_extra_calls(tmp_path, task):
    llm = ScriptedLLM({"orchestrator": [delegate("generalist", DRAFT), finish("3")], "worker": ["3 orders"]})
    run = make_run(tmp_path, task, llm, pool="single", refiner="A_none")
    run.run_fresh()
    assert len(llm.by_kind["worker"]) == 1 and DRAFT in llm.by_kind["worker"][0]["messages"][1]["content"]
    assert set(llm.by_kind) == {"orchestrator", "worker"}


def test_C_probes_every_candidate_and_executes_rewrite(tmp_path, task):
    llm = ScriptedLLM(base_script(**{"worker:openai/gpt-6-luna-20260922": ["probe answer luna", "2 unique orders"],
                                     "worker:google/gemini-3.1-flash-lite": ["probe answer gemini"]}))
    run = make_run(tmp_path, task, llm, pool="redundant", refiner="C_probe")
    info = run.run_fresh()
    assert info["status"] == "ok"
    w = llm.by_kind["worker"]
    probes, execution = w[:2], w[2]
    assert [b["model"] for b in probes] == ["openai/gpt-6-luna-20260922", "google/gemini-3.1-flash-lite"]
    for b in probes:  # probe: original task + draft + the four questions; no tools by default
        text = b["messages"][1]["content"]
        assert task.question in text and DRAFT in text and "Do NOT carry out" in text and "4. Plan" in text
        assert "tools" not in b
    # analysis saw both real answers; the executor (fixed: gen_luna) got the rewrite, in a fresh conversation
    a = llm.by_kind["analyze"][0]["messages"][1]["content"]
    assert "probe answer luna" in a and "probe answer gemini" in a and "given by the worker" in a
    assert execution["model"] == "openai/gpt-6-luna-20260922"
    assert REWRITTEN in execution["messages"][1]["content"] and len(execution["messages"]) == 2
    assert not any("probe answer" in json.dumps(m) for m in execution["messages"])
    # the orchestrator never sees the probe dialogue, only the instruction actually sent
    last = llm.by_kind["orchestrator"][1]["messages"]
    assert not any("probe answer" in json.dumps(m) for m in last) and REWRITTEN in last[-1]["content"]
    log = refine_log(run)
    assert log["status"] == "rewritten" and len(log["responses"]) == 2
    stages = [json.loads(l).get("stage") for l in (run.run_dir / "llm_calls.jsonl").read_text().splitlines()
              if '"status": "ok"' in l]
    assert stages == ["orchestrator", "refine.probe", "refine.probe", "refine.analyze", "refine.rewrite",
                      "execution", "orchestrator"]


def test_B_predicts_same_slots_without_worker_calls(tmp_path, task):
    llm = ScriptedLLM(base_script(simulate=["predicted luna", "predicted gemini"], worker=["2 unique orders"]))
    run = make_run(tmp_path, task, llm, pool="redundant", refiner="B_self_review")
    run.run_fresh()
    assert len(llm.by_kind["simulate"]) == 2  # one prediction per probe slot C would fill
    assert all(b["model"] == "openai/gpt-6-luna-20260922" and b["reasoning"] == {"effort": "high"}
               for b in llm.by_kind["simulate"])
    assert len(llm.by_kind["worker"]) == 1  # execution only
    a = llm.by_kind["analyze"][0]["messages"][1]["content"]
    assert "predicted luna" in a and "that you predicted" in a
    assert REWRITTEN in llm.by_kind["worker"][0]["messages"][1]["content"]


def test_no_issues_keeps_draft_without_rewrite(tmp_path, task):
    llm = ScriptedLLM(base_script(analyze=[analysis(issues=())], rewrite=[], worker=["probe", "3"]))
    run = make_run(tmp_path, task, llm, pool="single", refiner="C_probe")
    run.run_fresh()
    assert "rewrite" not in llm.by_kind and refine_log(run)["status"] == "no_issues"
    assert DRAFT in llm.by_kind["worker"][-1]["messages"][1]["content"]


def test_followup_continues_the_probe_conversation(tmp_path, task):
    a1 = analysis(followups=[{"response_id": "r1", "question": "Rows or unique ids?"}])
    llm = ScriptedLLM(base_script(analyze=[a1, analysis()], worker=["I count rows", "unique ids then", "2"]))
    run = make_run(tmp_path, task, llm, pool="single", refiner="C_probe")
    run.run_fresh()
    fu = llm.by_kind["worker"][1]["messages"]
    assert "I count rows" in json.dumps(fu) and "Rows or unique ids?" in fu[-1]["content"]
    assert len(llm.by_kind["analyze"]) == 2 and "unique ids then" in llm.by_kind["analyze"][1]["messages"][1]["content"]


def test_connected_condition_continues_probe_into_execution(tmp_path, task):
    llm = ScriptedLLM(base_script(worker=["probe answer", "2"]))
    run = make_run(tmp_path, task, llm, pool="single", refiner="C_probe_connected")
    run.run_fresh()
    ex = llm.by_kind["worker"][-1]["messages"]
    assert "probe answer" in json.dumps(ex) and REWRITTEN in ex[-1]["content"]


def test_refine_budget_exceeded_keeps_draft(tmp_path, task):
    cfg = load_refiner("C_probe")
    tight = RefinerConfig(**{**cfg.__dict__, "budget": Limits(max_llm_calls=1)})
    llm = ScriptedLLM(base_script(worker=["probe", "3"]))
    run = make_run(tmp_path, task, llm, pool="single", refiner="C_probe")
    run.cfg = run.cfg.__class__(**{**run.cfg.__dict__, "refiner": tight})
    from minpilot.refine.base import make_refiner

    run.refiner = make_refiner(tight)
    info = run.run_fresh()
    assert info["status"] == "ok" and refine_log(run)["status"] == "budget_exceeded"
    assert DRAFT in llm.by_kind["worker"][-1]["messages"][1]["content"]


def test_refine_at_first_only_refines_first_delegation(tmp_path, task):
    llm = ScriptedLLM({"orchestrator": [delegate("generalist", DRAFT), delegate("generalist", "second"), finish("2")],
                       "analyze": [analysis()], "rewrite": [rewrite()], "worker": ["p", "r1", "r2"]})
    run = make_run(tmp_path, task, llm, pool="single", refiner="C_probe", refine_at="first")
    run.run_fresh()
    assert [d["refine_status"] for d in run.delegations] == ["rewritten", "not_selected"]


@pytest.mark.landlock
def test_verification_runs_in_scratch_workspace(tmp_path, task):
    """A check delegated by the refiner writes a file; it must not appear in the execution's workspace."""
    ver = analysis(issues=[{**ISSUE, "decision": "needs_verification"}],
                   verifications=[{"issue_id": "i1", "worker_id": "generalist", "instruction": "write marker"}])
    code = "open('marker.txt','w').write('x'); print('ok')"
    llm = ScriptedLLM(base_script(analyze=[ver], worker=[
        "probe", {"tool_calls": [("run_python", {"code": code})]}, "wrote marker", "2"]))
    run = make_run(tmp_path, task, llm, pool="single", refiner="C_probe")
    run.run_fresh()
    assert not (run.work_dir / "marker.txt").exists()
    assert list((run.run_dir / "scratch" / "d0").rglob("marker.txt"))
    assert refine_log(run)["verifications"][0]["report"] == "wrote marker"
    assert "wrote marker" in llm.by_kind["rewrite"][0]["messages"][1]["content"]
