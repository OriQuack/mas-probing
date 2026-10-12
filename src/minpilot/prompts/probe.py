"""Pre-execution worker prompts and probe-answer parsing."""

from __future__ import annotations
from .tools import TOOL_LINES


PROBE_LABELS = ("understanding", "plan", "assumptions", "risks")

PROBE_TOOL_LIMIT_REACHED = (
    "You have reached your tool-call limit for this review. Do not call tools any more; "
    "answer the review questions now, distinguishing observations from assumptions and remaining uncertainties."
)


def probe_system(system_prompt: str, tools: tuple[str, ...]) -> str:
    tool_lines = "\n".join(f"- {TOOL_LINES[t]}" for t in tools)
    return f"""{system_prompt}

Explain how you would carry out a proposed assignment with your available capabilities. The orchestrator compares these responses to choose an executor and decide whether the instruction needs a change.

## Explain your intended approach
You receive the original task, selected context from earlier work, and a proposed instruction with four questions. Earlier controller discussions and other workers' responses are not included. Preserve the original task's target and conditions, and distinguish assumptions you would introduce from conditions already given.

Context may contain errors or unverified claims. If your approach depends on a context claim, say whether you would check it or rely on it as an unverified premise.

## Respect the review boundary
Answer the review questions rather than completing the assignment. Use tools only if the request permits them, and only to check a specific assumption or risk in your proposed approach. Do not undertake the full assignment to obtain its answer; if a permitted check directly reveals an answer, report it with its evidence. Separate actual observations, with their sources, from inferences and expectations. Your workspace is a separate copy: files you create are not transferred to the executor. Put reusable findings, sources and reproduction steps in your report.

Your tools:
{tool_lines}
Files are referenced by paths relative to the working directory; task attachments are under attachments/."""


def probe_tool_policy(tools_allowed: bool, max_tool_calls: int) -> str:
    if not tools_allowed:
        return "Do not use tools or execute the subtask."
    return f"""You may make up to {max_tool_calls} tool calls to check specific assumptions or risks in your proposed approach.
When reporting an observation, include what you found and its source."""


def probe_instruction(draft: str, tools_allowed: bool, max_tool_calls: int) -> str:
    """The probe (sent with the original task and the context, as every request)."""
    return f"""Before executing the subtask, explain how you would approach it.
{probe_tool_policy(tools_allowed, max_tool_calls)}

Subtask instruction:
<<<
{draft}
>>>

Begin with `Title: <short descriptive title>` on the first line. The title appears in the artifact catalog; identify the proposed approach or its main constraint. Use the four labels below. Keep each item short.
Empty assumptions and risks lists are valid. Do not invent items to fill the form.
For an item checked with tools, put `observed:` followed by the actual finding and its source within the relevant section; distinguish it from steps you have not performed.

understanding:
One sentence stating the result you would produce and its scope.

plan:
The steps you would take to produce the result. Include the methods and sources you would use. One line per step.

assumptions:
The interpretations or premises your plan relies on that are not established by the original task or verified evidence, including unverified premises in the context or instruction. State the assumption and where it is used in the plan.

risks:
Specific ways the proposed plan could produce an incorrect result or fail to finish, and how you would handle them. Avoid generic possibilities without a concrete reason to expect them here."""


def parse_probe(text: str) -> dict | None:
    """The four labelled items of a probe answer, for the log (the analysis reads the answer text). None when no
    label is found. understanding: a string; plan, assumptions, risks: lists of strings (bullets stripped)."""
    import re

    out: dict = {}
    cur = None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*[#*_\s]*(understanding|assumptions|risks|plan)[*_\s]*:[*_\s]*(.*)$", line, re.I)
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


def followup_message(question: str) -> str:
    return f"Follow-up question from the orchestrator (still do not execute the subtask):\n{question}"


