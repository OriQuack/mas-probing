"""Answer equivalence with LongCoT's own math comparison (`src/_verify/_math.py` of the pinned repository).

The `longcot` package `__init__` imports every domain's verifier (rdkit, chess, LLM clients), which the pinned
environment does not have. Only the math module is needed, so it is loaded under stub parent packages. The Gemini
fallback judge is never used: a comparison sympy cannot settle is `unresolved` and counts as different.

LongCoT's parser reads plain sympy syntax: LaTeX roots and logarithms (`\\sqrt{21}`, `\\log\\frac{a}{b}`,
`\\log_2(x)`) never parse, so equal values in different notation matched only as identical strings. Equivalence
version 2 (`EQUIVALENCE_VERSION`) adds value-preserving rewrites before LongCoT's comparison (`to_plain`): LaTeX
roots, logarithms and trig functions as sympy calls, `\\text{}` unwrapped, thousands separators in a lone number, a
singleton set as its element, a leading `x \\in` before a set. Where LongCoT's comparison stays undecided, three more
checks can make a match: sets as unordered collections, tuples entry by entry, and closed-form constants whose
difference evaluates to exactly zero. Unbased `\\log` is the natural logarithm, as in sympy and in competition
usage. Prose such as "all integers n >= 13" is not rewritten.
"""

from __future__ import annotations

import importlib
import re
import sys
import types
from functools import lru_cache
from pathlib import Path

import sympy as sp

from perturbation_consistency.longcot_nodes import clean_answer

LONGCOT_SRC = Path.home() / "data2/datasets/LongCoT/repo/src"
EQUIVALENCE_VERSION = 2
_FUNCS = ("arctan", "log", "ln", "sin", "cos", "tan")
_SET = re.compile(r"\s*(?:\\\{(.*)\\\}|\{(.*)\})\s*")


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


def _group_end(s: str, i: int) -> int:
    """Index just past the bracket group opened at s[i] ( (, { or [ ), or -1 if it never closes."""
    open_, close = s[i], {"(": ")", "{": "}", "[": "]"}[s[i]]
    depth = 0
    for j in range(i, len(s)):
        depth += (s[j] == open_) - (s[j] == close)
        if depth == 0:
            return j + 1
    return -1


def _argument(s: str, i: int) -> tuple[str, int] | None:
    """A function's argument starting at s[i]: (...), {...}, \\frac{..}{..} or an atom, with the index after it."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return None
    if s[i] in "({":
        end = _group_end(s, i)
        return (s[i + 1:end - 1], end) if end > 0 else None
    if s.startswith("\\frac", i) and s.startswith("{", i + 5):
        a = _group_end(s, i + 5)
        b = _group_end(s, a) if 0 < a < len(s) and s[a] == "{" else -1
        return (s[i:b], b) if b > 0 else None
    m = re.match(r"\\?[A-Za-z0-9.]+", s[i:])
    return (m.group(0), i + m.end()) if m else None


def _function_at(s: str, i: int) -> str | None:
    for f in _FUNCS:
        end = i + 1 + len(f)
        if s.startswith("\\" + f, i) and not s[end:end + 1].isalpha():
            return f
    return None


def to_plain(value: str) -> str:
    """LaTeX notation rewritten into the plain sympy syntax LongCoT's parser reads (see the module docstring)."""
    s = clean_answer(str(value))
    for token in ("\\left", "\\right", "\\displaystyle"):
        s = s.replace(token, "")
    for _ in range(3):
        s = re.sub(r"\\(?:text|mathrm|operatorname)\{([^{}]*)\}", r"\1", s)
    s = s.replace("{,}", "")
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", s.strip()):
        s = s.replace(",", "")
    s = re.sub(r"^\s*\(?[A-Za-z_\d₀-₉, ]+\)?\s*(?:∈|\\in)\s*(?=\\?\{)", "", s)  # "(S1, S2) \in {...}"
    if (inner := _set_body(s)) is not None and not re.search(r"[,:|;]|\\mid", inner):
        s = inner  # singleton set
    out, i = [], 0
    while i < len(s):
        if s.startswith("\\sqrt", i):
            j, index = i + 5, None
            if s.startswith("[", j) and (k := _group_end(s, j)) > 0:
                index, j = s[j + 1:k - 1], k
            if arg := _argument(s, j):
                inner = to_plain(arg[0])
                out.append(f"sqrt({inner})" if index is None else f"(({inner})^(1/({index})))")
                i = arg[1]
                continue
        if fn := _function_at(s, i):
            j, base = i + 1 + len(fn), None
            if s.startswith("_", j) and (b := _argument(s, j + 1)):
                base, j = b[0], b[1]
            if arg := _argument(s, j):
                inner = to_plain(arg[0])
                name = "log" if fn in ("log", "ln") else fn
                out.append(f"{name}({inner})" if base is None else f"log({inner}, {base})")
                i = arg[1]
                continue
        out.append(s[i])
        i += 1
    return "".join(out).strip()


def _set_body(s: str) -> str | None:
    """The inside of a whole-string set `{...}` / `\\{...\\}` whose braces match each other, else None."""
    m = _SET.fullmatch(s)
    if not m:
        return None
    body = m.group(1) if m.group(1) is not None else m.group(2)
    depth = 0
    for ch in body:  # "{a} + {b}" is not one set
        depth += (ch == "{") - (ch == "}")
        if depth < 0:
            return None
    return body if depth == 0 else None


def _set_items(s: str) -> list[str] | None:
    body = _set_body(s)
    if body is None or re.search(r"[:|]|\\mid", body):
        return None
    return _math()._split_top_level_csv(body)


def _tuple_items(s: str) -> list[str] | None:
    s = s.strip()
    if not (s.startswith("(") and _group_end(s, 0) == len(s)):
        return None
    items = _math()._split_top_level_csv(s[1:-1])
    return items if len(items) > 1 else None


def _numeric_match(a: str, b: str) -> bool:
    """Both closed-form constants whose difference sympy evaluates to exactly zero. `strict` evaluation raises the
    working precision until the digits are certain, so a tiny true difference (2/3 + sqrt(2)/4^2013 vs 2/3) stays
    nonzero, unlike a float or relative tolerance (which would also overflow on (2^2019-1)^2018). A difference that
    cannot be certified counts as different."""
    x, y = _math()._parse_expression(a), _math()._parse_expression(b)
    if x is None or y is None or x.free_symbols or y.free_symbols or not (x.is_number and y.is_number):
        return False
    try:
        return bool((x - y).evalf(30, strict=True) == 0)
    except Exception:  # noqa: BLE001 - PrecisionExhausted or an evaluation error: not shown equal
        return False


def compare(expected: str, predicted: str) -> str:
    """'match' | 'mismatch' | 'unresolved' | 'textual' for two single values, notation rewritten first (module
    docstring). sympy can raise on long free-form answers (seen: IndexError in its tokenizer); such a pair is
    'unresolved'."""
    try:
        a, b = to_plain(expected), to_plain(predicted)
        status = _math()._compare_component(a, b)
        if status in ("match", "mismatch"):  # LongCoT decided; the checks below only settle what it could not
            return status
        items_a, items_b = _set_items(a), _set_items(b)
        if items_a is not None and items_b is not None:
            rest = list(items_b)
            for item in items_a:
                hit = next((k for k, other in enumerate(rest) if compare(item, other) == "match"), None)
                if hit is None:
                    return status
                rest.pop(hit)
            return "match" if not rest else status
        tuple_a, tuple_b = _tuple_items(a), _tuple_items(b)
        if tuple_a is not None and tuple_b is not None:
            equal = len(tuple_a) == len(tuple_b) and all(compare(x, y) == "match" for x, y in zip(tuple_a, tuple_b))
            return "match" if equal else status
        return "match" if _numeric_match(a, b) else status
    except Exception:  # noqa: BLE001 - any parser failure means the values could not be shown equal
        return "unresolved"


def same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and compare(a, b) == "match"


def answer_parts(payload: object) -> list[str] | None:
    """A stored answer payload (list or comma string) as its components."""
    return _math()._answer_components(payload)


def compare_answer_lists(expected: object, predicted: list[str | None]) -> str:
    """Gold answer payload (list or comma string) against predicted values, entry by entry."""
    parts = _math()._answer_components(expected)
    if parts is None or any(p is None for p in predicted) or len(parts) != len(predicted):
        return "mismatch"
    if all(compare(e, str(p)) == "match" for e, p in zip(parts, predicted)):
        return "match"
    try:  # not all equal: LongCoT's own status label (mismatch / unresolved / textual)
        status = _math()._compare_components([to_plain(p) for p in parts], [to_plain(str(p)) for p in predicted])
        return "mismatch" if status == "match" else status
    except Exception:  # noqa: BLE001 - see compare()
        return "unresolved"


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
