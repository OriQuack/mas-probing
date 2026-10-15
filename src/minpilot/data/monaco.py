"""MoNaCo questions (Hugging Face allenai/MoNaCo_Benchmark at the revision in scripts/fetch_datasets.py).

Data: ~/data2/datasets/MoNaCo, fetched by `scripts/fetch_datasets.py monaco` (gated dataset: the Hugging Face
account must have been granted access). The dataset card asks that the data not be redistributed online, so nothing
from it is copied into this repository.

`MonacoQuestion` carries only the question. The annotated answers and the gold decomposition (QDMR steps) are
returned by `load_references`, and the full reasoning chain (intermediate questions, answers, evidence) by
`load_trace`: these are for scoring and analysis. An experiment that gives a model the decomposition or intermediate
answers must declare it as a condition; they are never part of the default input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MONACO_ROOT = Path.home() / "data2/datasets/MoNaCo"
RELEASE_FILE = "monaco_version_1_release.jsonl"


@dataclass(frozen=True)
class MonacoQuestion:
    ex_num: int
    question: str


@dataclass(frozen=True)
class MonacoReference:
    ex_num: int
    answers: list
    decomposition: list[str]


def _records(root: Path) -> list[dict]:
    path = root / RELEASE_FILE
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run scripts/fetch_datasets.py monaco (needs granted HF access)")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_questions(root: Path = MONACO_ROOT) -> list[MonacoQuestion]:
    return [MonacoQuestion(int(r["ex_num"]), r["question"]) for r in _records(root)]


def load_references(root: Path = MONACO_ROOT) -> dict[int, MonacoReference]:
    """Scoring and analysis only: never pass these to a model by default."""
    return {int(r["ex_num"]): MonacoReference(int(r["ex_num"]), list(r.get("validated_answer") or []),
                                              list(r.get("decomposition") or []))
            for r in _records(root)}


def load_trace(ex_num: int, root: Path = MONACO_ROOT) -> dict:
    """The annotated reasoning chain of one question: {"decomposition": [...], "provenance": {step: [...]}}.
    Analysis only. The file keys this by the question text, next to a contamination `canary` string."""
    data = json.loads((root / "execution_traces" / f"dataset_ex_{ex_num}.json").read_text(encoding="utf-8"))
    (chain,) = [v for k, v in data.items() if k != "canary"]
    return chain


# The paper's oracle (long-context) setting put every gold evidence document of a question in the prompt. Those
# documents are not shipped separately: they are the `input_documents` of the published GPT-4o oracle run.
ORACLE_RUN = "language_models_predictions/gpt4_o_2024-08-06_rag_oracle"
TIME_DEPENDENCY_FILE = "time_dependency_data/monaco_time_dependent_questions.json"


def _oracle_record(ex_num: int, root: Path) -> dict:
    return json.loads((root / ORACLE_RUN / f"llm_qa_judgement__{ex_num}.json").read_text(encoding="utf-8"))


def oracle_ex_nums(root: Path = MONACO_ROOT) -> list[int]:
    """Questions that have published oracle documents (1,287 of 1,315 at the pinned revision)."""
    return sorted(int(p.stem.rsplit("__", 1)[1]) for p in (root / ORACLE_RUN).glob("llm_qa_judgement__*.json"))


def load_oracle_documents(ex_num: int, root: Path = MONACO_ROOT) -> list[str]:
    """Model input: the oracle documents only. The same file also holds the gold answers, the gold decomposition
    and GPT-4.1 judgements; none of those are returned."""
    docs = _oracle_record(ex_num, root)["input_documents"]
    if not isinstance(docs, list) or not all(isinstance(d, str) for d in docs):
        raise ValueError(f"unexpected oracle documents for question {ex_num}")
    return list(docs)


def load_published_judgement(ex_num: int, root: Path = MONACO_ROOT) -> dict:
    """Analysis only: GPT-4o's oracle answer and its published GPT-4.1 judgement, for checking our judge."""
    r = _oracle_record(ex_num, root)
    return {"ex_num": ex_num, "output": r["output"], "judge_scores": r["judge_scores"],
            "judge_prompt": r["judge_response"]["prompt"], "judge_text": r["judge_response"]["llm_judgement"]}


PREDICTIONS_DIR = "language_models_predictions"


def load_published_answers(ex_num: int, root: Path = MONACO_ROOT) -> list[dict]:
    """Analysis only: every published run's text output for one question with its GPT-4.1 judge score.
    Runs without a text output for the question are skipped."""
    out = []
    for run in sorted(p for p in (root / PREDICTIONS_DIR).iterdir() if p.is_dir()):
        path = run / f"llm_qa_judgement__{ex_num}.json"
        if not path.exists():
            continue
        r = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(r.get("output"), str):
            out.append({"run": run.name, "output": r["output"], "judge_score": r["judge_scores"]["judge_score"]})
    return out


def load_time_dependency(root: Path = MONACO_ROOT) -> dict[str, bool]:
    """Question text -> whether its answer changes over time (the dataset's own labels)."""
    data = json.loads((root / TIME_DEPENDENCY_FILE).read_text(encoding="utf-8"))
    return {q: bool(v["is_time_dependent"]) for q, v in data.items()}
