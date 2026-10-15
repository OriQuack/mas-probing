"""Offline behavioral contracts for instruction selection and experiment lifecycle."""
import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import Raw, ScriptedLLM
from minpilot.llm.client import LLMClient
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import Limits, Trace
from perturbation_consistency import instruction_selection as ins, segment
from perturbation_consistency.longcot_nodes import parse_chain

PROMPT = """Problem node_0: What is 3?
Problem node_1: Compute [For this value use the answer from problem node_0 and add 1] squared.
Problem node_2: Compute [For this value use the answer from problem node_1 and subtract 6] plus 1.
Problem node_3: Compute [For this value use the answer from problem node_2 and add 0] times 2.
What are the answers to problem node_1, node_2, and node_3?
"""
GOLD = {"node_1": "16", "node_2": "11", "node_3": "22"}
INSTRUCTIONS = {"analogical": "Recall and solve three analogues, then apply the principles.",
                "clarify": "Restate conditions and goals before solving.",
                "local_check": "Check each value independently before passing it on."}


def records(patterns):
    return [{"worker": w, "sample": k, "answer": a, "status": "ok" if a is not None else "error"}
            for w, aa in zip(ins.WORKERS, patterns) for k, a in enumerate(aa)]


def fixture_chain():
    c = parse_chain("linear_easy_1", PROMPT)
    return c, segment.segment_target(c, "easy")


def test_agreement_separates_modal_support_from_cross_worker_support():
    concentrated = ins.agreement(records([["1"] * 3, ["1"] * 3, ["2"] * 3]))
    distributed = ins.agreement(records([["1", "1", "2"]] * 3))
    assert concentrated["agreement"] == distributed["agreement"] == 6 / 9
    assert concentrated["cross_worker_agreement"] == 9 / 27
    assert distributed["cross_worker_agreement"] == 15 / 27
    rs = records([["1", "1.0", None], [None] * 3, [None] * 3])
    assert ins.agreement(rs)["support"] == 2
    assert ins.agreement(rs[:2])["agreement"] == 2 / 9
    assert ins.agreement(records([[None] * 3] * 3))["agreement"] == 0
    with pytest.raises(ValueError, match="duplicate"):
        ins.agreement(rs + rs[:1])


def test_start_is_pooled_nine_modal_even_when_executor_disagrees():
    rs = records([["16", "17", "16.0"], ["99"] * 3, ["99"] * 3])
    assert ins.start_answer(rs) == {"answer": "99", "support": 6, "of": 9, "tied": False}
    assert ins.start_answer(list(reversed(rs))) == ins.start_answer(rs)
    assert ins.start_answer(records([["16"] * 3, ["17"] * 3, [None] * 3])) == {
        "answer": "16", "support": 3, "of": 9, "tied": True}
    assert ins.start_answer(records([[None] * 3] * 3)) == {
        "answer": None, "support": 0, "of": 9, "tied": False}


def test_selection_seed_and_order_independence():
    scores = {c: {"agreement": 2 / 3, "cross_worker_agreement": 1 / 3} for c in ins.CANDIDATES}
    a = ins.select("q:node_1", scores)
    assert a == ins.select("q:node_1", dict(reversed(list(scores.items()))))
    assert len(a["tied_candidates"]) == 4
    scores["clarify"]["agreement"] = 1
    assert ins.select("q:node_1", scores)["candidate"] == "clarify"


def test_generation_contract_and_solver_format(tmp_path):
    c, t = fixture_chain()
    llm = ScriptedLLM({"worker": [INSTRUCTIONS]})
    out = ins.generate(LLMClient(get_spec(ins.GENERATOR), Trace(tmp_path), transport=llm), PROMPT)
    assert out == {"naive": "", **INSTRUCTIONS}
    assert PROMPT in llm.bodies[0]["messages"][0]["content"]
    for instruction in out.values():
        prompt = ins.segment_prompt(c, t, instruction)
        assert segment.segment_text(c, t.nodes) in prompt
        assert prompt.endswith(segment.format_request(list(t.nodes)))
    with pytest.raises(ValueError):
        ins.validate_candidates({**INSTRUCTIONS, "clarify": "word " * 181})
    with pytest.raises(ValueError):
        ins.validate_candidates({**INSTRUCTIONS, "clarify": INSTRUCTIONS["analogical"]})
    naive = ins.continuation_prompt(c.node("node_2"), {"node_1": "16"}, "")
    assert "step by step" not in naive
    assert "- node_1: 16" in naive


def test_continuation_instruction_persists_and_gold_stays_out(tmp_path):
    c, t = fixture_chain()
    llm = ScriptedLLM({"worker": ["answer = 11", "answer = 99"]})
    trace = Trace(tmp_path)
    instruction = INSTRUCTIONS["local_check"]
    rec = ins.continue_chain(LLMClient(get_spec(ins.EXECUTOR), trace, transport=llm), trace, c, t, "16", GOLD, instruction)
    assert rec["status"] == "wrong_at_node_3"
    assert rec["requested_correct"] == 2
    for body in llm.bodies:
        prompt = body["messages"][0]["content"]
        assert instruction in prompt and "22" not in prompt
    assert "- node_1: 16" in llm.bodies[0]["messages"][0]["content"]
    assert "- node_2: 11" in llm.bodies[1]["messages"][0]["content"]
    llm = ScriptedLLM({"worker": []})
    assert ins.continue_chain(LLMClient(get_spec(ins.EXECUTOR), trace, transport=llm), trace, c, t,
                              "0", GOLD, instruction)["requested_correct"] == 0
    assert not llm.bodies


def test_truncation_and_budget_are_failures(tmp_path):
    llm = ScriptedLLM({"worker": [Raw("answer = 16", "length")]})
    assert ins.solve_segment(LLMClient(get_spec(ins.EXECUTOR), Trace(tmp_path), transport=llm), "q", "node_1")["answer"] is None
    trace = Trace(tmp_path / "budget", Limits(max_cost_usd=0))
    llm = ScriptedLLM({"worker": []})
    assert ins.solve_segment(LLMClient(get_spec(ins.EXECUTOR), trace, transport=llm), "q", "node_1")["status"] == "budget"
    assert not llm.bodies


def test_analysis_oracle_is_one_candidate_per_task_and_missing_is_zero():
    targets = [{"target_id": "q", "requested_after": ["node_1", "node_2"]}]
    selections = [{"target_id": "q", "primary": {"candidate": "naive", "tied_candidates": ["naive"]},
                   "cross": {"candidate": "naive"}}]
    runs = [{"target_id": "q", "candidate": "naive", "rep": 0,
             "requested": {"node_1": "correct", "node_2": "wrong"}},
            {"target_id": "q", "candidate": "analogical", "rep": 0,
             "requested": {"node_1": "wrong", "node_2": "correct"}}]
    out = ins.analyze(targets, selections, runs, reps=1)
    assert out["selection"]["requested_share"]["best_in_hindsight"]["mean"] == .5
    assert out["selection"]["requested_share"]["random"]["mean"] == .25
    assert out["selection"]["requested_share"]["clarify"]["mean"] == 0
    assert out["node_order"]["best_in_hindsight"][1]["accuracy"] == 0
    with pytest.raises(ValueError, match="duplicate"):
        ins.analyze(targets, selections, runs + runs[:1], reps=1)


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[1] / "scripts/run_instruction_selection.py"
    spec = importlib.util.spec_from_file_location("instruction_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("generation_mode", ["model", "session"])
def test_full_lifecycle_offline_resume_and_freeze(tmp_path, monkeypatch, runner, generation_mode):
    c, t = fixture_chain()
    source = tmp_path / "source"
    source.mkdir()
    (source / "targets.jsonl").write_text(json.dumps(t.__dict__) + "\n")
    (source / "manifest.json").write_text(json.dumps({"dataset": {"name": "LongCoT", "domain": "math", "revision": "test"}}))
    monkeypatch.setattr(runner.longcot, "load_questions", lambda *a, **kw: [SimpleNamespace(question_id=c.question_id, prompt=PROMPT)])
    def forbidden(*a, **kw):
        raise AssertionError("gold loaded before continuation")
    monkeypatch.setattr(runner.longcot, "load_references", forbidden)
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fake")
    args = argparse.Namespace(experiment=tmp_path / "experiment", source=source, dry_run=True, batch=False,
                              env_file=tmp_path / "absent.env", session_cost_usd=100., run_cost_usd=2., concurrency=1,
                              generation_mode=generation_mode)
    runner.prepare(args)
    assert not args.experiment.exists()
    args.dry_run = False
    runner.prepare(args)
    manifest, targets, inputs, chains = runner.load(args.experiment)
    generation = ScriptedLLM({"worker": [INSTRUCTIONS]})
    monkeypatch.setattr(runner, "http_transport", lambda key: generation)
    if generation_mode == "model":
        runner.generate(args, manifest, targets, inputs, chains)
    else:
        args.candidate_file = tmp_path / "reviewed.jsonl"
        args.author = "Offline test author"
        args.candidate_file.write_text(json.dumps({"target_id": t.target_id, "instructions": INSTRUCTIONS,
                                      "review": {"accepted": True, "notes": "Question-only self review."}}) + "\n")
        runner.import_candidates(args, manifest, targets, chains)
        assert not generation.bodies
    manifest, targets, inputs, chains = runner.load(args.experiment)
    assert manifest["frozen"]
    if generation_mode == "session":
        assert manifest["generator"] is None
        assert ins.GENERATOR not in manifest["models"]
        assert manifest["candidate_authoring"]["separate_model_api_cost_usd"] == 0
    assert len(runner.read_rows(args.experiment / "prompts.jsonl")) == 12
    assert len((args.experiment / "planned.csv").read_text().splitlines()) == 49
    probes = ScriptedLLM({"worker": lambda body: "node_0 = 3\nnode_1 = 16\nanswer = 16"})
    monkeypatch.setattr(runner, "http_transport", lambda key: probes)
    runner.probe(args, manifest)
    assert len(probes.bodies) == 36
    runner.probe(args, manifest)
    assert len(probes.bodies) == 36
    selected = runner.selections(args, manifest, targets)
    assert len(selected[0]["primary"]["tied_candidates"]) == 4
    assert all(s["of"] == 9 and s["support"] == 9 for s in selected[0]["starts"].values())
    monkeypatch.setattr(runner.longcot, "load_references", lambda *a, **kw: {c.question_id: SimpleNamespace(answer="16,11,22")})
    continuation = ScriptedLLM({"worker": lambda body: "answer = 11" if "Problem node_2:" in body["messages"][0]["content"] else "answer = 22"})
    monkeypatch.setattr(runner, "http_transport", lambda key: continuation)
    runner.continuation(args, manifest, targets, chains)
    assert len(continuation.bodies) == 24
    runner.continuation(args, manifest, targets, chains)
    assert len(continuation.bodies) == 24
    out = ins.analyze(targets, selected, runner.read_rows(args.experiment / "continuation.jsonl"))
    assert out["recorded_rollouts"] == 12
    assert out["selection"]["requested_share"]["selected"]["mean"] == 1
    runner.analyze(args, manifest, targets)
    saved = json.loads((args.experiment / "analysis/summary.json").read_text())
    assert saved["missing_rollouts"] == saved["probes_missing"] == 0
    assert saved["per_task"][t.target_id]["naive"]["segment_correct"] == 1
    assert (args.experiment / "analysis/node_order_accuracy.png").stat().st_size > 0
    (args.experiment / "prompts.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="frozen artifact"):
        runner.load(args.experiment)


def test_shared_budget_reservation_and_resume(tmp_path, monkeypatch, runner):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fake")
    monkeypatch.setattr(runner, "http_transport", lambda key: ScriptedLLM({"worker": []}))
    args = argparse.Namespace(experiment=tmp_path, session_cost_usd=.2, run_cost_usd=1.,
                              env_file=tmp_path / "absent.env", batch=False)
    stage = runner.Stage(args, "probe", ins.WORKERS)
    _, a = stage.client("a", ins.EXECUTOR)
    _, b = stage.client("b", ins.EXECUTOR)
    a.before_llm(.15)
    from minpilot.runtime.trace import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        b.before_llm(.15)
    a.settle_llm(.15, .1)
    a.llm({"status": "ok", "usage": {"cost": .1}})
    stage.close()
    resumed = runner.Stage(args, "probe", ins.WORKERS)
    assert resumed.session.run_scope.cost_usd == .1
    _, trace = resumed.client("c", ins.EXECUTOR)
    with pytest.raises(BudgetExceeded):
        trace.before_llm(.15)
    resumed.close()


def test_unknown_billing_stays_reserved_and_interrupted_requests_count_on_resume(tmp_path, runner):
    session = Trace(None, Limits(max_cost_usd=.2))
    trace = runner.StageTrace(tmp_path, 1., session)
    trace.before_llm(.15)
    trace.llm({"call_id": 1, "status": "started", "reserve_usd": .15})
    trace.settle_llm(.15, 0, unknown=True)
    trace.llm({"call_id": 1, "status": "error", "transient": True})
    other = runner.StageTrace(tmp_path / "other", 1., session)
    from minpilot.runtime.trace import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        other.before_llm(.1)
    trace.llm({"call_id": 2, "status": "started", "reserve_usd": .1})
    assert runner.trace_costs(tmp_path) == {"recorded_request_cost": 0., "unknown_cost_calls": 2,
                                         "unknown_reserved_usd": .25}


def test_missing_slots_and_modified_probe_results_cannot_change_selection(tmp_path, runner):
    args = argparse.Namespace(experiment=tmp_path)
    targets = [{"target_id": "q"}]
    with pytest.raises(ValueError, match="finish probe"):
        runner.selections(args, {"seed": 0}, targets)
    rs = [{"target_id": "q", "condition": c, **r} for c in ins.CANDIDATES
          for r in records([["16"] * 3] * 3)]
    path = tmp_path / "results.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rs))
    first = runner.selections(args, {"seed": 0}, targets)
    assert runner.selections(args, {"seed": 0}, targets) == first
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="changed after selection"):
        runner.selections(args, {"seed": 0}, targets)


def test_generation_failure_keeps_planned_slots(tmp_path, runner):
    c, t = fixture_chain()
    target = {**t.__dict__, "requested_after": ["node_1", "node_2", "node_3"]}
    runner.append(tmp_path / "candidates.jsonl", {"target_id": t.target_id, "status": "generation_failed",
                                                "instructions": {"naive": ""}})
    manifest = {"frozen": False}
    runner.freeze(tmp_path, manifest, [target], {t.target_id: c})
    prompts = runner.read_rows(tmp_path / "prompts.jsonl")
    assert len(prompts) == 12
    assert sum(p["prompt"] is None for p in prompts) == 9
    assert len((tmp_path / "planned.csv").read_text().splitlines()) == 49


def test_generation_budget_interruption_leaves_target_pending(tmp_path, monkeypatch, runner):
    c, t = fixture_chain()
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fake")
    fake = ScriptedLLM({"worker": []})
    monkeypatch.setattr(runner, "http_transport", lambda key: fake)
    args = argparse.Namespace(experiment=tmp_path, session_cost_usd=1e-12, run_cost_usd=1.,
                              env_file=tmp_path / "absent.env", batch=False)
    runner.generate(args, {"frozen": False}, [t.__dict__], {t.target_id: {"prompt": PROMPT}}, {t.target_id: c})
    assert not fake.bodies
    assert not (tmp_path / "candidates.jsonl").exists()
    assert not (tmp_path / "generation_attempts.jsonl").exists()


def test_batch_stage_uses_existing_dispatcher_transport(tmp_path, monkeypatch, runner):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fake")
    dispatched = []
    class FakeDispatcher:
        def __init__(self, http, log_path, specs, **kwargs):
            assert set(specs) == set(ins.WORKERS)
            self.transport = ScriptedLLM({"worker": ["answer = 16"]})
            self.closed = False
            dispatched.append(self)
        def close(self):
            self.closed = True
    monkeypatch.setattr(runner, "BatchDispatcher", FakeDispatcher)
    def forbidden_sync(key):
        def fail(*args):
            raise AssertionError("sync transport used in batch mode")
        return fail
    monkeypatch.setattr(runner, "http_transport", forbidden_sync)
    args = argparse.Namespace(experiment=tmp_path, session_cost_usd=1., run_cost_usd=.2,
                              env_file=tmp_path / "absent.env", batch=True)
    stage = runner.Stage(args, "probe", ins.WORKERS)
    client, trace = stage.client("batch-test", ins.EXECUTOR)
    assert ins.solve_segment(client, "Solve this problem.", "node_1")["answer"] == "16"
    stage.close()
    assert dispatched[0].closed
    assert runner.read_rows(tmp_path / "probe_jobs.jsonl")[0]["transport"] == "batch"
