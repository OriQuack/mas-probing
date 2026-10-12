"""perturbation_consistency.perturb: targets, rewrite checks, prompts and pilot calls (scripted models)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from fakes import Raw, ScriptedLLM
from minpilot.llm.client import LLMClient
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import Limits, Trace
from perturbation_consistency import perturb
from perturbation_consistency.longcot_nodes import parse_chain

PROMPT = """Solve this problem step by step and return the final solution at the end.

Problem node_0: Let $S$ be a set of consecutive positive integers whose digit sums are not multiples of 11. Find the largest $|S|$.
Problem node_1: Let $a+b+c = [For this value use the answer from problem node_0 and subtract 35]$. Find the minimum of $a^2+b^2+c^2$.
Problem node_2: Compute [For this value use the answer from problem node_1 and add 1] squared.
What are the answers to problem node_2, node_1, and node_0?
Return the answers as a single comma-separated list in the format: solution = [answer for node_2, answer for node_1, answer for node_0].
"""
GOLD = {"node_2": "16", "node_1": "3", "node_0": "38"}


def chain():
    return parse_chain("linear_hard_99", PROMPT)


def test_eligible_targets_need_gold_for_the_node_and_its_inputs():
    gold = {"node_2": "16", "node_0": "38"}  # node_1 not requested: node_2 cannot get its input
    ts = perturb.eligible_targets(chain(), gold, "hard", "linear")
    assert [(t.node, t.kind, t.inputs) for t in ts] == [("node_0", "first", {})]
    ts = perturb.eligible_targets(chain(), GOLD, "hard", "linear")
    assert [(t.node, t.kind, t.inputs) for t in ts] == [("node_0", "first", {}), ("node_1", "middle", {"node_0": "38"}),
                                                        ("node_2", "middle", {"node_1": "3"})]


def test_pick_targets_fills_each_stratum_with_one_target_per_question():
    pool = [perturb.Target(f"q{i}:node_{k}", f"q{i}", "hard", "linear", f"node_{k}", "middle" if k else "first", {})
            for i in range(5) for k in (0, 1)]
    picked = perturb.pick_targets(pool, {("hard", "first"): 2, ("hard", "middle"): 3}, seed=0)
    assert len(picked) == 5 and len({t.question_id for t in picked}) == 5
    assert picked == perturb.pick_targets(pool, {("hard", "first"): 2, ("hard", "middle"): 3}, seed=0)
    with pytest.raises(ValueError):
        perturb.pick_targets(pool, {("hard", "first"): 6}, seed=0)


def test_a_rewrite_must_keep_formulas_numbers_and_placeholders():
    text = chain().node("node_1").text
    ok = ("Suppose $a+b+c = [For this value use the answer from problem node_0 and subtract 35]$. "
          "What is the least value of $a^2+b^2+c^2$?")
    assert perturb.preserved(text, ok) == []
    assert perturb.preserved(text, ok.replace("subtract 35", "subtract 36"))  # placeholder changed
    plain = chain().node("node_0").text
    assert perturb.preserved(plain, plain.replace("multiples of 11", "multiples of eleven")) == ["11"]


def test_build_prompts_gives_three_samples_per_condition_and_drops_failed_rewrites():
    t = perturb.eligible_targets(chain(), GOLD, "hard", "linear")[1]
    node = chain().node("node_1")
    rewrites = {"paraphrase": {"ok": True, "text": "P"}, "structured": {"ok": False, "text": None}}
    rows = perturb.build_prompts(node, t, rewrites, ["Use Cauchy-Schwarz", "Use Lagrange multipliers", "Use QM-AM"])
    by = {}
    for r in rows:
        by.setdefault(r["condition"], []).append(r)
    assert {c: len(v) for c, v in by.items()} == {"repeat": 3, "instruction": 3, "surface": 2, "methods": 3,
                                                  "avoid_first": 3}
    assert all(r["prompt"].endswith(perturb.FORMAT) and "- node_0: 38" in r["prompt"] for r in rows)
    assert len({r["prompt"] for r in by["repeat"]}) == 1 and len({r["prompt"] for r in by["instruction"]}) == 3
    assert [r["detail"] for r in by["surface"]] == ["paraphrase", "irrelevant"]
    assert "Problem node_1: P" in by["surface"][0]["prompt"] and perturb.IRRELEVANT in by["surface"][1]["prompt"]
    assert "Use Lagrange multipliers." in by["methods"][1]["prompt"]


def test_rewrite_retries_and_drops_a_rewrite_that_loses_a_number(tmp_path):
    text = chain().node("node_0").text
    good = ("Consider runs of consecutive positive integers in which no digit sum is a multiple of 11; "
            "find the largest $|S|$ for a set $S$ of them.")
    replies = iter(["multiples of eleven only, $S$, $|S|$", good])
    llm = ScriptedLLM({"rewrite": lambda b: {"text": next(replies)},
                       "worker": lambda b: {"same_problem": True, "reason": "same"}})
    client = LLMClient(get_spec("sonnet-medium"), Trace(tmp_path, Limits()), transport=llm)
    out = perturb.rewrite(client, "paraphrase", text)
    assert out["ok"] and out["text"] == good and out["attempts"][0]["lost"] == ["11"]
    bad = ScriptedLLM({"rewrite": lambda b: {"text": good}, "worker": lambda b: {"same_problem": False, "reason": "x"}})
    out = perturb.rewrite(LLMClient(get_spec("sonnet-medium"), Trace(tmp_path / "b", Limits()), transport=bad),
                          "structured", text)
    assert not out["ok"] and out["text"] is None and len(out["attempts"]) == 2


def test_approaches_come_from_the_rewriter_with_a_schema(tmp_path):
    llm = ScriptedLLM({"worker": lambda b: {"approaches": ["A", "B", "C"]}})
    client = LLMClient(get_spec("sonnet-medium"), Trace(tmp_path, Limits()), transport=llm)
    assert perturb.approaches(client, "Problem node_0: x") == ["A", "B", "C"]
    assert llm.bodies[0]["response_format"]["json_schema"]["name"] == "approaches"


def _pilot_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_perturbation_pilot.py"
    spec = importlib.util.spec_from_file_location("run_perturbation_pilot", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_pilot_call_records_answer_method_and_status(tmp_path):
    mod = _pilot_module()
    llm = ScriptedLLM({"worker": [ "work\nmethod = carry analysis\nanswer = 38", Raw("...", "length")]})
    trace = Trace(tmp_path, Limits())
    client = LLMClient(get_spec("haiku-medium"), trace, transport=llm)
    row = {"target_id": "q:node_0", "condition": "repeat", "sample": 0, "detail": "plain", "prompt": "p"}
    ok = mod.call(client, trace, row, "haiku-medium")
    assert ok["answer"] == "38" and ok["method"] == "carry analysis" and ok["status"] == "ok"
    cut = mod.call(client, trace, row, "haiku-medium")
    assert cut["status"] == "length" and cut["answer"] is None


def test_method_label_takes_the_last_method_line():
    text = "method = first\n...\n**method = digit-sum carries**\nanswer = 1"
    assert perturb.method_label(text) == "digit-sum carries"
    assert perturb.method_label("answer = 1") is None
