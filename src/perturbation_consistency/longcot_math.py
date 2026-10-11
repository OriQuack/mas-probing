"""Answer equivalence with LongCoT's own math comparison (`src/_verify/_math.py` of the pinned repository).

The `longcot` package `__init__` imports every domain's verifier (rdkit, chess, LLM clients), which the pinned
environment does not have. Only the math module is needed, so it is loaded under stub parent packages. The Gemini
fallback judge is never used: a comparison sympy cannot settle is `unresolved` and counts as different.
"""

from __future__ import annotations

import importlib
import sys
import types
from functools import lru_cache
from pathlib import Path

LONGCOT_SRC = Path.home() / "data2/datasets/LongCoT/repo/src"


@lru_cache(maxsize=1)
def _math():
    if "longcot" not in sys.modules:
        pkg = types.ModuleType("longcot")
        pkg.__path__ = [str(LONGCOT_SRC)]
        sys.modules["longcot"] = pkg
    if "longcot._verify" not in sys.modules:
        sub = types.ModuleType("longcot._verify")
        sub.__path__ = [str(LONGCOT_SRC / "_verify")]
        sys.modules["longcot._verify"] = sub
    return importlib.import_module("longcot._verify._math")


def compare(expected: str, predicted: str) -> str:
    """'match' | 'mismatch' | 'unresolved' | 'textual' for two single values."""
    return _math()._compare_component(str(expected), str(predicted))


def same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and compare(a, b) == "match"


def answer_parts(payload: object) -> list[str] | None:
    """A stored answer payload (list or comma string) as its components."""
    return _math()._answer_components(payload)


def compare_answer_lists(expected: object, predicted: list[str | None]) -> str:
    """Gold answer payload (list or comma string) against predicted values, entry by entry."""
    parts = _math()._answer_components(expected)
    if parts is None or any(p is None for p in predicted):
        return "mismatch"
    return _math()._compare_components(parts, [str(p) for p in predicted])


def group(values: list[str | None]) -> list[list[int]]:
    """Indices grouped by equivalent value (missing answers stay alone), largest group first, ties by first index."""
    groups: list[list[int]] = []
    for i, v in enumerate(values):
        for g in groups:
            if v is not None and same(values[g[0]], v):
                g.append(i)
                break
        else:
            groups.append([i])
    return sorted(groups, key=lambda g: (-len(g), g[0]))
