"""Fixed rule that turns the run's stored final answer (the orchestrator's `finish` answer) into the string passed
to the GAIA scorer. Versioned: change the rule only by bumping EXTRACTION_VERSION, and report the version with
scores. Same rule as the previous pilot's v1.

The orchestrator is already asked to output only the answer; this rule is a deterministic fallback for formatting
slips. It never looks at the ground truth.

v1, applied in order:
  1. strip whitespace, code fences and backticks
  2. if "final answer:" occurs (any case), keep the text after its last occurrence
  3. if several non-empty lines remain, keep the last one
  4. strip surrounding markdown emphasis (**, __, *) and quotes
  5. drop one trailing period when the rest is a number (e.g. "42." -> "42")
"""

from __future__ import annotations

import re

EXTRACTION_VERSION = "v1"

_FINAL = re.compile(r"final\s+answer\s*[:：]", re.I)
_NUMBER = re.compile(r"^[-+$]?[\d,]*\.?\d+%?$")


def extract_final_answer(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip().strip("`").strip()
    if parts := _FINAL.split(s):
        s = parts[-1].strip() if len(parts) > 1 else s
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) > 1:
        s = lines[-1]
    prev = None
    while prev != s:
        prev = s
        for wrap in ("**", "__", "*", '"', "'", "`"):
            if len(s) > 2 * len(wrap) and s.startswith(wrap) and s.endswith(wrap):
                s = s[len(wrap):-len(wrap)].strip()
    if s.endswith(".") and _NUMBER.match(s[:-1]):
        s = s[:-1]
    return s
