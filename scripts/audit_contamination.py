#!/usr/bin/env python
"""Contamination audit of finished runs with the CURRENT blocklist rules (CPU; no model calls).

Checks what came into a run from outside (tool results that a model received) and what agents asked for:
  - every tool-result message against content_block_reason(question) and the URL rules on URLs it contains.
    Prompts written by the framework (system prompts, instructions, probe questions) contain the question by
    design and are not checked. The search header (it echoes the agent's own query) is dropped first.
  - every search query (query rule) and every read URL (URL rule).
  - audit only (stricter than the live rules): any 50-character window of the question's letters and digits
    quoted in a tool result (`quotes_task_question_window`). 50 letters and digits are about 8-10 words.
Images are not checked (their pixels are not text); a flagged image URL is caught by the URL rule.

Classes: confirmed_exposure (flagged content in a tool result a model received), blocked_attempt (a flagged
query or URL that our tools refused: the blocklist worked, not contamination), filtered_result (a search result
the live blocklist dropped before the model saw it: not contamination), executed_flagged (a flagged query or URL
that ran; its results are judged by the content check).
Writes <session>/contamination.json and contamination_<blocklist version>.json. Never reads ground-truth answers.

  python scripts/audit_contamination.py <session-or-runs-dir> [...]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from minpilot.data.gaia import load_task
from minpilot.tools import blocklist

URL = re.compile(r"https?://[^\s\"'<>)\]]+")


def _lines(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def _text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        c = "\n".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""


def _external_part(txt: str) -> str:
    return re.sub(r'^Search results for ".*?":\n', "", txt, count=1, flags=re.S)


QUOTE_WINDOW, QUOTE_STEP = 50, 1


def quotes_question_anywhere(text: str, question: str) -> bool:
    """Audit-only check, stricter than the live blocklist (which matches only the question's first 70 letters and
    digits): any 50-character window of the question's letters and digits appears in the text."""
    q, t = blocklist._squash(question), blocklist._squash(text)
    if len(q) < QUOTE_WINDOW:
        return False
    return any(q[i:i + QUOTE_WINDOW] in t for i in range(0, len(q) - QUOTE_WINDOW + 1, QUOTE_STEP))


def audit_run(rd: Path, question: str, allowed: tuple[str, ...]) -> dict:
    store = {r["h"]: r["m"] for r in _lines(rd / "messages.jsonl")}
    seen_by = {}
    for c in _lines(rd / "llm_calls.jsonl"):
        if c.get("status") == "started":
            continue
        for h in c.get("messages") or []:
            seen_by.setdefault(h, {k: c.get(k) for k in ("stage", "delegation", "worker", "model_key")})
    findings = []
    for h, m in store.items():
        if m.get("role") != "tool":
            continue
        txt = _external_part(_text(m))
        reason = blocklist.content_block_reason(txt, question, allowed=allowed)
        if not reason and quotes_question_anywhere(txt, question):
            reason = "quotes_task_question_window (audit only)"
        urls = sorted({u for u in URL.findall(txt) if blocklist.url_block_reason(u)})
        if reason or urls:
            findings.append({"kind": "model_input", "class": "confirmed_exposure", "reason": reason,
                             "blocked_urls": urls[:5], "seen_by": seen_by.get(h), "excerpt": txt[:300]})
    for t in _lines(rd / "tool_calls.jsonl"):
        if t.get("status") == "started":
            continue
        for url, why in zip(t.get("blocked_results") or [], t.get("blocked_reasons") or []):
            findings.append({"kind": "search_result", "class": "filtered_result", "reason": why, "url": url,
                             "stage": t.get("stage")})
        args = t.get("args") or {}
        q, u = args.get("query"), args.get("url")
        reason = (blocklist.query_block_reason(q) if q else None) or (blocklist.url_block_reason(u) if u else None)
        if reason:
            findings.append({"kind": "request", "class": "blocked_attempt" if t.get("blocked") else "executed_flagged",
                             "reason": reason, "tool": t.get("tool"), "arg": q or u, "stage": t.get("stage")})
    classes = Counter(f["class"] for f in findings)
    return {"contaminated": classes["confirmed_exposure"] > 0, "counts": dict(classes), "findings": findings[:50]}


def main(paths: list[Path]) -> None:
    for sess in paths:
        report = {}
        for rj in sorted(sess.rglob("run.json")):
            rd = rj.parent
            if "scratch" in rd.parts or "checkpoints" in rd.parts:
                continue
            run = json.loads(rj.read_text())
            task = load_task(run["task_id"])
            att = rd / "work" / "attachments"
            names = tuple(p.name for p in att.iterdir()) if att.is_dir() else ()
            # the run's own task id appears in its own attachment names and paths: not a leak
            r = audit_run(rd, task.question, names + (run["task_id"],))
            report[str(rd.relative_to(sess))] = r
            reasons = Counter(f.get("reason") for f in r["findings"])
            print(f"{run['task_id'][:8]} {rd.name[-28:]:28s} contaminated={r['contaminated']} {r['counts']} "
                  f"{dict(reasons)}")
        out = json.dumps({"blocklist_version": blocklist.BLOCKLIST_VERSION, "runs": report}, indent=1,
                         ensure_ascii=False)
        (sess / "contamination.json").write_text(out)
        (sess / f"contamination_{blocklist.BLOCKLIST_VERSION}.json").write_text(out)


if __name__ == "__main__":
    main([Path(a) for a in sys.argv[1:]])
