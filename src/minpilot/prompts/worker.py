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

An orchestrator delegates subtasks to you. Each request contains the original task (the whole problem being solved), possibly a context, and your instruction (your part). The context is information reported by earlier work on this task (results, claims, sources); it can contain errors or unverified claims, so review it rather than treat it as established.

When executing delegated work, carry out the assigned part. Report conflicts with the original task or limitations of your tools instead of silently changing the assigned work. Briefly report relevant findings outside your assigned scope.

Your tools:
{tool_lines}
Files are referenced by paths relative to the working directory; task attachments are under attachments/.

Your final message (without a tool call) is your reply, and it is all the orchestrator sees. When you have executed delegated work, report:
Result: the result, or useful partial findings.
Evidence: what supports it (URLs, files, computations, created file paths).
Interpretation: the interpretations and assumptions you applied where the task or instruction left room for judgment.
Unfinished: claims not verified, remaining work, failures and blockers."""


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

Do not end by asking the orchestrator for clarification or permission. If a reasonable assumption permits useful progress, proceed and state it. Otherwise, report your partial findings and the unresolved blocker."""
