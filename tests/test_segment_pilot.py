"""perturbation_consistency.segment: segment targets, whole-segment prompts and node answer lines (scripted models)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fakes import ScriptedLLM
from minpilot.llm.client import LLMClient
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import Limits, Trace
from perturbation_consistency import segment
from perturbation_consistency.longcot_nodes import parse_chain

PROMPT = """Solve this problem step by step and return the final solution at the end.

Problem node_0: Find the number of divisors of $36$.
Problem node_1: Compute [For this value use the answer from problem node_0 and add 1] squared.
Problem node_2: Compute $2^{[For this value use the answer from problem node_1 and subtract 90]}$.
What are the answers to problem node_2, and node_1?
Return the answers as a single comma-separated list in the format: solution = [answer for node_2, answer for node_1].
"""


def chain():
    return parse_chain("linear_hard_98", PROMPT)


def test_the_segment_ends_at_the_first_requested_node_after_node_0():
    t = segment.segment_target(chain(), "hard")
    assert t.target_id == "linear_hard_98:node_1" and t.nodes == ("node_0", "node_1") and t.inputs == {}
    late = PROMPT.replace("What are the answers to problem node_2, and node_1?",
                          "What are the answers to problem node_2?")
    assert segment.segment_target(parse_chain("q", late), "hard").nodes == ("node_0", "node_1", "node_2")


def test_build_prompts_perturbs_the_whole_segment_and_asks_for_every_node():
    c, t = chain(), segment.segment_target(chain(), "hard")
    rewrites = {"paraphrase": {"ok": True, "text": "Problem node_0: P0\nProblem node_1: P1"},
                "structured": {"ok": False}, "related_fact": {"ok": True, "text": "Note: 36 is a square."}}
    rows = segment.build_prompts(c, t, rewrites, ["Solve node_0 by prime factorisation first", "Go backwards"])
    counts = {}
    for r in rows:
        counts[r["condition"]] = counts.get(r["condition"], 0) + 1
    assert counts == {"repeat": 3, "instruction": 3, "surface": 2, "methods": 2, "avoid_first": 3}
    assert all(r["answer_node"] == "node_1" and r["nodes"] == ["node_0", "node_1"] for r in rows)
    assert all("`node_0 = <exact value>`, `node_1 = <exact value>`" in r["prompt"] for r in rows)
    assert all("Problem node_2" not in r["prompt"] for r in rows)
    surface = [r for r in rows if r["condition"] == "surface"]
    assert "Problem node_0: P0" in surface[0]["prompt"] and surface[1]["prompt"].count("Note: 36 is a square.") == 1


def test_node_answer_lines_are_read_in_common_forms():
    text = "work\nnode_0 = 9\n**node_1 = 100**\n\\(node_2\\) = \\frac{1}{2}\nmethod = x\nanswer = 100"
    assert segment.node_answers(text) == {"node_0": "9", "node_1": "100", "node_2": "\\frac{1}{2}"}


def test_a_segment_rewrite_must_keep_every_node_label(tmp_path):
    text = segment.segment_text(chain(), ("node_0", "node_1"))
    dropped = text.replace("Problem node_1:", "Then:")
    llm = ScriptedLLM({"rewrite": [{"text": dropped}, {"text": text.replace("Find", "Determine")}],
                       "worker": lambda b: {"same_problem": True, "reason": "same"}})
    out = segment.rewrite(LLMClient(get_spec("sonnet-high"), Trace(tmp_path, Limits()), transport=llm),
                          "paraphrase", text, ("node_0", "node_1"))
    assert out["ok"] and "Determine" in out["text"] and out["attempts"][0]["lost"] == ["node_1"]


def test_a_segment_call_falls_back_to_the_last_node_line(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_perturbation_pilot.py"
    spec = importlib.util.spec_from_file_location("run_perturbation_pilot", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    llm = ScriptedLLM({"worker": ["node_0 = 9\nnode_1 = 100\nmethod = direct"]})
    trace = Trace(tmp_path, Limits())
    row = {"target_id": "q:node_1", "condition": "repeat", "sample": 0, "detail": "plain", "prompt": "p",
           "answer_node": "node_1", "nodes": ["node_0", "node_1"]}
    rec = mod.call(LLMClient(get_spec("luna-medium"), trace, transport=llm), trace, row, "luna-medium")
    assert rec["answer"] == "100" and rec["node_answers"] == {"node_0": "9", "node_1": "100"} and rec["status"] == "ok"
