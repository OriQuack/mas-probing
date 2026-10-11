"""perturbation_consistency: LongCoT node parsing, answer grouping, worker choice and the two arms (scripted models)."""

from __future__ import annotations

import json
import re

import pytest

from fakes import Raw, ScriptedLLM
from minpilot.llm.client import LLMClient
from minpilot.llm.specs import get_spec
from perturbation_consistency import longcot_math
from perturbation_consistency.longcot_nodes import VARIANTS, extract_answer, node_prompt, parse_chain
from perturbation_consistency.runner import Settings, choose, run_pipeline, run_routed

PROMPT = """Solve this problem step by step and return the final solution at the end.

Problem node_0: What is the integer formed by the rightmost two digits of \\(4^{127}\\)?
Problem node_1: Let $b_{n+2}=[For this value use the answer from problem node_0 and subtract 49] b_{n+1}$. Find $b_3$.
Problem node_2: Find $x$ with $x^[For this value use the numerator of the reduced form of the fraction from problem node_1 and add 2]=1$.
Problem node_3: Compute [For this value use the integer answer from problem node_2 and add 1] squared.
What are the answers to problem node_3, and node_1?
Return the answers as a single comma-separated list in the format: solution = [answer for node_3, answer for node_1].
"""


def test_parse_chain_nodes_dependencies_and_requested_order():
    c = parse_chain("q1", PROMPT)
    assert [n.name for n in c.nodes] == ["node_0", "node_1", "node_2", "node_3"]
    assert [n.deps for n in c.nodes] == [(), ("node_0",), ("node_1",), ("node_2",)]
    assert c.requested == ("node_3", "node_1")
    assert c.nodes[3].text.endswith("squared.") and "What are the answers" not in c.nodes[3].text
    with pytest.raises(ValueError):
        parse_chain("bad", "Problem node_0: x\nProblem node_1: [For this value use problem node_5]\n"
                           "What are the answers to problem node_1?")


def test_variants_keep_the_problem_text_and_give_dependency_values():
    c = parse_chain("q1", PROMPT)
    prompts = [node_prompt(c.nodes[0], {}, v) for v in range(len(VARIANTS))]
    assert len(set(prompts)) == len(VARIANTS)
    assert all(c.nodes[0].text in p and "answer = <exact value>" in p for p in prompts)
    p1 = node_prompt(c.nodes[1], {"node_0": "12"}, 0)
    assert "[For this value use the answer from problem node_0 and subtract 49]" in p1 and "- node_0: 12" in p1
    with pytest.raises(KeyError):
        node_prompt(c.nodes[1], {}, 0)


def test_extract_answer_takes_the_last_answer_line():
    assert extract_answer("work...\nanswer = 3\nmore\nanswer = 1/2") == "1/2"
    assert extract_answer("**answer = 7**") == "7"
    assert extract_answer("Answer = $\\frac{1}{2}$") == "\\frac{1}{2}"
    assert extract_answer("the answer is 4") is None


@pytest.mark.parametrize("gold,predicted", [
    ("52", "\\(52\\)"), ("52", "**52**"), ("52", "$52$"), ("52", "\\boxed{52}"), ("13", "13."),
    ("8/9", "\\dfrac{8}{9}"), ("20/13", "\\tfrac{20}{13}"), ("4056195/4", "\\(\\frac{4\\,056\\,195}{4}\\)"),
    ("12-4\\sqrt{2}", "\\(12-4\\sqrt2\\)"), ("4p(p-1)", "\\(4p(p-1)\\)"),
])
def test_notation_does_not_change_the_value(gold, predicted):
    assert longcot_math.compare(gold, predicted) == "match"
    assert extract_answer(f"work\nanswer = {predicted}") is not None


def test_grouping_uses_longcot_equivalence():
    assert longcot_math.group(["0.5", "1/2", "3", None, "\\frac{1}{2}"]) == [[0, 1, 4], [2], [3]]
    assert longcot_math.compare_answer_lists(["16", "1/2"], ["16", "0.5"]) == "match"
    assert longcot_math.compare_answer_lists("16, 3", ["16", "4"]) != "match"
    assert longcot_math.compare_answer_lists(["16"], [None]) == "mismatch"


def test_choose_breaks_ties_with_a_seed_per_question():
    probes = {w: {"consistency": c, "modal_answer": w} for w, c in (("a", 0.8), ("b", 0.8), ("c", 0.4))}
    first = choose(probes, "q1")
    assert first["tied"] == ["a", "b"] and first["chosen"] in ("a", "b") and choose(probes, "q1") == first
    assert choose({"a": {"consistency": 0.2, "modal_answer": "x"}, "b": {"consistency": 1.0, "modal_answer": "y"}},
                  "q1")["chosen"] == "b"


LUNA, HAIKU, GEMINI = (get_spec(k).model for k in ("luna-high", "haiku-high", "gemini"))
TRUE = {"node_0": "84", "node_1": "35", "node_2": "-1", "node_3": "0"}


def node_of(body):
    return re.search(r"Problem (node_\d+):", body["messages"][-1]["content"]).group(1)


def script():
    haiku_first = iter(["84", "48", "84", "12", "84"])
    return ScriptedLLM({
        f"worker:{LUNA}": lambda b: f"reasoning\nanswer = {TRUE[node_of(b)]}",
        f"worker:{HAIKU}": lambda b: f"answer = {next(haiku_first) if node_of(b) == 'node_0' else TRUE[node_of(b)]}",
        f"worker:{GEMINI}": lambda b: Raw("thinking...", "length"),
    })


def settings(llm, **kw):
    return Settings(workers=("luna-high", "haiku-high", "gemini"), n_variants=5, fixed_reps=1,
                    client=lambda key, trace: LLMClient(get_spec(key), trace, transport=llm, sleep=lambda s: None),
                    **kw)


def test_routed_arm_picks_the_consistent_worker_and_continues_from_its_modal_answer(tmp_path):
    llm = script()
    chain = parse_chain("q1", PROMPT)
    res = run_routed(chain, tmp_path, settings(llm))
    assert res["choice"]["consistency"] == {"luna-high": 1.0, "haiku-high": 0.6, "gemini": 0.0}
    assert res["choice"]["chosen"] == "luna-high" and res["choice"]["modal_answer"] == "84"
    routed = res["routed"]
    assert routed["status"] == "ok" and routed["given"] == {"node_0": "84"}
    assert [n["node"] for n in routed["nodes"]] == ["node_1", "node_2", "node_3"]
    assert routed["final"] == {"node_3": "0", "node_1": "35"}
    probe = json.loads((tmp_path / "consistency_probe_haiku-high" / "record.json").read_text())
    assert [s["variant"] for s in probe["samples"]] == [0, 1, 2, 3, 4] and probe["groups"][0] == ["84", 3]
    luna_bodies = [b for b in llm.bodies if b["model"] == LUNA]
    node1 = next(b for b in luna_bodies if node_of(b) == "node_1")["messages"][-1]["content"]
    assert "- node_0: 84" in node1
    assert (tmp_path / "consistency_routed_r0" / "llm_calls.jsonl").exists()


def test_fixed_pipeline_stops_at_a_node_without_an_answer(tmp_path):
    llm = script()
    chain = parse_chain("q1", PROMPT)
    rec = run_pipeline(chain, "gemini", tmp_path / "g", settings(llm), arm="fixed_gemini", rep=0)
    assert rec["status"] == "stopped_at_node_0:length" and rec["final"] is None and len(rec["nodes"]) == 1
    ok = run_pipeline(chain, "luna-high", tmp_path / "l", settings(llm), arm="fixed_luna-high", rep=0)
    assert ok["status"] == "ok" and ok["final"] == {"node_3": "0", "node_1": "35"} and ok["llm_calls"] == 4
    assert all(n["variant"] == 0 for n in ok["nodes"])


def test_real_linear_chains_parse(tmp_path):
    from minpilot.data import longcot
    if not (longcot.LONGCOT_ROOT / "math" / "easy.json").exists():
        pytest.skip("LongCoT data not downloaded")
    chains = [parse_chain(q.question_id, q.prompt) for q in longcot.load_questions("math", "easy", template="linear")]
    refs = longcot.load_references("math", "easy")  # parser check only: requested nodes line up with the gold list
    assert len(chains) == 23
    for c in chains:
        assert len(c.nodes) == 15 and c.nodes[0].deps == ()
        assert len(c.requested) == len(longcot_math.answer_parts(refs[c.question_id].answer))
        assert all(n.deps == (c.nodes[i].name,) for i, n in enumerate(c.nodes[1:]))
