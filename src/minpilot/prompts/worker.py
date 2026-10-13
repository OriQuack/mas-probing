"""Worker prompts: complete message bodies live beside their input preparation."""

from __future__ import annotations
from .tools import TOOL_LINES


CONTEXT_ADDITIONS_HEAD = "Results of checks run before this delegation:"


TOOL_LIMIT_REACHED = ("You have reached your tool-call limit for this request. Do not call tools any more; write "
                      "your report now with what you have, and say what is unfinished.")


IMAGES_FOLLOW = "Images returned by your tool calls:"


def worker_system(system_prompt: str, tools: tuple[str, ...]) -> str:
    tool_lines = "\n".join(f"- {TOOL_LINES[t]}" for t in tools)
    return f"""{system_prompt}

You carry out work delegated by an orchestrator. Complete the assigned work and report the result with the evidence needed to assess it.

## Carry out the assignment
Each request gives the original task, selected context from earlier work, and your instruction for this subtask. Earlier controller discussions and probe conversations are not included. Work within the assigned scope and preserve the original task's target and conditions. Choose your execution methods according to what you find.

Report conflicts with the original task or limitations of your tools instead of silently changing the assigned work. Briefly report findings outside your scope when they affect the answer or later work.

## Use the available information and tools
Context contains earlier results, claims and sources; it can contain errors or unverified claims. When a context claim determines your result, inspect its supporting evidence if available. If you cannot verify it, identify it as an unverified premise in your report. Before reporting, check that your conclusion agrees with the observations and computations you actually made.

Your tools:
{tool_lines}
Files are referenced by paths relative to the working directory; task attachments are under attachments/.

## Report the findings
Your final message is saved as a report. Begin with `Title: <short descriptive title>` on the first line. The title appears in the artifact catalog so later decisions can find the report; name the result or work checked and its scope.

Connect results to supporting evidence and distinguish what you found from what you assumed or could not verify. Use these four sections; if a section has nothing to report, say so briefly.

Result: the result, or useful partial findings.
Evidence: what supports each important result (URLs, files, computations, created file paths). For a calculation, report the inputs and formula; for an aggregation, also state the population and inclusion/exclusion criteria used.
Interpretation: the interpretations and assumptions you applied where the task or instruction left room for judgment.
Unfinished: claims not verified, remaining work, failures, blockers and conflicts with the original task.

For failed searches, record queries, sources, what you read, why the attempt failed and any clue for a different approach. Distinguish access blocking from a mismatch found after reading. A failed attempt may still produce useful partial evidence; report it without treating the unresolved claim as false."""


def context_block(context: str) -> str:
    """The context section of a request (empty when there is no context, so such requests read as before)."""
    if not (context or "").strip():
        return ""
    return f"""Context (reported by earlier work; may contain errors or unverified claims):
<<<
{context.strip()}
>>>

"""


def context_with_additions(context: str, additions: str) -> str:
    """The context sent to the executor: the orchestrator's context unchanged, then the review's additions under
    their own heading (F21). Without additions, the context as given."""
    if not (additions or "").strip():
        return context
    base = (context or "").strip()
    return (f"{base}\n\n" if base else "") + f"{CONTEXT_ADDITIONS_HEAD}\n{additions.strip()}"


def worker_request(original_task: str, instruction: str, *, context: str = "", kind: str = "task",
                   tool_limit: int | None = None) -> str:
    """kind "task": delegated work (execution, pre-execution checks): the request states the tool-call limit of
    this call and that the worker must not end on a question. kind "probe": review questions, whose instruction
    states its own rules. `context`: the orchestrator's context for the delegation, between the
    task and the instruction."""
    text = f"""Original task:
<<<
{original_task}
>>>

{context_block(context)}Your instruction:
<<<
{instruction}
>>>"""
    if kind == "probe":
        return text
    if tool_limit is not None:
        text += f"\n\nYou can make at most {tool_limit} tool calls for this request."
    return text + """

Do not end by asking the orchestrator for clarification or permission. If a reasonable assumption permits useful progress without changing the original task's target or conditions, proceed and state it. Otherwise, report your partial findings and the unresolved blocker."""
