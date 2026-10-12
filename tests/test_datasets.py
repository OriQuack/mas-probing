"""LongCoT and MoNaCo loaders: questions only by default; answers and annotations through reference functions."""

from __future__ import annotations

import dataclasses
import json

import pytest

from minpilot.data import longcot, monaco


def write_longcot(root):
    rows = {"questions": [
        {"question_id": "m1", "prompt": "Problem node_0: ... What are the answers to node_1?",
         "problem": {"template": "linear"}, "answer": ["16"]},
        {"question_id": "m2", "prompt": "Problem node_0: ...", "problem": {"template": "dag"}, "answer": ["3"]},
    ]}
    (root / "math").mkdir(parents=True)
    (root / "math" / "easy.json").write_text(json.dumps(rows))
    (root / "chess").mkdir()
    (root / "chess" / "easy.json").write_text(json.dumps({"questions": [
        {"question_id": "c1", "prompt": "Moves: e4 e5", "problem": {"template": "uci_to_fen", "final_fen": "SECRET"},
         "answer": "SECRET"}]}))


def test_longcot_questions_carry_no_answer_or_problem_metadata(tmp_path):
    write_longcot(tmp_path)
    qs = longcot.load_questions("math", "easy", root=tmp_path)
    assert [q.question_id for q in qs] == ["m1", "m2"] and qs[0].template == "linear"
    assert [q.question_id for q in longcot.load_questions("math", "easy", template="dag", root=tmp_path)] == ["m2"]
    chess = longcot.load_questions("chess", "easy", root=tmp_path)[0]
    assert {f.name for f in dataclasses.fields(chess)} == {"question_id", "domain", "difficulty", "template", "prompt"}
    assert "SECRET" not in json.dumps(dataclasses.asdict(chess))
    refs = longcot.load_references("chess", "easy", root=tmp_path)
    assert refs["c1"].answer == "SECRET" and refs["c1"].problem["final_fen"] == "SECRET"
    with pytest.raises(ValueError):
        longcot.load_questions("math", "mini", root=tmp_path)


def test_monaco_questions_carry_no_answers_or_decomposition(tmp_path):
    rows = [{"ex_num": 7, "question": "Which of the 10 largest ...?", "decomposition": ["return #1", "return #2"],
             "validated_answer": ["Answer A"]}]
    (tmp_path / monaco.RELEASE_FILE).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (tmp_path / "execution_traces").mkdir()
    (tmp_path / "execution_traces" / "dataset_ex_7.json").write_text(json.dumps({
        "Which of the 10 largest ...?": {"decomposition": ["return #1"], "provenance": {}}, "canary": "GUID"}))
    q = monaco.load_questions(tmp_path)[0]
    assert q == monaco.MonacoQuestion(7, "Which of the 10 largest ...?")
    ref = monaco.load_references(tmp_path)[7]
    assert ref.answers == ["Answer A"] and ref.decomposition == ["return #1", "return #2"]
    assert monaco.load_trace(7, tmp_path)["provenance"] == {}
    with pytest.raises(FileNotFoundError, match="fetch_datasets.py monaco"):
        monaco.load_questions(tmp_path / "missing")
