"""perturbation_consistency: LongCoT node parsing, answer grouping, worker choice and the two arms (scripted models)."""

from __future__ import annotations

import json
import re
import threading
import time

import pytest

from fakes import Raw, ScriptedLLM
from minpilot.llm.client import LLMClient, TransientError
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import Limits, Trace
from perturbation_consistency import longcot_math
from perturbation_consistency.batch import BatchDispatcher
from perturbation_consistency.longcot_nodes import VARIANTS, extract_answer, node_prompt, parse_chain
from perturbation_consistency.runner import Settings, probe_limit, run_pipeline, run_routed

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


@pytest.mark.parametrize("tail,value", [  # luna-high response endings that the line pattern missed
    ("Thus\n\\[\n\\boxed{\\text{answer}=\\frac{13}{3}}\n\\]", "\\frac{13}{3}"),
    ("column.\n\n\\[\n\\boxed{\\text{answer = 14}}\n\\]", "14"),
    ("\\[\n\\boxed{\\text{answer}=\\{-\\sqrt{86},\\sqrt{71}\\}}\n\\]", "\\{-\\sqrt{86},\\sqrt{71}\\}"),
    ("\\[\n\\boxed{\\displaystyle \\text{answer}=\\sum_{k=0}^{3}k}\n\\]", "\\sum_{k=0}^{3}k"),
    ("answer = 2 at first\n\\boxed{\\text{answer = 3}}", "3"),
    ("\\boxed{\\text{answer = 3}}\nOn reflection:\nanswer = 5", "5"),
    # hard-batch endings: answer mid-line, trailing markdown/period, display-math wrapper around \text{answer}
    ("Both conditions force the first guess to be \\(859\\).answer = 859", "859"),
    ("Assuming the vertices are distinct (labeled), **answer = 30016**.", "30016"),
    ("## Final answer\n\n$$\\text{answer} = 738$$", "738"),
    ("The answer to node_18 is 5, which is irrational.", None),
])
def test_extract_answer_reads_boxed_text_answers(tail, value):
    assert extract_answer(tail) == value


@pytest.mark.parametrize("gold,predicted", [
    ("52", "\\(52\\)"), ("52", "**52**"), ("52", "$52$"), ("52", "\\boxed{52}"), ("13", "13."),
    ("8/9", "\\dfrac{8}{9}"), ("20/13", "\\tfrac{20}{13}"), ("4056195/4", "\\(\\frac{4\\,056\\,195}{4}\\)"),
    ("12-4\\sqrt{2}", "\\(12-4\\sqrt2\\)"), ("4p(p-1)", "\\(4p(p-1)\\)"),
])
def test_notation_does_not_change_the_value(gold, predicted):
    assert longcot_math.compare(gold, predicted) == "match"
    assert extract_answer(f"work\nanswer = {predicted}") is not None


def test_a_parser_crash_counts_as_not_equal():
    # a real luna-high node_0 answer that made sympy's tokenizer raise IndexError (linear_easy_15)
    weird = ("\\(c_{2020}(0)+2c_{2020}(1)+\\displaystyle\\sum_{r=1}^{2020}\\bigl(2^{r-1}+c_{r-1}(0)\\bigr)\\), where "
             "\\(c_m(d)=\\displaystyle\\sum_{i=0}^{\\lfloor(m-d)/2\\rfloor}\\frac{m!}{(i+d)!i!(m-2i-d)!}\\)")
    assert longcot_math.compare("3^{2021}-2^{2021}", weird) in ("unresolved", "mismatch", "textual")
    assert longcot_math.group(["3^{2021}-2^{2021}", weird, "3^{2021}-2^{2021}"]) == [[0, 2], [1]]


def test_grouping_uses_longcot_equivalence():
    assert longcot_math.group(["0.5", "1/2", "3", None, "\\frac{1}{2}"]) == [[0, 1, 4], [2], [3]]
    assert longcot_math.compare_answer_lists(["16", "1/2"], ["16", "0.5"]) == "match"
    assert longcot_math.compare_answer_lists("16, 3", ["16", "4"]) != "match"
    assert longcot_math.compare_answer_lists(["16"], [None]) == "mismatch"


@pytest.mark.parametrize("a,b", [  # same value, different notation (recorded answers and gold strings)
    ("3\\sqrt{21}", "3√21"),
    ("3*sqrt(21)", "3\\sqrt{21}"),
    ("\\log\\frac{2007}{2006}", "\\ln\\left(\\frac{2007}{2006}\\right)"),
    ("\\log\\frac{2007}{2006}", "log(2007/2006)"),
    ("\\log_2(2015)-1", "\\log_2\\left(\\frac{2015}{2}\\right)"),
    ("\\log_2 8", "3"),
    ("\\sqrt[3]{8}", "2"),
    ("\\frac{\\sqrt{3}}{2}", "\\sin(\\pi/3)"),
    ("48+sqrt(2016)", "48 + 12\\sqrt{14}"),
    ("\\frac{2\\sqrt{170}-9\\sqrt{5}}{5}", "\\frac{2\\sqrt{34}-9}{\\sqrt{5}}"),
    ("2/3 + 1/(3*4^2013)", "\\displaystyle \\frac{2\\cdot4^{2013}+1}{3\\cdot4^{2013}}"),
    ("3", "\\{3\\}"),
    ("12,345", "12345"),
    ("\\{(2025, 36), (4489, 2500)\\}", "(S₁, S₂) ∈ {(4489, 2500), (2025, 36)}"),
])
def test_equivalent_notation_matches(a, b):
    assert longcot_math.compare(a, b) == "match" and longcot_math.compare(b, a) == "match"


@pytest.mark.parametrize("a,b", [  # different values, some differing only far below float precision
    ("3\\sqrt{21}", "3\\sqrt{22}"),
    ("3^2021 - 2^2021", "3^{2021} - 2^{2021} - 1"),
    ("2/3 + 1/(3*4^2013)", "2/3"),
    ("(2^{2019} - 1)^{2018}", "3"),
    ("3^{2014}/(2^{2014}*2014!)", "0"),
    ("1/3", "0.333333333333"),
    ("\\{1, 2\\}", "\\{1, 3\\}"),
    ("(1, 2)", "(2, 1)"),
    ("\\log\\frac{2007}{2006}", "\\log\\frac{2008}{2007}"),
])
def test_different_values_do_not_match(a, b):
    assert longcot_math.compare(a, b) != "match" and longcot_math.compare(b, a) != "match"


LUNA, HAIKU, GEMINI = (get_spec(k).model for k in ("luna-high", "haiku-high", "gemini"))
TRUE = {"node_0": "84", "node_1": "35", "node_2": "-1", "node_3": "0"}


def node_of(body):
    return re.search(r"Problem (node_\d+):", body["messages"][-1]["content"]).group(1)


def variant_of(body):
    text = body["messages"][-1]["content"]
    return next(v for v, t in enumerate(VARIANTS) if text.startswith(t.split("{body}")[0]))


def script(haiku=None):
    """luna always right; haiku right except where `haiku[(node, variant)]` says otherwise; gemini cut off."""
    haiku = haiku or {}
    return ScriptedLLM({
        f"worker:{LUNA}": lambda b: f"reasoning\nanswer = {TRUE[node_of(b)]}",
        f"worker:{HAIKU}": lambda b: f"answer = {haiku.get((node_of(b), variant_of(b)), TRUE[node_of(b)])}",
        f"worker:{GEMINI}": lambda b: Raw("thinking...", "length"),
    })


def settings(llm, **kw):
    return Settings(workers=("luna-high", "haiku-high", "gemini"), n_variants=5, fixed_reps=1,
                    client=lambda key, trace: LLMClient(get_spec(key), trace, transport=llm, sleep=lambda s: None),
                    **kw)


def test_routed_arm_picks_the_consistent_worker_and_continues_from_its_modal_answer(tmp_path):
    llm = script({("node_0", 1): "48", ("node_0", 3): "12"})
    chain = parse_chain("q1", PROMPT)
    res = run_routed(chain, tmp_path, settings(llm))
    assert res["choice"]["consistency"] == {"luna-high": 1.0, "haiku-high": 0.6, "gemini": 0.0}
    assert res["choice"]["chosen"] == "luna-high" and res["choice"]["given"] == {"node_0": "84"}
    assert res["choice"]["probed_nodes"] == 1
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


def test_a_tie_is_probed_on_the_next_node_by_the_tied_workers_only(tmp_path):
    llm = script({("node_1", 2): "9", ("node_1", 4): "9"})  # haiku and luna tie on node_0; luna wins node_1
    chain = parse_chain("q1", PROMPT)
    res = run_routed(chain, tmp_path, settings(llm, probe_depth=3))
    choice = res["choice"]
    assert [r["node"] for r in choice["rounds"]] == ["node_0", "node_1"]
    assert choice["rounds"][0]["kept"] == ["luna-high", "haiku-high"]
    assert choice["rounds"][1]["consistency"] == {"luna-high": 1.0, "haiku-high": 0.6}
    assert choice["chosen"] == "luna-high" and choice["tied"] == ["luna-high"]
    assert choice["given"] == {"node_0": "84", "node_1": "35"} and choice["path_variant"] == 0
    assert not any(b["model"] == GEMINI and node_of(b) == "node_1" for b in llm.bodies)
    assert [n["node"] for n in res["routed"]["nodes"]] == ["node_2", "node_3"]
    haiku = json.loads((tmp_path / "consistency_probe_haiku-high" / "record.json").read_text())
    assert [r["node"] for r in haiku["rounds"]] == ["node_0", "node_1"] and haiku["consistency"] == 1.0


def test_a_tie_left_after_the_last_probed_node_is_broken_by_a_seed(tmp_path):
    chain = parse_chain("q1", PROMPT)
    res = run_routed(chain, tmp_path / "a", settings(script(), probe_depth=2))
    again = run_routed(chain, tmp_path / "b", settings(script(), probe_depth=2))
    assert res["choice"]["tied"] == ["haiku-high", "luna-high"] and res["choice"]["probed_nodes"] == 2
    assert res["choice"]["chosen"] == again["choice"]["chosen"]
    assert res["choice"]["given"] == {"node_0": "84", "node_1": "35"}


def test_the_probe_limit_is_a_share_of_the_chain_nodes(tmp_path):
    chain = parse_chain("q1", PROMPT)  # 4 nodes
    assert [probe_limit(chain, Settings(workers=(), probe_fraction=f)) for f in (0.2, 0.5, 1.0)] == [1, 2, 4]
    assert probe_limit(chain, Settings(workers=(), probe_depth=3)) == 3
    res = run_routed(chain, tmp_path, settings(script(), probe_fraction=0.5))  # luna and haiku stay tied
    assert res["choice"]["probe_limit"] == 2 and res["choice"]["probed_nodes"] == 2
    assert len(res["choice"]["tied"]) == 2


def test_real_chain_probe_limits_at_twenty_percent():
    from minpilot.data import longcot
    if not (longcot.LONGCOT_ROOT / "math" / "hard.json").exists():
        pytest.skip("LongCoT data not downloaded")
    s = Settings(workers=(), probe_fraction=0.2)
    limits = {d: {probe_limit(parse_chain(q.question_id, q.prompt), s)
                  for q in longcot.load_questions("math", d, template="linear")} for d in ("easy", "medium", "hard")}
    assert limits == {"easy": {3}, "medium": {7}, "hard": {10}}


def test_a_stopped_variant_chain_counts_as_no_answer_on_later_nodes(tmp_path):
    llm = ScriptedLLM({
        f"worker:{LUNA}": lambda b: Raw("...", "length") if node_of(b) == "node_0" and variant_of(b) == 0
        else f"answer = {TRUE[node_of(b)]}",
        f"worker:{HAIKU}": lambda b: Raw("...", "length") if node_of(b) == "node_0" and variant_of(b) == 1
        else f"answer = {TRUE[node_of(b)]}",
        f"worker:{GEMINI}": lambda b: Raw("thinking...", "length"),
    })
    res = run_routed(parse_chain("q1", PROMPT), tmp_path, settings(llm, probe_depth=2))
    luna = json.loads((tmp_path / "consistency_probe_luna-high" / "record.json").read_text())
    assert luna["rounds"][1]["samples"][0]["status"] == "chain_stopped"
    assert luna["rounds"][1]["consistency"] == 0.8 and res["choice"]["tied"] == ["haiku-high", "luna-high"]
    assert res["choice"]["path_variant"] == (1 if res["choice"]["chosen"] == "luna-high" else 0)


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


class FakeBatchAPI:
    """OpenRouter Batch API stand-in: each POSTed batch completes on its `delay`-th poll, every request answered by
    `llm`. `bare` drops `usage.cost` and `provider` from result bodies (the batch docs do not promise them);
    `fail` makes every request an error; the first `provider_failures` batches end as `failed` without results."""

    def __init__(self, llm, delay: int = 1, bare: bool = False, fail: bool = False, provider_failures: int = 0):
        self.llm, self.delay, self.bare, self.fail = llm, delay, bare, fail
        self.provider_failures = provider_failures
        self.batches: dict[str, dict] = {}
        self.payloads: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, method, path, body):
        with self.lock:
            if method == "POST":
                self.payloads.append(body)
                bid = f"batch_{len(self.batches)}"
                self.batches[bid] = {"payload": body, "polls": 0}
                return 202, {"id": bid, "status": "validating"}
            b = self.batches[path.rsplit("/", 1)[1]]
            b["polls"] += 1
            if b["polls"] < self.delay:
                return 200, {"status": "in_progress", "results": None}
            if self.provider_failures and not b.get("failed_once"):
                self.provider_failures -= 1
                b["failed_once"] = True
                return 200, {"status": "failed", "usage": {}, "results": None,
                             "error": {"message": "The provider ended this batch without producing results."}}
        p, results = b["payload"], []
        for r in p["requests"]:
            if self.fail:
                results.append({"custom_id": r["custom_id"], "response": None,
                                "error": {"code": 400, "message": "bad request"}})
                continue
            out = self.llm({**r["body"], "model": p["model"], "provider": p["provider"]}, None)
            if self.bare:
                out.pop("provider")
                out["usage"].pop("cost")
            results.append({"custom_id": r["custom_id"], "response": {"status_code": 200, "body": out}, "error": None})
        return 200, {"status": "completed", "request_counts": {"total": len(results)},
                     "usage": {"cost": 0.01 * len(results)}, "results": results}


def dispatcher(api, tmp_path, **kw):
    specs = {k: get_spec(k) for k in ("luna-high", "haiku-high", "gemini", "flash-medium")}
    return BatchDispatcher(api, tmp_path / "batches.jsonl", specs, quiet_s=0.05, poll_s=0.0, resubmit_delay_s=0.0,
                           sleep=lambda s: time.sleep(0.005), **kw)


def test_a_batch_the_provider_drops_is_resubmitted(tmp_path):
    api = FakeBatchAPI(ScriptedLLM({"worker": lambda b: "answer = 1"}), provider_failures=2)
    d = dispatcher(api, tmp_path)
    try:
        client = LLMClient(get_spec("flash-medium"), Trace(tmp_path / "t", Limits()), transport=d.transport,
                           sleep=lambda s: None)
        res = client.chat([{"role": "user", "content": "hi"}])
    finally:
        d.close()
    assert res.content == "answer = 1" and len(api.payloads) == 3
    log = [json.loads(x) for x in (tmp_path / "batches.jsonl").read_text().splitlines()]
    assert [x["resubmits"] for x in log if x["event"] == "resubmit"] == [1, 2]


def test_resubmits_are_capped_then_the_call_fails_as_transient(tmp_path):
    api = FakeBatchAPI(ScriptedLLM({"worker": lambda b: "answer = 1"}), provider_failures=10)
    d = dispatcher(api, tmp_path, max_resubmits=1)
    try:
        with pytest.raises(TransientError, match="after 1 resubmits"):
            d.transport({"model": get_spec("flash-medium").model, "messages": []}, None)
    finally:
        d.close()
    assert len(api.payloads) == 2


def batch_client(d):
    return lambda key, trace: LLMClient(get_spec(key), trace, transport=d.transport, sleep=lambda s: None)


def test_batch_transport_pools_calls_per_model_and_maps_results_back(tmp_path):
    api = FakeBatchAPI(script(), delay=2)
    d = dispatcher(api, tmp_path)
    try:
        s = settings(None)
        s.client = batch_client(d)
        res = run_routed(parse_chain("q1", PROMPT), tmp_path / "run", s)
    finally:
        d.close()
    assert res["choice"]["consistency"] == {"luna-high": 1.0, "haiku-high": 1.0, "gemini": 0.0}
    assert res["routed"]["status"] == "ok" and res["routed"]["final"] == {"node_3": "0", "node_1": "35"}
    first = api.payloads[0]
    assert list(first) == ["endpoint", "model", "provider", "completion_window", "requests"]
    assert first["provider"]["allow_fallbacks"] is False and len(first["provider"]["only"]) == 1
    assert all("model" not in r["body"] and "provider" not in r["body"] for p in api.payloads for r in p["requests"])
    assert sorted(len(p["requests"]) for p in api.payloads[:3]) == [5, 5, 5]  # node_0: a batch per worker
    log = [json.loads(x) for x in (tmp_path / "batches.jsonl").read_text().splitlines()]
    assert {x["event"] for x in log} == {"submitted", "finished"} and "Bearer" not in json.dumps(log)
    assert d.charged_usd == pytest.approx(0.01 * sum(len(p["requests"]) for p in api.payloads))


def test_batch_results_without_cost_or_provider_are_filled_and_flagged(tmp_path):
    api = FakeBatchAPI(ScriptedLLM({"worker": lambda b: "answer = 1"}), bare=True)
    d = dispatcher(api, tmp_path)
    spec = get_spec("flash-medium")
    try:
        client = LLMClient(spec, Trace(tmp_path / "t", Limits()), transport=d.transport, sleep=lambda s: None)
        res = client.chat([{"role": "user", "content": "hi"}])
    finally:
        d.close()
    assert res.content == "answer = 1" and res.usage["cost_estimated"] is True
    assert res.usage["cost"] == pytest.approx(0.5 * (10 * spec.price_prompt + 5 * spec.price_completion))
    assert api.payloads[0]["provider"] == {"only": ["google-vertex"], "allow_fallbacks": False}
    assert d.estimated_usd == pytest.approx(res.usage["cost"])


def test_a_failed_batch_request_stops_the_pipeline_like_an_api_error(tmp_path):
    d = dispatcher(FakeBatchAPI(ScriptedLLM({"worker": lambda b: "answer = 1"}), fail=True), tmp_path)
    try:
        rec = run_pipeline(parse_chain("q1", PROMPT), "luna-high", tmp_path / "p",
                           Settings(workers=("luna-high",), client=batch_client(d)), arm="fixed_luna-high", rep=0)
    finally:
        d.close()
    assert rec["status"] == "stopped_at_node_0:error" and "400" in rec["nodes"][0]["error"]


def test_google_vertex_responses_named_google_pass_the_provider_check(tmp_path):
    llm = ScriptedLLM({"worker": lambda b: "answer = 1"}, provider="Google")
    res = LLMClient(get_spec("flash-medium"), Trace(tmp_path, Limits()), transport=llm).chat(
        [{"role": "user", "content": "x"}])
    assert res.content == "answer = 1"
