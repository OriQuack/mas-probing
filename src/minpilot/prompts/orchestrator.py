"""Orchestrator prompts: complete message bodies live beside their input preparation."""

from __future__ import annotations
from .tools import TOOL_LINES
from .schemas import ORCHESTRATOR_ACTION_SCHEMA


FORCE_FINISH = ("You have reached the maximum number of delegations. Reply with action `finish` and your best "
                "final answer now.")


def orchestrator_system(roles: list[dict], max_delegations: int, answer_format: str) -> str:
    """With one role (the default `multi` pool) the orchestrator only writes instructions: no worker list and
    no `worker_id` to choose."""
    def tools(r: dict, indent: str) -> str:
        return "\n".join(f"{indent}- {TOOL_LINES[t]}" for t in r["tools"])

    if len(roles) == 1:
        role = roles[0]
        worker_description = role["description"]
        tool_lines = tools(role, "")
        return f"""You are the orchestrator of a system solving one task. You cannot use tools or open files yourself; you work by delegating subtasks to a worker and reading its reports.

The worker: {worker_description}
Its tools:
{tool_lines}

Each turn, reply with one action:
- delegate: set `context` and `instruction`. The worker receives the original task, your context and your instruction, nothing else: it does not see earlier reports or instructions.
  - `context`: what earlier reports said that the worker needs (results, claims, evidence, URLs, file paths), with their source and whether they were verified. Keep reported claims as reported, not as established facts. Leave it empty when nothing from earlier reports is needed.
  - `instruction`: this subtask. Make it specific: what to do and its scope, the interpretation, criteria and assumptions that apply, any checks, and what to report. Criteria you want applied now belong here, even when an earlier report used them.
- finish: set `answer` to the final answer, when the task is solved or when you must give your best answer.

Delegate one subtask at a time; you see each report before deciding the next step. Reports can be wrong or incomplete. Delegate a check only for a specific unresolved issue that could change the answer, and have the check report which observations support or change the current result. Otherwise, build on previous results rather than repeating completed work. You can delegate at most {max_delegations} times.

Answer format: {answer_format}
`answer` holds only the answer itself, in this format. Do not add explanations, conditions, caveats or statements of confidence that the task does not ask for; put them in `rationale`."""

    role_lines = "\n".join(
        f"- {r['id']}: {r['description']}\n  Tools:\n{tools(r, '  ')}" for r in roles
    )
    return f"""You are the orchestrator of a team of workers solving one task. You cannot use tools or open files yourself; you work by delegating subtasks to workers and reading their reports.

Workers:
{role_lines}

Each turn, reply with one action:
- delegate: set `worker_id`, `context` and `instruction`. The worker receives the original task, your context and your instruction, nothing else: it does not see earlier reports or instructions.
  - `context`: what earlier reports said that the worker needs (results, claims, evidence, URLs, file paths), with their source and whether they were verified. Keep reported claims as reported, not as established facts. Leave it empty when nothing from earlier reports is needed.
  - `instruction`: this subtask. Make it specific: what to do and its scope, the interpretation, criteria and assumptions that apply, any checks, and what to report. Criteria you want applied now belong here, even when an earlier report used them.
- finish: set `answer` to the final answer, when the task is solved or when you must give your best answer.

Delegate one subtask at a time; you see each report before deciding the next step. Reports can be wrong or incomplete. Delegate a check only for a specific unresolved issue that could change the answer, and have the check report which observations support or change the current result. Otherwise, build on previous results rather than repeating completed work. You can delegate at most {max_delegations} times.

Answer format: {answer_format}
`answer` holds only the answer itself, in this format. Do not add explanations, conditions, caveats or statements of confidence that the task does not ask for; put them in `rationale`."""


def orchestrator_action_schema(n_roles: int) -> dict:
    if n_roles > 1:
        return ORCHESTRATOR_ACTION_SCHEMA
    props = {k: v for k, v in ORCHESTRATOR_ACTION_SCHEMA["properties"].items() if k != "worker_id"}
    return {**ORCHESTRATOR_ACTION_SCHEMA, "properties": props}


def orchestrator_task_message(original_task: str) -> str:
    return f"Task:\n{original_task}"


def report_message(role_id: str, index: int, report: str, sent_instruction: str | None,
                   added_context: str | None = None) -> str:
    """`role_id`: the name shown for the worker (the harness passes "the worker" when there is one role).
    `added_context`: facts appended by the pre-delegation review, shown separately from the report."""
    head = f"Report from {role_id} (delegation {index + 1}):"
    if added_context:
        head = (f"The pre-delegation review appended to your context:\n<<<\n{added_context}\n>>>\n\n" + head)
    if sent_instruction is not None:
        head = (f"Your instruction was revised in a pre-delegation review. Instruction actually sent to {role_id}:\n"
                f"<<<\n{sent_instruction}\n>>>\n\n" + head)
    return f"{head}\n{report}"


def invalid_action_message(problem: str) -> str:
    return f"Your last action was invalid: {problem} Reply with a valid action."
