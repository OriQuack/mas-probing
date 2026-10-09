"""Refiner prompts r5, frozen (decision R21): the "earlier refiner" arm of the stage-1 comparison
(`prompts: r5` in a condition). Copied verbatim from prompts.py at r5; do not edit. The current refiner prompts
(r6) are in prompts.py. The worker system prompt and request framing are shared (they are PROMPTS_VERSION's).
"""

from __future__ import annotations

from minpilot.agents.prompts import worker_request, worker_system

VERSION = "r5"
DECISIONS = ("resolved_from_task", "needs_verification", "defer_to_execution", "not_relevant")

# -- probing (C) and simulated probing (B) ------------------------------------------------------
PROBE_QUESTION_TEXT = {
    "understanding": "Understanding: What do you understand this subtask asks you to do? State its scope, targets "
                     "and expected output.",
    "assumptions": "Assumptions: Distinguish conditions stated in the original task or instruction from additional "
                   "assumptions you introduce. For each important additional assumption, what would change if it "
                   "were different?",
    "failure": "Failure: What task-specific problems could prevent successful execution, such as missing inputs, "
               "tool limitations, or a conflict between the instruction and the original task? How would you "
               "respond?",
    "plan": "Plan: In what steps and with what methods would you carry out the whole subtask?",
}


def probe_questions_block(questions: tuple[str, ...]) -> str:
    return "\n".join(f"{i}. {PROBE_QUESTION_TEXT[q]}" for i, q in enumerate(questions, 1))


def probe_instruction(draft: str, questions: tuple[str, ...], tools_allowed: bool, max_tool_calls: int,
                      with_context: bool = False) -> str:
    """`with_context`: the request carries a context (F21); the probe then names it as an input."""
    src = "the original task, the context, the instruction" if with_context else "the original task, the instruction"
    tools = (f"You may use your tools only for quick checks that help you answer (at most {max_tool_calls} calls). "
             f"Answer from {src}, what you know about your tools and those checks."
             if tools_allowed else f"Do not use tools during this probe. Answer from {src}, and what you know about "
             "your tools.")
    given = " (with the context above)" if with_context else ""
    return f"""The orchestrator is about to give you the subtask instruction below{given}. Before it is executed, it \
asks how you read it. Do not execute the subtask. {tools}

Subtask instruction:
<<<
{draft}
>>>

Answer each question about this subtask:
{probe_questions_block(questions)}
Be concrete and brief."""


def followup_message(question: str) -> str:
    return f"Follow-up question from the orchestrator (still do not execute the subtask):\n{question}"


def simulate_system() -> str:
    return ("You are the orchestrator of a system solving a task. Before delegating a subtask, you review your "
            "instruction by predicting how the worker who would receive it would answer questions about it.")


def simulate_request(original_task: str, draft: str, worker: dict, questions: tuple[str, ...],
                     context: str = "") -> str:
    """The worker's system prompt and the probe message (with the same context) are built by the same functions as
    C's real probe (no tools while answering, as in C_probe). `worker["system_prompt"]` is the worker's registered
    prompt; without it the role description stands in."""
    system = worker_system(worker.get("system_prompt") or worker["description"], tuple(worker["tools"]))
    message = worker_request(original_task, probe_instruction(draft, questions, False, 0, bool(context.strip())),
                             context=context, kind="probe")
    return f"""The worker who would receive your instruction runs with the system prompt below and would be sent \
the message below.

===== worker's system prompt =====
{system}
===== end of system prompt =====

===== message to the worker =====
{message}
===== end of message =====

Predict the answers this worker would most plausibly give to the message above, in the worker's voice. Be concrete \
and brief."""


def analyze_system() -> str:
    return ("You are the orchestrator of a system solving a task. You review a subtask instruction before delegating "
            "it. You cannot use tools yourself; facts can only be checked by delegating checks to workers.")


def review_context_block(context: str) -> str:
    """The delegation's context as the refiner sees it (read-only; F21). Empty when there is none."""
    if not (context or "").strip():
        return ""
    return ("Context sent with the instruction (reported by earlier work; it is passed to the worker unchanged and "
            f"may contain errors or unverified claims):\n<<<\n{context.strip()}\n>>>\n\n")


def analyze_request(original_task: str, draft: str, target: dict, responses: list[dict], source: str,
                    max_verifications: int, roles: list[dict], followups_allowed: int, context: str = "") -> str:
    resp = "\n\n".join(f"[{r['id']}] ({r['who']})\n{r['text']}" for r in responses)
    roles_txt = "\n".join(f"- {r['id']}: {r['description']} Tools: {', '.join(r['tools'])}." for r in roles)
    origin = ("given by the worker(s) who would receive it" if source == "probe"
              else "that you predicted for the worker who would receive it")
    follow = (f"\nYou may ask up to {followups_allowed} follow-up questions in total to the workers who answered "
              "(refer to an answer by its id), when an answer is unclear in a way that matters."
              if followups_allowed else "\nDo not ask follow-up questions (leave `followups` empty).")
    # independent answer sets (follow-up answers, ids "r1.f1", belong to their set)
    compare = ("\nThe answer sets above were given independently. Compare them: differences in interpretation or "
               "assumptions, steps missing from a plan, and mismatches in the risks named and how to handle them. "
               "Problems all answers missed are issues too."
               if len({r["id"].split(".")[0] for r in responses}) > 1 else "")
    has_ctx = bool((context or "").strip())
    ctx_issue = ("\nIssues can lie in the instruction or in the context it relies on (a reported claim that is wrong, "
                 "unverified or applied wrongly)." if has_ctx else "")
    receives = "the original task, the context and your check instruction" if has_ctx else \
        "the original task and your check instruction"
    return f"""Original task:
<<<
{original_task}
>>>

{review_context_block(context)}Subtask instruction to be sent to {target['role']}:
<<<
{draft}
>>>

Answers to review questions about this instruction, {origin}:
{resp}

Identify issues that can materially affect this subtask's result or feasibility. Judge them against the original \
task: neither agreement nor disagreement between answers decides what is correct.
When answers differ, distinguish conflicting interpretations from compatible alternatives. Compatible alternatives \
are not issues by themselves.
Also consider consequential omissions, unsupported assumptions and questionable premises of the task or the \
instruction, even when the answers agree.{ctx_issue}{compare}

For each issue choose a decision:
- resolved_from_task: the original task or the instruction settles it; give the resolution.
- needs_verification: a fact must be checked before execution, because the correct instruction depends on it.
- defer_to_execution: the executing worker can check it during execution and proceed according to the result; \
give, as the resolution, the check and how to proceed for each relevant outcome. Request no check for it.
- not_relevant: it does not affect this subtask's result or feasibility.
Request checks only for needs_verification issues, most important first; checks for other issues are not run. \
You may request up to {max_verifications} checks, each delegated to one of these workers (it receives {receives}; \
keep checks short and specific):
{roles_txt}{follow}
If there are no issues, return an empty list."""


ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": ["understanding", "assumption", "failure", "plan"]},
            "summary": {"type": "string"},
            "evidence": {"type": "string", "description": "Which answers (ids) show it, and how."},
            "decision": {"type": "string", "enum": ["resolved_from_task", "needs_verification", "defer_to_execution",
                                                    "not_relevant"]},
            "resolution": {"type": "string"},
        }, "required": ["id", "kind", "summary", "evidence", "decision", "resolution"]}},
        "followups": {"type": "array", "items": {"type": "object", "properties": {
            "response_id": {"type": "string"}, "question": {"type": "string"}},
            "required": ["response_id", "question"]}},
        "verifications": {"type": "array", "items": {"type": "object", "properties": {
            "issue_id": {"type": "string"}, "worker_id": {"type": "string"}, "instruction": {"type": "string"}},
            "required": ["issue_id", "worker_id", "instruction"]}},
    },
    "required": ["issues", "followups", "verifications"],
}


def verify_instruction(check: str) -> str:
    return ("This is a short check requested before the main subtask is delegated. Do only this check and report "
            f"what you found, with evidence.\n\nCheck:\n{check}")


def rewrite_request(original_task: str, draft: str, issues: list[dict], verifications: list[dict],
                    target: dict, context: str = "") -> str:
    """Only the instruction is rewritten; the context is shown read-only and passed on unchanged (F21)."""
    import json

    ver = "\n\n".join(f"[{v['issue_id']}] check by {v['worker_id']}: {v['instruction']}\nResult:\n{v['report']}"
                      for v in verifications) or "(none)"
    has_ctx = bool((context or "").strip())
    ctx_rule = ("- Only the instruction is rewritten; the context above is passed to the worker unchanged. Do not "
                "repeat it in the instruction. If a context claim is wrong or needs checking, say in the instruction "
                "which claim to check or replace, and how to proceed.\n" if has_ctx else "")
    sees = ("the original task, the context and this instruction" if has_ctx
            else "the original task and this instruction")
    return f"""Original task:
<<<
{original_task}
>>>

{review_context_block(context)}Current subtask instruction (it will be executed by {target['role']}, whose tools are: \
{', '.join(target['tools'])}):
<<<
{draft}
>>>

Issues found in the review:
{json.dumps(issues, ensure_ascii=False, indent=1)}

Verification results:
{ver}

Write the final version of the subtask instruction, once. Rules:
- Change only what is needed to address consequential issues. Preserve unaffected parts of the instruction. Do \
not add unrelated general advice or duplicate requirements.
- State supported verification findings that the executor needs; it will not see this review. Do not present \
unverified claims as facts.
- For issues deferred to execution (defer_to_execution), and needs_verification issues without a check result, \
include the check and how to proceed for each relevant outcome.
- Preserve the original task's requested goal. Questionable factual premises may be checked and discrepancies \
reported; do not silently replace the task with a different one.
{ctx_rule}- Keep the instruction self-contained (the worker sees only {sees}; do not paste the review) and doable by \
the executing worker with its tools.
- If no issue requires a change, return the current instruction unchanged and set `unchanged` to true."""


REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "instruction": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "string"}},
        "unchanged": {"type": "boolean"},
    },
    "required": ["instruction", "changes", "unchanged"],
}


# -- adapters (uniform calls from refine/review.py) --------------------------------------------------
def probe_for(draft: str, cfg, with_context: bool) -> str:
    return probe_instruction(draft, cfg.questions, cfg.probe_tools, cfg.probe_max_tool_calls, with_context)


def simulate_for(original_task: str, draft: str, worker: dict, cfg, context: str = "") -> str:
    return simulate_request(original_task, draft, worker, cfg.questions, context)

