"""perturbation_consistency.segment_routing: probe prompts, the irrelevant sentence and the continuation (scripted)."""

from __future__ import annotations

from fakes import Raw, ScriptedLLM
from minpilot.llm.client import LLMClient
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import Limits, Trace
from perturbation_consistency import segment, segment_routing as sr
from perturbation_consistency.longcot_nodes import parse_chain

PROMPT = """Solve this problem step by step and return the final solution at the end.

Problem node_0: Tom has $3$ apples. How many apples does Tom have?
Problem node_1: Compute [For this value use the answer from problem node_0 and add 1] squared.
Problem node_2: Compute [For this value use the answer from problem node_1 and subtract 6] plus 1.
Problem node_3: Compute [For this value use the answer from problem node_2 and add 0] times 2.
Problem node_4: Compute [For this value use the answer from problem node_3 and add 0] plus 3.
What are the answers to problem node_4, node_2, and node_3?
Return the answers as a single comma-separated list in the format: solution = [answer for node_4, answer for node_2, answer for node_3].
"""
GOLD = {"node_2": "11", "node_3": "22", "node_4": "25"}


def chain():
    return parse_chain("linear_hard_98", PROMPT)


def client(tmp_path, llm, key="haiku-medium"):
    return LLMClient(get_spec(key), Trace(tmp_path, Limits()), transport=llm)


def test_the_segment_cap_depends_on_the_difficulty():
    assert sr.segment_target(chain(), "hard").nodes == ("node_0", "node_1", "node_2")
    late = PROMPT.replace("node_4, node_2, and node_3?", "node_4, and node_3?")
    assert sr.segment_target(parse_chain("q", late), "easy").node == "node_3"
    only_last = parse_chain("q", late.replace("node_4, and node_3?", "node_4?"))
    assert sr.segment_target(only_last, "hard").node == "node_4"  # node_k itself is within the cap
    assert segment.segment_target(only_last, "hard", max_last=3) is None


def test_probe_prompts_use_five_samples_per_condition_and_keep_the_problems():
    c, t = chain(), sr.segment_target(chain(), "hard")
    sentence = "Tom's sister has 4 pears."
    items = {"paraphrase": {"ok": True, "text": "Problem node_0: P0\nProblem node_1: P1\nProblem node_2: P2"},
             "irrelevant_context": {"ok": True, "node": "node_0", "sentence": sentence,
                                    "text": f"Tom has $3$ apples. {sentence} How many apples does Tom have?"}}
    rows = sr.build_prompts(c, t, items)
    by = {(r["condition"], r["detail"]): r["prompt"] for r in rows}
    assert [sum(r["condition"] == k for r in rows) for k in sr.CONDITIONS] == [5, 5, 5]
    assert all(r["prompt"].endswith(segment.format_request(list(t.nodes))) for r in rows)
    plain = segment.segment_text(c, t.nodes)
    cot = by[("instruction", "zero_shot_cot")]
    assert cot.index(plain) < cot.index("Let's think step by step.")
    assert by[("surface", "re_read")].count(plain) == 2 and "Read the question again: " in by[("surface", "re_read")]
    fmt = by[("surface", "format_perturbation")]
    assert "PROBLEM [node_1]\nCompute [For this value use the answer from problem node_0 and add 1] squared." in fmt
    perm = by[("surface", "batch_permutation")]
    order = [perm.index(f"Problem {n}:") for n in t.nodes]
    assert sorted(order) != order and all(c.node(n).text in perm for n in t.nodes)
    assert sentence in by[("surface", "irrelevant_context")] and "Problem node_0: P0" in by[("surface", "paraphrase")]
    assert "Problem node_3" not in "".join(r["prompt"] for r in rows)
    fewer = sr.build_prompts(c, t, {"paraphrase": {"ok": False}})
    assert sum(r["condition"] == "surface" for r in fewer) == 3


def test_an_irrelevant_sentence_must_leave_the_problem_unchanged(tmp_path):
    c = chain()
    original = c.node("node_0").text
    good = "Tom's sister has 4 pears."
    assert sr.insertion_problems(original, original.replace("How", f"{good} How"), good) == []
    assert sr.insertion_problems(original, original.replace("$3$", "$5$") + f" {good}", good) == [
        "the rest of the problem changed"]
    assert "mentions a placeholder or a problem label" in sr.insertion_problems(
        original, original + " See node_1.", "See node_1.")

    def reply(body):
        name = body["response_format"]["json_schema"]["name"]
        if name == "irrelevant_context":
            reply.n += 1
            new = original.replace("$3$", "$4$") + f" {good}" if reply.n == 1 else original.replace("How", f"{good} How")
            return {"node": "node_0", "sentence": good, "text": new}
        return {"changes_answer": False, "hints": False, "contradicts": False, "looks_related": True, "reason": "ok"}
    reply.n = 0
    out = sr.irrelevant_context(client(tmp_path, ScriptedLLM({"worker": reply}), "sonnet-high"), c,
                                ("node_0", "node_1", "node_2"))
    assert out["ok"] and out["node"] == "node_0" and len(out["attempts"]) == 2
    assert out["attempts"][0]["problems"] == ["the rest of the problem changed"]
    none = sr.irrelevant_context(client(tmp_path, ScriptedLLM({"worker": reply}), "sonnet-high"), c,
                                 ("node_0", "node_1", "node_2"), tries=0)
    assert not none["ok"] and none["attempts"] == []


def test_the_start_value_is_the_most_frequent_probe_answer():
    assert sr.start_answer(["4", "16", "16", None, "16.0"]) == {"answer": "16", "support": 3, "of": 5, "tied": False}
    assert sr.start_answer(["4", "5"])["tied"] and sr.start_answer([None, None])["answer"] is None


def test_the_continuation_stops_at_the_first_wrong_requested_node_and_never_shows_gold(tmp_path):
    c, t = chain(), sr.segment_target(chain(), "hard")
    llm = ScriptedLLM({"worker": ["work\nanswer = 23", "answer = 99"]})
    rec = sr.continue_chain(client(tmp_path, llm), Trace(tmp_path, Limits()), c, t, "11", GOLD)
    assert rec["status"] == "wrong_at_node_3" and [x["node"] for x in rec["calls"]] == ["node_3"]
    assert rec["requested"] == {"node_4": "not_reached", "node_2": "correct", "node_3": "wrong"}
    assert rec["requested_correct"] == 1 and rec["requested_total"] == 3
    prompt = llm.bodies[0]["messages"][0]["content"]
    assert "- node_2: 11" in prompt and "22" not in prompt and "25" not in prompt

    llm = ScriptedLLM({"worker": ["answer = 22", "answer = 25"]})
    rec = sr.continue_chain(client(tmp_path, llm), Trace(tmp_path, Limits()), c, t, "11", GOLD)
    assert rec["status"] == "ok" and rec["requested_correct"] == 3 and len(llm.bodies) == 2


def test_a_wrong_or_missing_segment_answer_makes_no_call(tmp_path):
    c, t = chain(), sr.segment_target(chain(), "hard")
    for start, status in (("12", "wrong_at_node_2"), (None, "no_segment_answer")):
        llm = ScriptedLLM({"worker": []})
        rec = sr.continue_chain(client(tmp_path, llm), Trace(tmp_path, Limits()), c, t, start, GOLD)
        assert rec["status"] == status and rec["requested_correct"] == 0 and llm.bodies == []


def test_a_cut_off_node_stops_the_run(tmp_path):
    c, t = chain(), sr.segment_target(chain(), "hard")
    llm = ScriptedLLM({"worker": [Raw("answer = 22", "length")]})
    rec = sr.continue_chain(client(tmp_path, llm), Trace(tmp_path, Limits()), c, t, "11", GOLD)
    assert rec["status"] == "length_at_node_3" and rec["requested"]["node_3"] == "not_reached"
