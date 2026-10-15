"""Pre-execution worker prompts and probe-answer parsing."""

from __future__ import annotations
from .tools import TOOL_LINES


PROBE_LABELS = ("understanding", "plan")

PROBE_TOOL_LIMIT_REACHED = (
    "You have reached your tool-call limit for this probe request. Do not call tools any more; "
    "answer the two questions now, marking the steps you checked with `observed:` and leaving the rest as planned steps."
)


def probe_system(system_prompt: str, tools: tuple[str, ...]) -> str:
    tool_lines = "\n".join(f"- {TOOL_LINES[t]}" for t in tools)
    return f"""{system_prompt}

Explain how you would carry out a proposed assignment with your available capabilities. The orchestrator compares the workers' answers to choose a worker for the assignment and to decide what its execution request should make clear or correct.

## Explain your intended approach
You receive selected context from earlier work and a proposed assignment with two questions: how you understand the assignment and how you would carry it out. The first request of this conversation gives the original task. You keep this conversation and your workspace for the whole run; your earlier requests, reports and tool results remain in it. The orchestrator's conversation and other workers' conversations are not included. Preserve the original task's target and conditions.

Context may contain errors or unverified claims. If a step of your plan uses a context claim, say in that step whether you would check it.

## Stay within the probe
Answer the two questions rather than carrying out the assignment. Use tools only if the request permits them, and only to check a specific step of your plan, such as whether a file has the expected structure or whether a method works on a small part of the data. Do not carry out the full assignment to obtain its answer; if a permitted check directly reveals the answer, write it in that step's `observed:` line with its source. Separate actual observations, with their sources, from inferences and expectations. Files you create remain in your workspace for your later requests; other workers receive only what your report states. Put reusable findings, sources and reproduction steps in your report.

Your tools:
{tool_lines}
Files are referenced by paths relative to the working directory; task attachments are under attachments/."""


def probe_tool_policy(tools_allowed: bool, max_tool_calls: int) -> str:
    if not tools_allowed:
        return "Do not use tools or execute the subtask."
    return f"""You may make up to {max_tool_calls} tool calls to check specific steps of your plan.
When reporting an observation, include what you found and its source."""


def probe_instruction(draft: str, tools_allowed: bool, max_tool_calls: int) -> str:
    """The probe request's instruction, sent with the context; a worker's first request also carries the original task."""
    return f"""Before carrying out this assignment, answer two questions: how you understand it and how you would carry it out.
{probe_tool_policy(tools_allowed, max_tool_calls)}

Assignment:
<<<
{draft}
>>>

Use the two labels below. Keep each item short.
For a step checked with tools, put `observed:` followed by the actual finding and its source in that step; distinguish it from steps you have not performed. If a check reveals the answer, write it in that step's `observed:` line with its source.

understanding:
What the assignment asks for and which conditions of the original task apply to it, as you understand them.

plan:
The steps you would take to carry out the assignment. Include the methods and sources you would use. One line per step."""


def parse_probe(text: str) -> dict | None:
    """The two labelled items of a probe answer, for the log (the analysis reads the answer text). None when no
    label is found. understanding: a string; plan: a list of strings (bullets stripped)."""
    import re

    out: dict = {}
    cur = None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*[#*_\s]*(understanding|plan)[*_\s]*:[*_\s]*(.*)$", line, re.I)
        if m:
            cur = m.group(1).lower()
            out[cur] = [m.group(2).strip()] if m.group(2).strip() else []
        elif cur and line.strip():
            out[cur].append(line.strip())
    if not out:
        return None
    none = re.compile(r"^\(?(none|n/a|no \w+)\.?\)?$", re.I)

    def items(lines):
        xs = [re.sub(r"^([-*•]|\d+[.)])\s+", "", s).strip() for s in lines]
        return [x for x in xs if x and not none.match(x)]

    return {"understanding": " ".join(out.get("understanding", [])).strip(),
            **{k: items(out.get(k, [])) for k in PROBE_LABELS[1:]}}
