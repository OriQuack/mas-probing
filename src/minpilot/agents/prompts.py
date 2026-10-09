"""All prompts of min_pilot, in one place, with two versions recorded per run:
- PROMPTS_VERSION: the orchestrator and worker prompts (what a run and its checkpoints are made of; a restore
  refuses a different version).
- REFINER_PROMPTS_VERSION: the probe, review, analysis, verification and rewrite prompts. They act only after a
  checkpoint, so a restore may use a newer version than the run that recorded the checkpoint.

Written for this framework; nothing is taken from OWL's prompts. The answer-format rules are the benchmark's
(GAIA's, in data/gaia.py) and are passed in by the harness.
"""

from __future__ import annotations

# v2 (2026-10-09): the answer rules come from the benchmark; `answer` holds only the answer (no explanation,
#     conditions, caveats or confidence unless the task asks); worker tool lines for tools v3 (decisions F16, K17)
# v3 (2026-10-09): worker tool line for read_url names the on-or-before snapshot rule (tools v4, K8)
# v4 (2026-10-09): with one role (the `single` pool, now the default) the orchestrator prompt and action schema
#     have no worker list and no `worker_id`; the multi-role prompt is unchanged (decision P6)
# v5 (2026-10-09): orchestrator: rationale states what is established / unresolved / why now; checks only for
#     doubtful important results, otherwise build on earlier results; worker tools described with what they return.
#     Worker: do the assigned part, report conflicts and tool limits instead of silently changing the work, report
#     relevant findings outside the scope; Result / Evidence / Assumptions / Unfinished report; no ending on a
#     request for clarification or permission. Tool lines: read_url returns a reader's answer, read_url_text the
#     extracted text (decision F18). Delegated work (execution, checks) gets the call's tool-call limit and the
#     no-question rule in its request, not in the system prompt (probes do not); the task text carries the run
#     reference date (F19)
PROMPTS_VERSION = "v5"
# r2 (2026-10-08): the task's premises are given; issues never turn the subtask into "is the task answerable?"
# r3 (2026-10-09): the rewrite prompt names the executing worker's role and tools (review: a rewrite must stay
#     doable by the fixed executor)
# r4 (2026-10-09): r2 reverted in the analysis (premises and doubts may be raised and checked again); the rewrite
#     keeps the subtask's goal, corrects conflicts with the task, and turns contradictions into checks and
#     conditional steps instead of a validity assessment (decisions R14)
# r5 (2026-10-09): probe questions made specific (expected output; stated vs introduced assumptions; task-specific
#     failures); probe preamble "do not execute, no tools"; B sees the worker's actual system prompt and probe
#     message (same functions as C) and predicts without "be critical / include errors" or the model name; the
#     analysis targets consequential issues, separates conflicting from compatible answers, compares independent
#     answer sets, and leaves checks the executor can do to execution (decision `defer_to_execution`; checks run
#     only for `needs_verification` issues); minimal rewrite rules (decision R20)
REFINER_PROMPTS_VERSION = "r5"

TOOL_LINES = {
    "web_search": "web_search: search the web (Google results); returns titles, URLs and snippets",
    "read_url": ("read_url: ask a question about a web page or online document; returns an answer written by a "
                 "reader model from the page's full text, not the text itself (optionally from an archived snapshot: "
                 "by default the latest on or before a date)"),
    "read_url_text": "read_url_text: read a web page or online document; returns the extracted raw text, page by page",
    "find_in_url": ("find_in_url: find a string in a web page or online document; returns each match with the text "
                    "around it"),
    "read_file": "read_file: read a file in the working directory (documents, spreadsheets, zips, text)",
    "view_image": "view_image: look at an image file or image URL",
    "run_python": "run_python: run Python in the working directory (no network)",
}

# -- original task --------------------------------------------------------------------------------
def original_task_text(question: str, attachment: str | None, reference_date: str | None = None) -> str:
    """The task as every model sees it. `reference_date` (YYYY-MM-DD) is fixed when a run starts and kept by its
    checkpoints, so every condition restored from one sees the same date (decision F19)."""
    text = question if not attachment else f"{question}\n\nAttached file: {attachment}"
    if reference_date:
        text += (f"\n\nRun reference date: {reference_date} (today's date for this run; a date or time stated in the "
                 "task takes precedence).")
    return text


# -- orchestrator ---------------------------------------------------------------------------------
def orchestrator_system(roles: list[dict], max_delegations: int, answer_format: str) -> str:
    """With one role (the default `single` pool) the orchestrator only writes instructions: no worker list and
    no `worker_id` to choose (decision P6)."""
    def tools(r: dict, indent: str) -> str:
        return "\n".join(f"{indent}- {TOOL_LINES[t]}" for t in r["tools"])

    if len(roles) == 1:
        r = roles[0]
        intro = f"""You are the orchestrator of a system solving one task. You cannot use tools or open files \
yourself; you work by delegating subtasks to a worker and reading its reports.

The worker: {r['description']}
Its tools:
{tools(r, "")}"""
        delegate = "set `context` and `instruction`"
    else:
        lines = "\n".join(f"- {r['id']}: {r['description']}\n  Tools:\n{tools(r, '  ')}" for r in roles)
        intro = f"""You are the orchestrator of a team of workers solving one task. You cannot use tools or open files \
yourself; you work by delegating subtasks to workers and reading their reports.

Workers:
{lines}"""
        delegate = "set `worker_id`, `context` and `instruction`"
    return f"""{intro}

Each turn, reply with one action:
- delegate: {delegate}. The worker receives the original task, your context and your \
instruction, nothing else: it does not see earlier reports or instructions.
  - `context`: what earlier reports said that the worker needs (results, claims, evidence, URLs, file paths), \
with their source and whether they were verified. Keep reported claims as reported, not as established facts. \
Leave it empty when nothing from earlier reports is needed.
  - `instruction`: this subtask. Make it specific: what to do and its scope, the interpretation, criteria and \
assumptions that apply, any checks, and what to report. Criteria you want applied now belong here, even when an \
earlier report used them.
- finish: set `answer` to the final answer, when the task is solved or when you must give your best answer.

Delegate one subtask at a time; you see each report before deciding the next step. Reports can be wrong or \
incomplete. When an important result is in doubt, have it checked by delegating a check. Otherwise, build on \
previous results rather than repeating completed work. You can delegate at most {max_delegations} times.

Answer format: {answer_format}
`answer` holds only the answer itself, in this format. Do not add explanations, conditions, caveats or statements \
of confidence that the task does not ask for; put them in `rationale`."""


ORCHESTRATOR_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string", "description": "Briefly state what is established, what remains unresolved, "
                                                       "and why this action is appropriate now."},
        "action": {"type": "string", "enum": ["delegate", "finish"]},
        "worker_id": {"type": "string"},
        "context": {"type": "string", "description": "Information from earlier reports that the worker needs, with "
                                                    "source and verification status; empty if none."},
        "instruction": {"type": "string"},
        "answer": {"type": "string", "description": "Only the final answer, in the required format."},
    },
    "required": ["rationale", "action"],
}


def orchestrator_action_schema(n_roles: int) -> dict:
    if n_roles > 1:
        return ORCHESTRATOR_ACTION_SCHEMA
    props = {k: v for k, v in ORCHESTRATOR_ACTION_SCHEMA["properties"].items() if k != "worker_id"}
    return {**ORCHESTRATOR_ACTION_SCHEMA, "properties": props}


def orchestrator_task_message(original_task: str) -> str:
    return f"Task:\n{original_task}"


def report_message(role_id: str, index: int, report: str, sent_instruction: str | None) -> str:
    """`role_id`: the name shown for the worker (the harness passes "the worker" when there is one role)."""
    head = f"Report from {role_id} (delegation {index + 1}):"
    if sent_instruction is not None:
        head = (f"Your instruction was revised in a pre-delegation review. Instruction actually sent to {role_id}:\n"
                f"<<<\n{sent_instruction}\n>>>\n\n" + head)
    return f"{head}\n{report}"


FORCE_FINISH = ("You have reached the maximum number of delegations. Reply with action `finish` and your best "
                "final answer now.")


def invalid_action_message(problem: str) -> str:
    return f"Your last action was invalid: {problem} Reply with a valid action."


# -- workers --------------------------------------------------------------------------------------
def worker_system(system_prompt: str, tools: tuple[str, ...]) -> str:
    tool_lines = "\n".join(f"- {TOOL_LINES[t]}" for t in tools)
    return f"""{system_prompt}

An orchestrator delegates subtasks to you. Each request contains the original task (the whole problem being \
solved), possibly a context, and your instruction (your part). The context is information reported by earlier work \
on this task (results, claims, sources); it can contain errors or unverified claims, so review it rather than treat \
it as established.

When executing delegated work, carry out the assigned part. Report conflicts with the original task or \
limitations of your tools instead of silently changing the assigned work. Briefly report relevant findings outside \
your assigned scope.

Your tools:
{tool_lines}
Files are referenced by paths relative to the working directory; task attachments are under attachments/.

Your final message (without a tool call) is your reply, and it is all the orchestrator sees. When you have \
executed delegated work, report:
Result: completed or useful partial findings.
Evidence: supporting URLs, files, computations and created file paths.
Assumptions: assumptions made and claims not verified.
Unfinished: remaining work, failures and blockers."""


def context_block(context: str) -> str:
    """The context section of a request (empty when there is no context, so such requests read as before)."""
    if not (context or "").strip():
        return ""
    return (f"Context (reported by earlier work; may contain errors or unverified claims):\n<<<\n{context.strip()}"
            "\n>>>\n\n")


def worker_request(original_task: str, instruction: str, *, context: str = "", kind: str = "task",
                   tool_limit: int | None = None) -> str:
    """kind "task": delegated work (execution, pre-execution checks): the request states the tool-call limit of
    this call and that the worker must not end on a question. kind "probe": review questions, whose instruction
    states its own rules (decision F18). `context`: the orchestrator's context for the delegation, between the
    task and the instruction (decision F21)."""
    text = (f"Original task:\n<<<\n{original_task}\n>>>\n\n{context_block(context)}"
            f"Your instruction:\n<<<\n{instruction}\n>>>")
    if kind == "probe":
        return text
    if tool_limit is not None:
        text += f"\n\nYou can make at most {tool_limit} tool calls for this request."
    return text + ("\n\nDo not end by asking the orchestrator for clarification or permission. If a reasonable "
                   "assumption permits useful progress, proceed and state it. Otherwise, report your partial findings "
                   "and the unresolved blocker.")


TOOL_LIMIT_REACHED = ("You have reached your tool-call limit for this request. Do not call tools any more; write "
                      "your report now with what you have, and say what is unfinished.")
IMAGES_FOLLOW = "Images returned by your tool calls:"


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
