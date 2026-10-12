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
