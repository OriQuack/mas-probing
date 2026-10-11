"""LongCoT questions (github.com/LongHorizonReasoning/longcot at the commit in scripts/fetch_datasets.py).

Data: ~/data2/datasets/LongCoT/repo/src/data/<domain>/<difficulty>.json, fetched by `scripts/fetch_datasets.py
longcot`. `LongcotQuestion` carries only what a model may see: the prompt, plus ids and the template name for
selecting subsets. The reference answer and the `problem` metadata stay out of it: `problem` can hold
solution-derived values (e.g. chess `final_fen`; logic instances are checked programmatically against it), so both are
returned only by `load_references`, for scoring and analysis.

LongCoT-mini is the `easy` difficulty of every domain. The official evaluation is a single model call without tools;
results from our multi-agent runs on these prompts are reported separately from official LongCoT scores.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

LONGCOT_ROOT = Path.home() / "data2/datasets/LongCoT/repo/src/data"
DOMAINS = ("logic", "cs", "chemistry", "chess", "math")
DIFFICULTIES = ("easy", "medium", "hard")


@dataclass(frozen=True)
class LongcotQuestion:
    question_id: str
    domain: str
    difficulty: str
    template: str | None
    prompt: str


@dataclass(frozen=True)
class LongcotReference:
    question_id: str
    answer: object  # str | list | dict | None (logic: verified from `problem`)
    problem: dict | None


def _records(domain: str, difficulty: str, root: Path) -> list[dict]:
    if domain not in DOMAINS or difficulty not in DIFFICULTIES:
        raise ValueError(f"unknown LongCoT split {domain}/{difficulty}")
    return json.loads((root / domain / f"{difficulty}.json").read_text(encoding="utf-8"))["questions"]


def _splits(domain: str | None, difficulty: str | None) -> list[tuple[str, str]]:
    return [(d, f) for d in ([domain] if domain else DOMAINS) for f in ([difficulty] if difficulty else DIFFICULTIES)]


def load_questions(domain: str | None = None, difficulty: str | None = None, *, template: str | None = None,
                   root: Path = LONGCOT_ROOT) -> list[LongcotQuestion]:
    out = []
    for dom, diff in _splits(domain, difficulty):
        for r in _records(dom, diff, root):
            name = (r.get("problem") or {}).get("template")
            if template is None or name == template:
                out.append(LongcotQuestion(str(r["question_id"]), dom, diff, name, r["prompt"]))
    return out


def load_references(domain: str | None = None, difficulty: str | None = None, *,
                    root: Path = LONGCOT_ROOT) -> dict[str, LongcotReference]:
    """Scoring and analysis only: never pass these to a model."""
    return {str(r["question_id"]): LongcotReference(str(r["question_id"]), r.get("answer"), r.get("problem"))
            for dom, diff in _splits(domain, difficulty) for r in _records(dom, diff, root)}
