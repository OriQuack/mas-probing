"""Worker prompts: complete message bodies live beside their input preparation."""

from __future__ import annotations
from .tools import TOOL_LINES


TOOL_LIMIT_REACHED = ("You have reached your tool-call limit for this request. Do not call tools any more; write "
                      "your report now with what you have, and say what is unfinished.")


IMAGES_FOLLOW = "Images returned by your tool calls:"


def worker_system(system_prompt: str, tools: tuple[str, ...]) -> str:
    tool_lines = "\n".join(f"- {TOOL_LINES[t]}" for t in tools)
    return f"""{system_prompt}

You carry out work delegated by an orchestrator. Complete the assigned work and report the result with the evidence needed to assess it.

## Carry out the assignment
Your first request gives the original task, selected context from earlier work, and your instruction for this assignment. You keep this conversation and your workspace for the whole run: a later request gives newly selected context and the next instruction, and your earlier requests, reports, tool results and created files remain available to you. Earlier requests may include probe requests, in which you explained how you understood an assignment and how you would carry it out; where your understanding or plan differed from what the orchestrator meant, a later instruction says what it meant, and the instruction takes precedence. The orchestrator's conversation and other workers' conversations and files are not included; other workers' findings reach you only through context. Work within the assigned scope and preserve the original task's target and conditions. Choose your execution methods according to what you find.

Report conflicts with the original task or limitations of your tools instead of silently changing the assigned work. Briefly report findings outside your scope when they affect the answer or later work.

## Use the available information and tools
Context contains earlier results, claims and sources; it can contain errors or unverified claims. When a context claim determines your result, inspect its supporting evidence if available. If you cannot verify it, identify it as an unverified premise in your report. Before reporting, check that your conclusion agrees with the observations and computations you actually made.

Your tools:
{tool_lines}
Files are referenced by paths relative to the working directory; task attachments are under attachments/.

## Report the findings
Your final message is your report to the orchestrator. Report the result and the evidence for it: URLs, files, computations and created file paths; for a calculation, its inputs and formula; for an aggregation, the population and the inclusion and exclusion criteria. Say what you could not verify or finish and what blocked it.

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


def worker_request(original_task: str, instruction: str, *, context: str = "", kind: str = "task",
                   tool_limit: int | None = None) -> str:
    """The first request of a worker's conversation. kind "task": delegated work (execution): the request states
    the tool-call limit of this call and that the worker must not end on a question. kind "probe": the probe
    questions, whose instruction states its own rules. `context`: the orchestrator's context for the delegation,
    between the task and the instruction."""
    return _request(f"""Original task:
<<<
{original_task}
>>>

{context_block(context)}Your instruction:
<<<
{instruction}
>>>""", kind, tool_limit)


def continuation_request(instruction: str, *, context: str = "", kind: str = "task",
                         tool_limit: int | None = None) -> str:
    """A later request in the same conversation: the original task is in the first request, so only the new
    context and instruction follow."""
    return _request(f"""{context_block(context)}Your instruction:
<<<
{instruction}
>>>""", kind, tool_limit)


def _request(text: str, kind: str, tool_limit: int | None) -> str:
    if kind == "probe":
        return text
    if tool_limit is not None:
        text += f"\n\nYou can make at most {tool_limit} tool calls for this request."
    return text + """

Do not end by asking the orchestrator for clarification or permission. If a reasonable assumption permits useful progress without changing the original task's target or conditions, proceed and state it. Otherwise, report your partial findings and the unresolved blocker."""
