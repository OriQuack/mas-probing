"""Offline contracts for MoNaCo oracle-setting instruction selection."""
import argparse
import importlib.util
import json
from pathlib import Path

import pytest

from fakes import Raw, ScriptedLLM
from minpilot.data import monaco
from minpilot.llm.client import HTTPError, LLMClient
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import Limits, Trace
from perturbation_consistency import monaco_instruction_selection as mis

INSTRUCTIONS = {"decompose": "Break the question into subquestions and answer them in order.",
                "clarify": "State which entities, attributes and conditions the question covers before answering.",
                "structured": "Write a table with one row per candidate item found in the documents."}
GOLD_SECRET = "Zanzibar-GOLD"


def records(patterns):
    """Probe slots whose answer line joins the given items; [] is "none" and None a failed slot."""
    line = lambda a: "; ".join(map(str, a)) or "none"
    return [{"worker": w, "sample": k, "answer_line": line(a) if a is not None else None,
             "status": "ok" if a is not None else "error", "content": f"Answers: {line(a)}" if a is not None else None}
            for w, aa in zip(mis.WORKERS, patterns) for k, a in enumerate(aa)]


def lines_of(rows):
    """Split stand-in: the items each answer line was built from."""
    return {r["answer_line"]: {"status": "empty", "items": []} if r["answer_line"] == "none" else
            {"status": "answer", "items": r["answer_line"].split("; ")} for r in rows if r["answer_line"]}


def split_by_separator(body):
    """Splitter stand-in: items are the "; "-separated pieces of each line."""
    entries = dict(x.split(": ", 1) for x in body["messages"][0]["content"].split("Lines:\n")[1].splitlines())
    return {"lines": [{"id": i, "status": "empty" if t == "none" else "answer",
                       "items": [] if t == "none" else t.split("; ")} for i, t in entries.items()]}


def group_by_text(body):
    """Clusterer stand-in: each distinct item text is its own group."""
    ids = [line.split(":")[0] for line in body["messages"][0]["content"].split("Items:\n")[1].splitlines()]
    return {"groups": [[i] for i in ids], "no_answer": []}


def test_normalization_keeps_sign_decimal_point_and_inner_punctuation():
    key = mis.answer_key
    assert key(["-3"]) != key(["3"]) and key([-3]) != key([3])
    assert key(["1.5"]) != key(["15"]) and key([1.5]) != key([15])
    assert key(["1.50"]) == key(["1.5"]) == key([1.5])
    assert key(["1,234"]) == key(["1234"]) == key([1234])
    assert key(["45%"]) != key(["45"])
    assert key(["St. Louis"]) != key(["St Louis"]) and key(["U.S."]) != key(["US"])
    assert key(["  New   York "]) == key(["new york"]) and key(["Ｐａｒｉｓ"]) == key(["paris"])
    assert key(["Yes"]) == key([True]) == key(["true"]) and key(["no"]) == key([False])
    assert key(["a", "b"]) == key(["b", "a", "a"])
    assert key([["France", 2]]) == key([["france", "2"]]) != key([["France", 3]])
    assert key([["France"]]) == key(["France"])


def test_answer_line_parsing():
    assert mis.answer_line("reasoning\nAnswers: Aisne, Ardennes") == "Aisne, Ardennes"
    assert mis.answer_line("Answers: x\nmore\n**Answers:** Yes, Scream\nThese are...") == "Yes, Scream"  # the last
    assert mis.answer_line("**Final Answer:**  130,000  troops") == "130,000 troops"
    assert mis.answer_line("Answer: none") == "none" and mis.answer_line("ANSWERS: 4") == "4"
    assert mis.answer_line("Answers:\n- Leni (lover)\n- Frieda\n\nDone.") == "Leni (lover); Frieda"  # a block
    assert mis.answer_line("no answer line") is None and mis.answer_line("Answers:   ") is None
    assert mis.answer_line("The answers are below: a") is None  # the marker opens a line
    assert mis.answer_line(None) is None


def test_split_items_must_be_verbatim_pieces_covering_the_line(tmp_path):
    cover = mis.items_cover
    assert cover("Aisne, Ardennes and Haute-Marne", ["Aisne", "Ardennes", "Haute-Marne"])
    assert cover("Raymond IV of Toulouse (Count); Tancred", ["Raymond IV of Toulouse (Count)", "Tancred"])
    assert cover("Smith, John", ["Smith, John"]) and cover("Yes", ["Yes"]) and cover("4.", ["4"])
    assert not cover("Aisne, Ardennes", ["Aisne"])  # an item left out
    assert not cover("Aisne, Ardennes", ["Ardennes", "Aisne"])  # out of order
    assert not cover("Aisne, Ardennes", ["Aisne", "Ardennes", "Mayotte"])  # not in the line
    assert not cover("Raymond IV (Count)", ["Raymond IV"])  # a detail outside its item
    assert not cover("1. Aisne 2. Ardennes", ["Aisne", "Ardennes"]) and not cover("x", [])
    prompt, ids = mis.cluster_prompt("Which?", ["a, b", "none", "a, b"], "0:q", mis.SPLIT_PROMPT)
    assert sorted(ids.values()) == ["a, b", "none"] and all(w not in prompt for w in mis.WORKERS)
    inv = {t: i for i, t in ids.items()}
    good = {"lines": [{"id": inv["a, b"], "status": "answer", "items": ["a", "b"]},
                      {"id": inv["none"], "status": "empty", "items": []}]}
    assert mis.parse_split(good, ids) == {"a, b": {"status": "answer", "items": ["a", "b"]},
                                          "none": {"status": "empty", "items": []}}
    bad = {"lines": [{"id": inv["a, b"], "status": "answer", "items": ["a"]},
                     {"id": inv["none"], "status": "no_answer", "items": ["none"]}]}
    assert {v["status"] for v in mis.parse_split(bad, ids).values()} == {"invalid"}
    for broken in [{"lines": good["lines"][:1]}, {"lines": good["lines"] * 2}, {"items": []},
                   {"lines": [{**good["lines"][0], "status": "maybe"}, good["lines"][1]]}]:
        with pytest.raises(ValueError):
            mis.parse_split(broken, ids)
    llm = ScriptedLLM({"worker": [bad, good]})
    rec = mis.split(LLMClient(get_spec(mis.SPLITTER), Trace(tmp_path), transport=llm), "Which?", ["a, b", "none"], "0:q")
    assert rec["status"] == "ok" and rec["attempts"] == 2 and rec["invalid"] == 0 and "response_format" in llm.bodies[0]
    llm = ScriptedLLM({"worker": [bad] * mis.TRIES})
    rec = mis.split(LLMClient(get_spec(mis.SPLITTER), Trace(tmp_path), transport=llm), "Which?", ["a, b", "none"], "0:q")
    assert rec["status"] == "ok" and rec["invalid"] == 2  # kept; those slots count as failed
    assert mis.slot_items({"status": "ok", "answer_line": "a, b"}, rec["lines"]) is None
    assert mis.slot_items({"status": "ok", "answer_line": "none"}, mis.parse_split(good, ids)) == []
    assert mis.split(None, "Which?", [], "0:q")["attempts"] == 0


def test_agreement_keeps_nine_slot_denominator_and_seeded_ties():
    rule = lambda rows: mis.rule_agreement(rows, lines_of(rows))
    concentrated = rule(records([[["a"]] * 3, [["a"]] * 3, [["b"]] * 3]))
    distributed = rule(records([[["a"], ["a"], ["b"]]] * 3))
    assert concentrated["agreement"] == distributed["agreement"] == 6 / 9
    assert concentrated["cross_worker_agreement"] == 9 / 27
    assert distributed["cross_worker_agreement"] == 15 / 27
    failed = records([[["a"], ["A"], None], [None] * 3, [None] * 3])
    assert rule(failed)["support"] == 2 and rule(failed)["of"] == 9
    assert rule(records([[None] * 3] * 3))["agreement"] == 0
    with pytest.raises(ValueError, match="duplicate"):
        rule(failed + failed[:1])
    with pytest.raises(ValueError, match="9 probe slots"):
        mis.agreement(["x"] * 8)
    with pytest.raises(ValueError, match="9 probe slots"):
        mis.set_agreement([None] * 8)
    scores = {c: {"agreement": 1 / 3, "cross_worker_agreement": 0.} for c in mis.CANDIDATES}
    pick = mis.select("monaco_1", scores)
    assert pick == mis.select("monaco_1", dict(reversed(list(scores.items()))))
    assert len(pick["tied_candidates"]) == 4


def test_item_f1_agreement_reduces_to_modal_share_for_one_item_answers():
    rule = lambda rows: mis.rule_agreement(rows, lines_of(rows))
    one = records([[["a"]] * 3, [["a"]] * 3, [["b"], ["b"], None]])
    labels = {"a": "g0", "b": "g1"}
    out = mis.set_agreement(mis.item_sets(one, lines_of(one), labels))
    assert out["agreement"] == round(6 / 9, 12) == round(rule(one)["agreement"], 12)
    assert out["cross_worker_agreement"] == round(rule(one)["cross_worker_agreement"], 12)
    assert mis.set_agreement([None] * 9)["agreement"] == 0
    # Lists: partial overlap earns partial agreement instead of an exact-match collapse.
    lists = records([[["a", "b", "c"], ["a", "b"], ["a", "b", "c", "d"]]] * 3)
    labels = {t: f"g{t}" for t in "abcd"}
    sets = mis.item_sets(lists, lines_of(lists), labels)
    assert mis.f1(sets[0], sets[1]) == pytest.approx(0.8) and mis.f1(sets[0], None) == 0
    assert mis.f1(frozenset(), frozenset()) == 1 and mis.f1(frozenset(), sets[0]) == 0
    out = mis.set_agreement(sets)
    assert out["agreement"] == pytest.approx((3 + 3 * 0.8 + 3 * 6 / 7) / 9) and out["support"] == 3
    assert rule(lists)["agreement"] == 3 / 9
    # Synonyms share a group; items marked as no answer are dropped, a slot of only such items fails;
    # "nothing qualifies" is the empty answer; a line that failed the split check is a failed slot.
    rows = records([[["Arizona Cardinals"], ["Cardinals"], ["unknown"]], [[4], [], ["x"]], [None] * 3])
    lines = {**lines_of(rows), "x": {"status": "invalid", "items": ["y"]}}
    labels = {"Arizona Cardinals": "g0", "Cardinals": "g0", "unknown": None, "4": "g1"}
    sets = mis.item_sets(rows, lines, labels)
    assert sets[:6] == [frozenset({"g0"}), frozenset({"g0"}), None, frozenset({"g1"}), frozenset(), None]
    with pytest.raises(KeyError):
        mis.item_sets(rows, lines, {})


def test_cluster_prompt_hides_slots_and_reply_must_partition_ids(tmp_path):
    texts = ['["b"]', '["a"]', '["b"]', "I cannot tell"]
    prompt, ids = mis.cluster_prompt("Which?", texts, "0:q")
    assert sorted(ids.values()) == sorted(set(texts)) and (prompt, ids) == mis.cluster_prompt("Which?", texts[::-1], "0:q")
    assert all(w not in prompt for w in mis.WORKERS) and "naive" not in prompt and "Question: Which?" in prompt
    inv = {t: i for i, t in ids.items()}
    labels = mis.parse_clusters({"groups": [[inv['["a"]'], inv['["b"]']]], "no_answer": [inv["I cannot tell"]]}, ids)
    assert labels == {'["a"]': "g0", '["b"]': "g0", "I cannot tell": None}
    for bad in [{"groups": [list(ids)], "no_answer": [inv['["a"]']]}, {"groups": [list(ids)[:2]], "no_answer": []},
                {"groups": [list(ids), []], "no_answer": []}, {"groups": [list(ids) + ["A9"]], "no_answer": []}]:
        with pytest.raises(ValueError):
            mis.parse_clusters(bad, ids)
    llm = ScriptedLLM({"worker": [{"groups": [], "no_answer": []}, {"groups": [list(ids)], "no_answer": []}]})
    rec = mis.cluster(LLMClient(get_spec(mis.CLUSTERER), Trace(tmp_path), transport=llm), "Which?", texts, "0:q")
    assert rec["status"] == "ok" and rec["attempts"] == 2 and set(rec["labels"].values()) == {"g0"}
    assert "response_format" in llm.bodies[0]
    assert mis.cluster(None, "Which?", [], "0:q") == {"status": "ok", "attempts": 0, "ids": {}, "labels": {}}


def test_pending_retries_transient_failures_up_to_three_attempts():
    key = lambda r: r["k"]
    rows = [{"k": "ok", "status": "ok"}, {"k": "short", "status": "length"}, {"k": "err", "status": "error"},
            {"k": "budget", "status": "error"}, {"k": "budget", "status": "budget"},
            {"k": "spent", "status": "error"}, {"k": "spent", "status": "error"}, {"k": "spent", "status": "error"},
            {"k": "late", "status": "error"}, {"k": "late", "status": "ok"}]
    planned = ["ok", "short", "err", "budget", "spent", "late", "new"]
    assert mis.pending(planned, rows, key) == ["err", "budget", "spent", "new"]  # three errors: one attempt left
    assert mis.pending(planned, rows + [{"k": "spent", "status": "error"}], key) == ["err", "budget", "new"]
    # Probes: an error, a length stop or a missing answer line is retried once.
    probes = [{"k": "short", "status": "length"}, {"k": "none", "status": "no_answer"}, {"k": "err", "status": "error"},
              {"k": "again", "status": "length"}, {"k": "again", "status": "no_answer"}, {"k": "ok", "status": "ok"}]
    assert mis.pending_probes(["short", "none", "err", "again", "ok", "new"], probes, key) == ["short", "none", "err", "new"]
    assert mis.latest(rows, key)["late"]["status"] == "ok"


def test_judge_prompt_kind_and_gold_rendering():
    assert mis.judge_kind(["Paris"]) == "single" and mis.judge_kind([True]) == "single"
    assert mis.judge_kind([["Paris", 2]]) == "list" and mis.judge_kind(["a", "b"]) == "list"
    assert mis.gold_text([True]) == "['Yes']" and mis.gold_text([False]) == "['No']"
    assert mis.gold_text([1]) == "[1]"  # a count of one is not "Yes"
    p = mis.judge_prompt("Q?", "resp", ["a", "b"])
    assert "not an estimate! \n\nreasoning:" in p and "overlapping answers:" in p
    assert "[correct_answer]: ['a', 'b']" in p and "[response]: 'resp'" in p
    assert "final precision:" in mis.judge_prompt("Q?", "resp", [53.8])


def test_judgement_parsing_matches_published_scores():
    single = "extracted_final_answer: 29.4\n\nreasoning: ...\n\ncorrect: no\n\nprecision: ...\n\nfinal precision: 0.5466"
    assert mis.parse_judgement(single, [53.82585751978892])["score"] == 0.5466
    lst = ("extracted_final_answer: Aisne, Ardennes, Haute-Marne\n\nfinal answer length: 3\n\nreasoning: x\n\n"
           "correct: no\n\noverlapping answers: Aisne")
    out = mis.parse_judgement(lst, ["Mayotte", "Aisne", "Pas-de-Calais"])
    assert out["score"] == pytest.approx(1 / 3) and out["precision"] == out["recall"] == pytest.approx(1 / 3)
    # Recall counts every gold value; empty and NULL items are not matches; precision is capped at 1.
    rows = [["a", 1], ["b", 2]]
    out = mis.parse_judgement("final answer length: 1\n\noverlapping answers: ###a 1###b 2###", rows)
    assert (out["num_correct"], out["predicted"], out["gold_length"]) == (2, 2, 4)
    assert mis.parse_judgement("final answer length: 4\n\noverlapping answers: NULL", ["x"] * 2)["score"] == 0
    # The judge may list more overlaps than gold values (116: three for two); recall is capped at 1.
    out = mis.parse_judgement("final answer length: 3\n\noverlapping answers: a###b###c", ["a", "b"])
    assert out["recall"] == 1 and out["score"] == 1
    with pytest.raises(ValueError):
        mis.parse_judgement("correct: yes", ["a", "b"])


def test_judge_retries_once_then_fails(tmp_path):
    llm = ScriptedLLM({"worker": ["garbage", "final precision: 1"]})
    rec = mis.judge(LLMClient(get_spec(mis.JUDGE), Trace(tmp_path), transport=llm), "Q?", "r", ["a"])
    assert rec["status"] == "ok" and rec["score"] == 1 and rec["attempts"] == 2
    llm = ScriptedLLM({"worker": ["garbage"] * mis.TRIES})
    assert mis.judge(LLMClient(get_spec(mis.JUDGE), Trace(tmp_path), transport=llm), "Q?", "r", ["a"])["score"] is None
    assert len(llm.bodies) == mis.TRIES == 4


def test_solve_failures(tmp_path):
    llm = ScriptedLLM({"worker": [Raw("Answers: a", "length"), "reasoning only"]})
    client = LLMClient(get_spec(mis.EXECUTOR), Trace(tmp_path), transport=llm)
    rec = mis.solve(client, "q")
    assert rec["status"] == "length" and rec["answer_line"] is None
    assert mis.solve(client, "q")["status"] == "no_answer"
    trace = Trace(tmp_path / "budget", Limits(max_cost_usd=0))
    llm = ScriptedLLM({"worker": []})
    assert mis.solve(LLMClient(get_spec(mis.EXECUTOR), trace, transport=llm), "q")["status"] == "budget"
    assert not llm.bodies


def test_analysis_oracle_missing_and_failed_runs_score_zero():
    targets = [{"target_id": "q"}]
    sel = [{"target_id": "q", "primary": {"candidate": "clarify", "tied_candidates": ["clarify", "naive"]},
            "cross": {"candidate": "naive"}}]
    ex = [{"target_id": "q", "candidate": c, "rep": 0} for c in mis.CANDIDATES]
    judged = [{"target_id": "q", "candidate": "naive", "rep": 0, "status": "ok", "score": .5},
              {"target_id": "q", "candidate": "clarify", "rep": 0, "status": "ok", "score": 1.},
              {"target_id": "q", "candidate": "decompose", "rep": 0, "status": "error", "score": None}]
    out = mis.analyze(targets, sel, ex, judged, kinds={"q": "list"}, reps=1)
    s = out["selection"]["score"]
    assert s["selected"]["mean"] == s["best_in_hindsight"]["mean"] == 1
    assert s["naive"]["mean"] == .5 and s["decompose"]["mean"] == s["structured"]["mean"] == 0
    assert s["random"]["mean"] == pytest.approx(1.5 / 4) and s["tie_average"]["mean"] == .75
    assert out["selection"]["perfect"]["selected"]["mean"] == 1
    assert out["by_kind"]["list"]["targets"] == 1
    with pytest.raises(ValueError, match="duplicate"):
        mis.analyze(targets, sel, ex + ex[:1], judged, reps=1)
    with pytest.raises(ValueError, match="without execution"):
        mis.analyze(targets, sel, ex[:1], judged, reps=1)


# Published oracle scores (GPT-4o, Llama): 0 is single, one run right -> single_one_model_correct; 1 is a list at
# 0.5 -> list_0.4-0.6; 2 is single, both right -> excluded; 3 is time-dependent.
SCORES = {0: (1., 0.), 1: (.5, .5), 2: (1., 1.), 3: (1., 1.)}


def fake_monaco(root: Path, n: int = 4, second_oracle_run: bool = True) -> None:
    rows, time_dep = [], {}
    (root / monaco.ORACLE_RUN).mkdir(parents=True)
    llama = root / "language_models_predictions/llama31_405b_instruct_rag_oracle"
    if second_oracle_run:
        llama.mkdir(parents=True)
    (root / "time_dependency_data").mkdir()
    for ex in range(n):
        q = f"Which towns in region {ex} have a harbour?"
        answer = [GOLD_SECRET, f"Town{ex}"] if ex % 2 else [GOLD_SECRET]
        rows.append({"ex_num": ex, "question": q, "decomposition": ["DECOMP-SECRET #1"], "validated_answer": answer})
        time_dep[q] = {"is_time_dependent": ex == n - 1, "answer_change_frequency": None}
        (root / monaco.ORACLE_RUN / f"llm_qa_judgement__{ex}.json").write_text(json.dumps({
            "question": q, "output": f"ANSWER: [\"{GOLD_SECRET}\"]", "input_documents": [f"*** Document title: D{ex}\nfacts"],
            "gold_decomposition": "DECOMP-SECRET", "gold_answers": answer,
            "judge_response": {"prompt": "JUDGE-SECRET", "llm_judgement": "final precision: 1"},
            "judge_scores": {"judge_score": SCORES.get(ex, (1., 1.))[0], "precision": 1.0}}))
        if second_oracle_run:
            (llama / f"llm_qa_judgement__{ex}.json").write_text(json.dumps({
                "output": "Answers: Town", "judge_scores": {"judge_score": SCORES.get(ex, (1., 1.))[1]}}))
    (root / monaco.RELEASE_FILE).write_text("".join(json.dumps(r) + "\n" for r in rows))
    (root / monaco.TIME_DEPENDENCY_FILE).write_text(json.dumps(time_dep))
    (root / "SOURCE.json").write_text(json.dumps({"origin": "fake", "revision": "test"}))


def test_loaders_return_documents_only(tmp_path):
    fake_monaco(tmp_path)
    assert monaco.oracle_ex_nums(tmp_path) == [0, 1, 2, 3]
    docs = monaco.load_oracle_documents(1, tmp_path)
    assert docs == ["*** Document title: D1\nfacts"]
    assert monaco.load_time_dependency(tmp_path)["Which towns in region 3 have a harbour?"] is True


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[1] / "scripts/run_monaco_instruction_selection.py"
    spec = importlib.util.spec_from_file_location("monaco_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_lifecycle_offline_gold_never_reaches_models(tmp_path, monkeypatch, runner):
    data = tmp_path / "monaco"
    data.mkdir()
    fake_monaco(data)
    monkeypatch.setattr(runner, "ALLOCATION", {"single_one_model_correct": 1, "list_0.4-0.6": 1, "single_partial": 0})
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fake")
    args = argparse.Namespace(experiment=tmp_path / "exp", data_root=data, dry_run=True, batch=False,
                              env_file=tmp_path / "absent.env", session_cost_usd=100., run_cost_usd=2., concurrency=1,
                              ex_nums=None)
    runner.prepare(args)
    assert not args.experiment.exists()
    args.dry_run = False
    runner.prepare(args)
    manifest, targets, inputs = runner.load(args.experiment)
    assert manifest["pool"]["size"] == 3 and manifest["pool"]["rule"] == "stratified"  # time-dependent 3 is out
    assert [(t["ex_num"], t["stratum"]) for t in targets] == [(0, "single_one_model_correct"), (1, "list_0.4-0.6")]
    assert "target_selection.json" in manifest["input_hashes"]

    def model(body):
        content = body["messages"][0]["content"]
        if content.startswith("Judge whether"):
            assert GOLD_SECRET in content  # only the judge sees the gold
            return "final answer length: 2\n\noverlapping answers: x" if "Town" in content else "final precision: 1"
        if content.startswith("Below are final answer lines"):
            assert "Document title" not in content
            return split_by_separator(body)
        if content.startswith("Below are answer items"):
            assert "Document title" not in content
            return group_by_text(body)
        if "one row per candidate" in content and body["model"] == get_spec(mis.WORKERS[0]).model and not failed:
            failed.append(1)
            return HTTPError(400, "offline transient failure")
        return "reasoning\nAnswers: harbour town" if "one row per candidate" in content else "Answers: other"

    failed = []
    llm = ScriptedLLM({"worker": model})
    monkeypatch.setattr(runner, "http_transport", lambda key: llm)
    runner.validate_judge(args, manifest, targets, inputs)
    assert len(runner.read_rows(args.experiment / "judge_validation.jsonl")) == 2
    args.candidate_file, args.author = tmp_path / "reviewed.jsonl", "offline test author"
    args.review_type = "question-only review"
    old_keys = {"analogical": "a", "clarify": "b", "local_check": "c"}
    args.candidate_file.write_text("".join(json.dumps({"target_id": t["target_id"], "instructions": old_keys,
                                   "review": {"accepted": True, "notes": "question-only"}}) + "\n" for t in targets))
    with pytest.raises(ValueError, match="decompose, clarify, structured"):
        runner.import_candidates(args, manifest, targets, inputs)
    args.candidate_file.write_text("".join(json.dumps({"target_id": t["target_id"], "instructions": INSTRUCTIONS,
                                   "review": {"accepted": True, "notes": "question-only"}}) + "\n" for t in targets))
    runner.import_candidates(args, manifest, targets, inputs)
    manifest, targets, inputs = runner.load(args.experiment)
    assert manifest["frozen"] and manifest["candidate_authoring"]["review_type"] == "question-only review"
    assert set(manifest["models"]) == {*mis.WORKERS, mis.JUDGE, mis.SPLITTER}
    assert len((args.experiment / "planned.csv").read_text().splitlines()) == 1 + 2 * 4 * 3 * 4
    runner.probe(args, manifest)
    rows = runner.read_rows(args.experiment / "results.jsonl")
    assert len(rows) == 2 * 36 and sum(r["status"] == "error" for r in rows) == 1
    with pytest.raises(ValueError, match="retryable"):
        runner.split(args, manifest, targets, inputs)
    runner.probe(args, manifest)
    runner.probe(args, manifest)
    assert len(runner.read_rows(args.experiment / "results.jsonl")) == 2 * 36 + 1
    with pytest.raises(ValueError, match="split stage"):
        runner.cluster(args, manifest, targets, inputs)
    runner.split(args, manifest, targets, inputs)
    runner.split(args, manifest, targets, inputs)
    with pytest.raises(ValueError, match="already split"):
        runner.probe(args, manifest)
    with pytest.raises(ValueError, match="cluster stage"):
        runner.selections(args, manifest, targets)
    runner.cluster(args, manifest, targets, inputs)
    runner.cluster(args, manifest, targets, inputs)
    sels = runner.selections(args, manifest, targets)
    assert all(s["scores"]["naive"]["support"] == 9 for s in sels)
    assert all(s["scores"]["structured"]["support"] == 9 for s in sels)
    runner.execute(args, manifest, targets)
    runner.execute(args, manifest, targets)
    runner.judge(args, manifest, targets, inputs)
    runner.judge(args, manifest, targets, inputs)
    calls = [b["messages"][0]["content"] for b in llm.bodies]
    assert sum(c.startswith("Judge whether") for c in calls) == 2 + 2 * 12  # validation, runs
    assert sum(c.startswith("Use the documents") for c in calls) == 2 * 36 + 1 + 2 * 12
    assert sum(c.startswith("Below are final answer lines") for c in calls) == 2
    assert sum(c.startswith("Below are answer items") for c in calls) == 2
    for c in calls:
        if not c.startswith("Judge whether"):
            assert GOLD_SECRET not in c and "DECOMP-SECRET" not in c and "JUDGE-SECRET" not in c
    runner.analyze(args, manifest, targets)
    summary = json.loads((args.experiment / "analysis/summary.json").read_text())
    assert "probe_majority" not in summary["selection"]["score"]
    assert summary["recorded_executions"] == summary["planned_executions"] == 24
    assert summary["judged_ok"] == 24 and summary["split_line_statuses"] == {"answer": 4}
    assert set(summary["by_stratum"]) == {"single_one_model_correct", "list_0.4-0.6"}

    path = Path(__file__).resolve().parents[1] / "scripts/rejudge_monaco_instruction_selection.py"
    spec = importlib.util.spec_from_file_location("monaco_rejudge", path)
    rejudge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rejudge)
    monkeypatch.setattr(rejudge.runner, "http_transport", lambda key: llm)
    re_args = argparse.Namespace(**{**vars(args), "experiment": tmp_path / "rejudge", "source": args.experiment})
    rejudge.prepare(re_args)
    re_manifest, re_targets, re_inputs = rejudge.load(re_args.experiment)
    assert re_manifest["source_judge"] == manifest["judge"] and re_manifest["judge"] == mis.JUDGE
    before = len(llm.bodies)
    rejudge.runner.validate_judge(re_args, re_manifest, re_targets, re_inputs)
    rejudge.runner.judge(re_args, re_manifest, re_targets, re_inputs)
    rejudged = [b["messages"][0]["content"] for b in llm.bodies[before:]]
    assert len(rejudged) == 2 + 2 * 12 and sum("[response]: 'Answers: " in c for c in rejudged) == 2 * 12
    assert all(c.startswith("Judge whether") for c in rejudged)
    rejudge.analyze(re_args, re_manifest, re_targets)
    re_summary = json.loads((re_args.experiment / "analysis/summary.json").read_text())
    assert re_summary["judge_changes"]["compared"] == 24 and "hindsight_null" in re_summary

    path = Path(__file__).resolve().parents[1] / "scripts/judge_monaco_probes.py"
    spec = importlib.util.spec_from_file_location("monaco_probe_judge", path)
    probe_judge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe_judge)
    monkeypatch.setattr(probe_judge.runner, "http_transport", lambda key: llm)
    pj_args = argparse.Namespace(**{**vars(args), "experiment": tmp_path / "probe_judge", "source": args.experiment,
                                    "judged": re_args.experiment})
    probe_judge.prepare(pj_args)
    _, pj_targets, pj_inputs = probe_judge.load(pj_args.experiment)
    before = len(llm.bodies)
    probe_judge.judge(pj_args, pj_targets, pj_inputs)
    probe_judge.judge(pj_args, pj_targets, pj_inputs)
    assert len(llm.bodies) - before == 2 * 36
    probe_judge.analyze(pj_args, pj_targets)
    pj = json.loads((pj_args.experiment / "analysis/summary.json").read_text())
    assert pj["probe_judged_ok"] == 2 * 36 and set(pj["policies_on_executions"]) >= {"selected", "probe_oracle"}
    # A run judged by the current judge can score its own executions.
    probe_judge.prepare(argparse.Namespace(**{**vars(pj_args), "experiment": tmp_path / "probe_judge_self",
                                              "judged": args.experiment}))
    (args.experiment / "prompts.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="frozen artifact"):
        runner.load(args.experiment)


def test_explicit_questions_must_be_in_pool(tmp_path, runner):
    data = tmp_path / "monaco"
    data.mkdir()
    fake_monaco(data)
    args = argparse.Namespace(experiment=tmp_path / "exp", data_root=data, dry_run=False, ex_nums=[1, 0, 1])
    runner.prepare(args)
    manifest, targets, _ = runner.load(args.experiment)
    assert [t["ex_num"] for t in targets] == [0, 1] and manifest["pool"]["rule"] == "explicit"
    args.experiment, args.ex_nums = tmp_path / "exp2", [3]
    with pytest.raises(ValueError, match="not in the pool"):
        runner.prepare(args)


def test_clustering_validation_offline(tmp_path, monkeypatch):
    data = tmp_path / "monaco"
    data.mkdir()
    fake_monaco(data, n=6, second_oracle_run=False)
    for run, text, score in [("run_a", "Answers: Arizona Cardinals", 1.0), ("run_b", "**Answers:** Cardinals", 1.0),
                             ("run_c", "Answers: Bears", 0.0)]:
        (data / monaco.PREDICTIONS_DIR / run).mkdir()
        for ex in range(6):
            (data / monaco.PREDICTIONS_DIR / run / f"llm_qa_judgement__{ex}.json").write_text(json.dumps(
                {"output": f"reasoning\n{text}", "judge_scores": {"judge_score": score}}))
    path = Path(__file__).resolve().parents[1] / "scripts/validate_monaco_answer_clustering.py"
    spec = importlib.util.spec_from_file_location("clustering_validation", path)
    val = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(val)
    assert val.published_answer("x\n**Answers:** a, b\n") == "a, b" and val.published_answer("none") is None
    assert val.rule_key("1,234, b") == val.rule_key("b; 1234.")
    monkeypatch.setattr(val, "SAMPLE_TARGETS", 1)
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fake")
    args = argparse.Namespace(experiment=tmp_path / "val", data_root=data, questions=2, dry_run=False, batch=False,
                              session_cost_usd=1., run_cost_usd=.5, concurrency=1, env_file=tmp_path / "absent.env")
    val.prepare(args)
    manifest, inputs = val.load(args.experiment, calls=True)
    assert len(inputs) == 2 and all(len(i["answers"]) == 4 for i in inputs)  # three runs plus the oracle run

    def clusterer(body):
        content = body["messages"][0]["content"]
        assert GOLD_SECRET not in content.split("Answers:\n")[0]
        ids = dict(line.split(": ", 1) for line in content.split("Answers:\n")[1].splitlines())
        same = [i for i, t in ids.items() if "Cardinals" in t]
        return {"groups": [same] + [[i] for i in ids if i not in same], "no_answer": []}

    llm = ScriptedLLM({"worker": clusterer})
    monkeypatch.setattr(val.runner, "http_transport", lambda key: llm)
    val.cluster(args, inputs)
    val.cluster(args, inputs)
    assert len(llm.bodies) == 2
    val.analyze(args, inputs)
    summary = json.loads((args.experiment / "summary.json").read_text())
    # Per question: same pairs = {A.Cardinals, Cardinals} plus each with the oracle answer; different = Bears x 3.
    assert summary["all"]["same_luna_accuracy"] < 1 and summary["all"]["different_luna_accuracy"] == 1
    assert summary["all"]["same_rule_accuracy"] < summary["all"]["same_luna_accuracy"]


def test_judge_reads_the_answer_line_unless_there_is_none():
    content = 'Excluded: "b", "c".\nAnswers: a; d (2)'
    assert mis.judge_response({"answer_line": mis.answer_line(content), "content": content}) == "Answers: a; d (2)"
    assert mis.judge_response({"answer_line": None, "content": "free text"}) == "free text"


def test_strata_and_allocation(runner):
    assert runner.stratum("list", 5, [.3, .5]) == "list_0.4-0.6" and runner.stratum("list", 5, [.1, .2]) == "list_0.0-0.2"
    assert runner.stratum("list", 5, [.9, .8]) == "list_0.8-1.0" and runner.stratum("list", 101, [.5, .5]) is None
    assert runner.stratum("single", 1, [1., 0.]) == "single_one_model_correct"
    assert runner.stratum("single", 1, [.9, 1.]) == "single_partial" and runner.stratum("single", 1, [.4, .6]) == "single_partial"
    assert runner.stratum("list", 5, [0., 0.]) is None and runner.stratum("single", 1, [1., 1.]) is None
    members = {name: list(range(100)) for name in runner.ALLOCATION}
    sample = runner.stratified_sample(members)
    assert {n: len(v) for n, v in sample.items()} == runner.ALLOCATION and sample == runner.stratified_sample(members)
    assert sum(runner.ALLOCATION.values()) == 50
    with pytest.raises(ValueError, match="planned"):
        runner.stratified_sample({**members, "single_partial": [1, 2]})


def test_hindsight_null_is_zero_for_identical_candidates_and_positive_under_noise():
    assert mis.hindsight_null({"q": [0.5] * 12}, draws=50)["mean"] == 0
    noisy = mis.hindsight_null({"q": [1.] * 6 + [0.] * 6, "r": [1., 0.] * 6}, draws=200)
    assert 0 < noisy["mean"] and noisy["q025"] <= noisy["mean"] <= noisy["q975"]
