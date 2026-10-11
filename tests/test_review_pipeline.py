"""Review conversation isolation, fixed probe format, context additions and verification."""

from __future__ import annotations

import json

import pytest

from fakes import ScriptedLLM, delegate, finish
from minpilot import prompts
from minpilot.config import RefinerConfig, refiner_from_dict
from test_harness import make_run

CTX = "An earlier report (not verified) said the sheet has 100 orders, counted as rows."
DRAFT = "Count the orders in attachments/sheet.csv for 2025."
NEW = "Count unique order ids in attachments/sheet.csv for 2025."
FACT = "Order ids repeat across rows (check by the worker on attachments/sheet.csv)."
ISSUE = {"id": "i1", "target": "Count the orders", "impact": "rows are not orders", "evidence": "r1 counts rows",
         "decision": "needs_verification", "resolution": "check whether ids repeat"}
CHECK = {"issue_id": "i1", "worker_id": "worker", "instruction": "check whether ids repeat"}


def script(rewrite=None, **extra):
    s = {"orchestrator": [delegate("worker", DRAFT, CTX), finish("2")],
         "analyze": [{"issues": [ISSUE], "followups": [], "verifications": [CHECK]}],
         "rewrite": [rewrite or {"instruction": NEW, "context_additions": FACT, "changes": ["unique ids"],
                                 "unchanged": False}]}
    s.update(extra)
    return s


def text(body) -> str:
    """A worker request (messages[1]) or a review turn (the last message of the orchestrator conversation, r7)."""
    return body["messages"][-1]["content"] if body["messages"][0]["content"].startswith("You are the orchestrator") \
        else body["messages"][1]["content"]


def refine_log(run) -> dict:
    return json.loads((run.run_dir / "refine" / "d0.json").read_text())


def test_probe_has_four_labels_and_the_tool_policy():
    p = prompts.probe_instruction("do x", False, 0)
    assert p.startswith("Before executing the subtask, explain how you would approach it.\n"
                        "Do not use tools or execute the subtask.\n\nSubtask instruction:\n<<<\ndo x\n>>>")
    for label in ("understanding:", "assumptions:", "risks:", "plan:"):
        assert f"\n{label}\n" in p
    assert "Do not invent items to fill the form." in p
    t = prompts.probe_instruction("do x", True, 3)
    assert "up to 3 tool calls" in t and "include what you found and its source" in t
    assert "Do not use tools" not in t


def test_parse_probe():
    got = prompts.parse_probe("**understanding:** the count of unique ids\nassumptions:\n- ids, not rows\nrisks:\n"
                              "(none)\nplan:\n1. read the file\n2. count")
    assert got == {"understanding": "the count of unique ids", "assumptions": ["ids, not rows"], "risks": [],
                   "plan": ["read the file", "count"]}
    assert prompts.parse_probe("no labels here") is None


def test_analysis_and_rewrite_texts(tmp_path, task):
    llm = ScriptedLLM(script(worker=["understanding: x\nassumptions:\nrisks:\nplan:\n- a", "ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="executor_probe")
    assert run.run_fresh()["status"] == "ok"
    a = text(llm.by_kind["analyze"][0])
    assert a.index("1. The original task") < a.index("2. The instruction") < a.index("3. The answers")
    assert "Neither a claim nor agreement between answers establishes an external fact" in a
    assert "Omit generic or speculative concerns" in a and "Compare the answer sets" not in a  # one answer set
    r = text(llm.by_kind["rewrite"][0])
    assert "Preserve the result requested by the original task and the assigned subtask's scope." in r
    assert "Allow a supported inference" in r
    assert "Another conceivable interpretation is not sufficient." not in r  # r8 rule removed (R24)
    assert "rather than forcing an unsupported choice" in r and "not instructions to copy" in r
    assert "Keep observations separate from interpretations" in r
    assert "A subtask may cover only part of the original task" in a
    assert "missing evidence as confirmation" in a
    assert "predicted answers indicate how you expect it" in a
    log = refine_log(run)
    assert log["prompts"] == "r12" and log["responses"][0]["parsed"]["plan"] == ["a"]
    assert json.loads((run.run_dir / "run.json").read_text())["refiner_prompts_version"] == "r12"
    assert "[r1] (respondent 1)\n" in a and "gen_luna" not in a and log["probe_order"] == ["gen_luna"]


def test_context_additions_follow_the_unchanged_context(tmp_path, task):
    llm = ScriptedLLM(script(worker=["probe", "ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="executor_probe")
    run.run_fresh()
    sent = text(llm.by_kind["worker"][-1])
    assert sent.index(CTX) < sent.index(prompts.CONTEXT_ADDITIONS_HEAD) < sent.index(FACT) < sent.index(NEW)
    d = json.loads((run.run_dir / "run.json").read_text())["delegations"][0]
    assert d["context"] == CTX and d["context_additions"] == FACT and d["final"] == NEW
    report_msg = llm.by_kind["orchestrator"][1]["messages"][-1]["content"]
    assert "appended to your context" in report_msg and FACT in report_msg and NEW in report_msg
    assert refine_log(run)["context_additions"] == FACT


def test_additions_alone_are_sent_with_the_draft(tmp_path, task):
    llm = ScriptedLLM(script(rewrite={"instruction": DRAFT, "context_additions": FACT, "changes": [],
                                      "unchanged": False}, worker=["probe", "ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="executor_probe")
    run.run_fresh()
    d = run.delegations[0]
    assert d["final"] == DRAFT and not d["changed"] and d["refine_status"] == "rewritten"
    assert FACT in text(llm.by_kind["worker"][-1])




def test_probe_tools_record_observations(tmp_path, task):
    url = "https://example.org/orders-2025"
    llm = ScriptedLLM(script(
        rewrite={"instruction": f"{NEW} Use {url}; it lists 37 orders.", "context_additions": "",
                 "changes": [], "unchanged": False},
        analyze=[{"issues": [{**ISSUE, "decision": "defer_to_execution"}], "followups": [], "verifications": []}],
        worker=[{"tool_calls": [("web_search", {"query": "orders 2025"})]}, "understanding: x\nrisks:\n- y", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="executor_probe_tools")
    run.run_fresh()
    log = refine_log(run)
    obs = log["probe_observations"]
    assert len(obs) == 1 and obs[0]["tool"] == "web_search" and obs[0]["response_id"] == "r1"
    assert "orders 2025" in obs[0]["args"]
    assert "up to 3 tool calls" in text(llm.by_kind["worker"][0])
    assert "cite the reported tool observation and its source" in text(llm.by_kind["analyze"][0])
    assert isinstance(log["observations_in_rewrite"], list)


def test_observation_overlap():
    from minpilot.refine.review import observation_overlap

    got = observation_overlap('Use https://a.org/x and "Table 3"; 2025 had 37 orders.',
                              ["task about 2025"], ['page https://a.org/x says "Table 3" lists 37 orders'])
    assert got == ["37", "https://a.org/x", "table 3"]


def test_config_rules():
    with pytest.raises(TypeError):
        RefinerConfig(name="x", kind="probe", questions=("plan",))
    with pytest.raises(ValueError, match="unknown refiner kind"):
        RefinerConfig(name="x", kind="direct_check")
    with pytest.raises(ValueError, match="no prompt version"):
        refiner_from_dict({"name": "old", "kind": "probe"})
    assert refiner_from_dict({"name": "current", "kind": "probe", "prompts": "r12",
                              "questions": ["understanding", "assumptions", "failure", "plan"]}).prompts == "r12"
    with pytest.raises(ValueError):
        RefinerConfig(name="x", kind="probe", prompts="r7")  # not kept (R23)
    with pytest.raises(ValueError):
        RefinerConfig(name="x", kind="probe", prompts="r8")  # not kept (R24)


def test_review_continues_a_discarded_copy_of_the_orchestrator_conversation(tmp_path, task):
    llm = ScriptedLLM(script(worker=["probe", "ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="executor_probe")
    run.run_fresh()
    first = llm.by_kind["orchestrator"][0]["messages"]           # system + task
    action = llm.by_kind["analyze"][0]["messages"][len(first)]    # the pending delegate action
    analyze = llm.by_kind["analyze"][0]["messages"]
    assert analyze[:len(first)] == first and action["role"] == "assistant" and DRAFT in action["content"]
    assert analyze[-1]["content"].startswith(prompts.REVIEW_HEAD) and len(analyze) == len(first) + 2
    rewrite = llm.by_kind["rewrite"][0]["messages"]
    assert rewrite[:len(analyze)] == analyze and rewrite[len(analyze)]["role"] == "assistant"  # the analysis reply
    assert "## Check results" in rewrite[-1]["content"]
    # the copy is discarded: the orchestrator's next turn has no review turn, only the report
    nxt = llm.by_kind["orchestrator"][1]["messages"]
    assert not any(prompts.REVIEW_HEAD in (m.get("content") or "") for m in nxt)
    assert len(nxt) == len(first) + 2


def test_prediction_starts_from_the_conversation(tmp_path, task):
    llm = ScriptedLLM(script(simulate=["predicted"], worker=["ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="self_review")
    run.run_fresh()
    sim = llm.by_kind["simulate"][0]["messages"]
    assert sim[0]["content"].startswith("You are the orchestrator") and DRAFT in sim[-2]["content"]
    assert "The worker sees only its system prompt and the message below, not this conversation" in sim[-1]["content"]


def test_decisions():
    from minpilot.refine.review import check_analysis

    ok = {"issues": [{**ISSUE, "decision": "clarify"}], "followups": [], "verifications": []}
    old = {"issues": [{**ISSUE, "decision": "resolved_from_task"}], "followups": [], "verifications": []}
    assert check_analysis(ok, set(), {"worker"}, prompts.DECISIONS) is None
    assert "unknown decisions" in check_analysis(old, set(), {"worker"}, prompts.DECISIONS)
