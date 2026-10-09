"""Refiner prompts r6/r7 (decisions R21, R22): the four-item probe, the analysis order and acceptance rule, the rewrite rules,
context additions (facts to the context, actions to the instruction), the frozen r5 arm, the probe-tools condition
and its observation records, and the direct-check condition."""

from __future__ import annotations

import json

import pytest

from fakes import ScriptedLLM, delegate, finish
from minpilot.agents import prompts, prompts_r5
from minpilot.config import PROBE_QUESTIONS, RefinerConfig, refiner_from_dict
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
    for label in ("understanding:", "choices:", "risks:", "plan:"):
        assert f"\n{label}\n" in p
    assert "Do not invent items to fill the form." in p
    t = prompts.probe_instruction("do x", True, 3)
    assert "up to 3 tool calls" in t and "include what you found and its source" in t
    assert "Do not use tools" not in t


def test_parse_probe():
    got = prompts.parse_probe("**understanding:** the count of unique ids\nchoices:\n- ids, not rows\nrisks:\n"
                              "(none)\nplan:\n1. read the file\n2. count")
    assert got == {"understanding": "the count of unique ids", "choices": ["ids, not rows"], "risks": [],
                   "plan": ["read the file", "count"]}
    assert prompts.parse_probe("no labels here") is None


def test_r7_analysis_and_rewrite_texts(tmp_path, task):
    llm = ScriptedLLM(script(worker=["understanding: x\nchoices:\nrisks:\nplan:\n- a", "ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c2_probe_executor")
    assert run.run_fresh()["status"] == "ok"
    a = text(llm.by_kind["analyze"][0])
    assert a.index("1. The original task") < a.index("2. The instruction") < a.index("3. The answers")
    assert "neither an answer nor agreement between answers is evidence of a fact" in a
    assert "Do not accept generic risks" in a and "Compare the answer sets" not in a  # one answer set
    r = text(llm.by_kind["rewrite"][0])
    assert "Preserve the result requested by the original task." in r
    assert "Do not demand explicit statements or a separate proof of uniqueness" in r
    assert "Another conceivable interpretation is not sufficient." in r
    log = refine_log(run)
    assert log["prompts"] == "r7" and log["responses"][0]["parsed"]["plan"] == ["a"]
    assert json.loads((run.run_dir / "run.json").read_text())["refiner_prompts_version"] == "r7"


def test_context_additions_follow_the_unchanged_context(tmp_path, task):
    llm = ScriptedLLM(script(worker=["probe", "ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c2_probe_executor")
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
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c2_probe_executor")
    run.run_fresh()
    d = run.delegations[0]
    assert d["final"] == DRAFT and not d["changed"] and d["refine_status"] == "rewritten"
    assert FACT in text(llm.by_kind["worker"][-1])


def test_r5_arm_keeps_the_earlier_prompts(tmp_path, task):
    llm = ScriptedLLM(script(rewrite={"instruction": NEW, "changes": [], "unchanged": False},
                             analyze=[{"issues": [{**ISSUE, "kind": "assumption", "summary": "s"}], "followups": [],
                                       "verifications": [CHECK]}],
                             worker=["probe", "ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c2_probe_executor_r5")
    run.run_fresh()
    probe = text(llm.by_kind["worker"][0])
    assert prompts_r5.probe_instruction(DRAFT, PROBE_QUESTIONS, False, 0, True) in probe
    assert "Change only what is needed to address consequential issues" in text(llm.by_kind["rewrite"][0])
    assert "context_additions" not in llm.by_kind["rewrite"][0]["response_format"]["json_schema"]["schema"]["properties"]
    sent = text(llm.by_kind["worker"][-1])
    assert prompts.CONTEXT_ADDITIONS_HEAD not in sent and sent.count(CTX) == 1
    assert refine_log(run)["prompts"] == "r5"
    assert json.loads((run.run_dir / "run.json").read_text())["refiner_prompts_version"] == "r5"


def test_probe_tools_record_observations(tmp_path, task):
    url = "https://example.org/orders-2025"
    llm = ScriptedLLM(script(
        rewrite={"instruction": f"{NEW} Use {url}; it lists 37 orders.", "context_additions": "",
                 "changes": [], "unchanged": False},
        analyze=[{"issues": [{**ISSUE, "decision": "defer_to_execution"}], "followups": [], "verifications": []}],
        worker=[{"tool_calls": [("web_search", {"query": "orders 2025"})]}, "understanding: x\nrisks:\n- y", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c2_probe_tools")
    run.run_fresh()
    log = refine_log(run)
    obs = log["probe_observations"]
    assert len(obs) == 1 and obs[0]["tool"] == "web_search" and obs[0]["response_id"] == "r1"
    assert "orders 2025" in obs[0]["args"]
    assert "up to 3 tool calls" in text(llm.by_kind["worker"][0])
    assert "Tool observations that answers report" in text(llm.by_kind["analyze"][0])
    assert isinstance(log["observations_in_rewrite"], list)


def test_observation_overlap():
    from minpilot.refine.review import observation_overlap

    got = observation_overlap('Use https://a.org/x and "Table 3"; 2025 had 37 orders.',
                              ["task about 2025"], ['page https://a.org/x says "Table 3" lists 37 orders'])
    assert got == ["37", "https://a.org/x", "table 3"]


def test_direct_check_asks_no_worker_before_checks(tmp_path, task):
    llm = ScriptedLLM(script(worker=["ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c2_direct_check")
    assert run.run_fresh()["status"] == "ok"
    check, execution = (text(b) for b in llm.by_kind["worker"])
    assert "Do only this check" in check and NEW in execution and FACT in execution
    a = text(llm.by_kind["analyze"][0])
    assert "Answers about" not in a and "3. The answers" not in a
    assert refine_log(run)["responses"] == []


def test_config_rules():
    with pytest.raises(ValueError):
        RefinerConfig(name="x", kind="probe", questions=("plan",))  # questions are r5 only
    with pytest.raises(ValueError):
        RefinerConfig(name="x", kind="direct_check", prompts="r5")
    assert refiner_from_dict({"name": "old", "kind": "probe"}).prompts == "r5"  # recorded before prompt sets


def test_r7_review_continues_a_discarded_copy_of_the_orchestrator_conversation(tmp_path, task):
    llm = ScriptedLLM(script(worker=["probe", "ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c2_probe_executor")
    run.run_fresh()
    first = llm.by_kind["orchestrator"][0]["messages"]           # system + task
    action = llm.by_kind["analyze"][0]["messages"][len(first)]    # the pending delegate action
    analyze = llm.by_kind["analyze"][0]["messages"]
    assert analyze[:len(first)] == first and action["role"] == "assistant" and DRAFT in action["content"]
    assert analyze[-1]["content"].startswith(prompts.REVIEW_HEAD) and len(analyze) == len(first) + 2
    rewrite = llm.by_kind["rewrite"][0]["messages"]
    assert rewrite[:len(analyze)] == analyze and rewrite[len(analyze)]["role"] == "assistant"  # the analysis reply
    assert "Results of checks run before this delegation" in rewrite[-1]["content"]
    # the copy is discarded: the orchestrator's next turn has no review turn, only the report
    nxt = llm.by_kind["orchestrator"][1]["messages"]
    assert not any(prompts.REVIEW_HEAD in (m.get("content") or "") for m in nxt)
    assert len(nxt) == len(first) + 2


def test_r7_prediction_starts_from_the_conversation(tmp_path, task):
    llm = ScriptedLLM(script(simulate=["predicted"], worker=["ids repeat", "2"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c1_self_review")
    run.run_fresh()
    sim = llm.by_kind["simulate"][0]["messages"]
    assert sim[0]["content"].startswith("You are the orchestrator") and DRAFT in sim[-2]["content"]
    assert "The worker sees only the message below, not this conversation" in sim[-1]["content"]


def test_r7_decisions():
    from minpilot.refine.review import check_analysis

    ok = {"issues": [{**ISSUE, "decision": "clarify"}], "followups": [], "verifications": []}
    old = {"issues": [{**ISSUE, "decision": "resolved_from_task"}], "followups": [], "verifications": []}
    assert check_analysis(ok, set(), {"worker"}, prompts.DECISIONS) is None
    assert "unknown decisions" in check_analysis(old, set(), {"worker"}, prompts.DECISIONS)
    assert check_analysis(old, set(), {"worker"}, prompts_r5.DECISIONS) is None
