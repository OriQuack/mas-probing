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
PROMPTS_VERSION = "v4"
# r2 (2026-10-08): the task's premises are given; issues never turn the subtask into "is the task answerable?"
# r3 (2026-10-09): the rewrite prompt names the executing worker's role and tools (review: a rewrite must stay
#     doable by the fixed executor)
# r4 (2026-10-09): r2 reverted in the analysis (premises and doubts may be raised and checked again); the rewrite
#     keeps the subtask's goal, corrects conflicts with the task, and turns contradictions into checks and
#     conditional steps instead of a validity assessment (decisions R14)
REFINER_PROMPTS_VERSION = "r4"

TOOL_LINES = {
    "web_search": "web_search: search the web (Google results)",
    "read_url": ("read_url: ask a question about a web page or online document; a reader model answers from its full "
                 "text (optionally an archived snapshot: by default the latest on or before a date)"),
    "read_url_text": "read_url_text: read a web page or online document as raw text, page by page",
    "find_in_url": "find_in_url: find a string in a web page or online document, with the text around it",
    "read_file": "read_file: read a file in the working directory (documents, spreadsheets, zips, text)",
    "view_image": "view_image: look at an image file or image URL",
    "run_python": "run_python: run Python in the working directory (no network)",
}

# -- original task --------------------------------------------------------------------------------
def original_task_text(question: str, attachment: str | None) -> str:
    if not attachment:
        return question
    return f"{question}\n\nAttached file: {attachment}"


# -- orchestrator ---------------------------------------------------------------------------------
def orchestrator_system(roles: list[dict], max_delegations: int, answer_format: str) -> str:
    """With one role (the default `single` pool) the orchestrator only writes instructions: no worker list and
    no `worker_id` to choose (decision P6)."""
    if len(roles) == 1:
        r = roles[0]
        intro = f"""You are the orchestrator of a system solving one task. You cannot use tools or open files \
yourself; you work by delegating subtasks to a worker and reading its reports.

The worker ({r['id']}): {r['description']} Tools: {', '.join(r['tools'])}."""
        delegate = "set `instruction`"
    else:
        lines = "\n".join(f"- {r['id']}: {r['description']} Tools: {', '.join(r['tools'])}." for r in roles)
        intro = f"""You are the orchestrator of a team of workers solving one task. You cannot use tools or open files \
yourself; you work by delegating subtasks to workers and reading their reports.

Workers:
{lines}"""
        delegate = "set `worker_id` and `instruction`"
    return f"""{intro}

Each turn, reply with one action:
- delegate: {delegate}. The worker receives the original task and your instruction, \
nothing else: it does not see earlier reports or instructions. Put into the instruction everything it needs \
from earlier results (values, URLs, file paths). Make the instruction specific: what to do and its scope, the \
interpretation and conditions that matter, and what to report.
- finish: set `answer` to the final answer, when the task is solved or when you must give your best answer.

Delegate one subtask at a time; you see each report before deciding the next step. Reports can be wrong or \
incomplete; have important claims checked when in doubt. You can delegate at most {max_delegations} times.

Answer format: {answer_format}
`answer` holds only the answer itself, in this format. Do not add explanations, conditions, caveats or statements \
of confidence that the task does not ask for; put them in `rationale`."""


ORCHESTRATOR_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string", "description": "Brief reason for this action."},
        "action": {"type": "string", "enum": ["delegate", "finish"]},
        "worker_id": {"type": "string"},
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

You are one worker in a team; an orchestrator delegates subtasks to you. Each request contains the original task \
(the whole problem the team is solving, for context) and your instruction (your part). Do your part as \
instructed.

Your tools:
{tool_lines}
Files are referenced by paths relative to the working directory; task attachments are under attachments/.

Your final message (without a tool call) is your report, and it is all the orchestrator sees. Include the result \
with its evidence or source (URL, file, computation), what you assumed or could not verify, anything that failed \
and why, and the paths of files you created."""


def worker_request(original_task: str, instruction: str) -> str:
    return f"Original task:\n<<<\n{original_task}\n>>>\n\nYour instruction:\n<<<\n{instruction}\n>>>"


TOOL_LIMIT_REACHED = ("You have reached your tool-call limit for this request. Do not call tools any more; write "
                      "your report now with what you have, and say what is unfinished.")
IMAGES_FOLLOW = "Images returned by your tool calls:"


# -- probing (C) and simulated probing (B) ------------------------------------------------------
PROBE_QUESTION_TEXT = {
    "understanding": "Understanding: What do you understand this subtask asks you to do? State its scope, targets "
                     "and direction.",
    "assumptions": "Assumptions: What are you assuming? For each important assumption, what would change if it "
                   "were different?",
    "failure": "Failure: What could fail while you work on it, and how would you respond?",
    "plan": "Plan: In what steps and with what methods would you carry out the whole subtask?",
}


def probe_questions_block(questions: tuple[str, ...]) -> str:
    return "\n".join(f"{i}. {PROBE_QUESTION_TEXT[q]}" for i, q in enumerate(questions, 1))


def probe_instruction(draft: str, questions: tuple[str, ...], tools_allowed: bool, max_tool_calls: int) -> str:
    tools = (f" You may use your tools only for quick checks that help you answer (at most {max_tool_calls} calls)."
             if tools_allowed else " Do not use tools; answer from the instruction and what you know about your tools.")
    return f"""The orchestrator is about to give you the subtask instruction below. Before it is executed, it wants \
to know how you read it. Do NOT carry out the subtask.{tools}

Subtask instruction:
<<<
{draft}
>>>

Answer each question about this subtask:
{probe_questions_block(questions)}
Be concrete and brief."""


def followup_message(question: str) -> str:
    return f"Follow-up question from the orchestrator (still do NOT carry out the subtask):\n{question}"


def simulate_system() -> str:
    return ("You are the orchestrator of a team of workers. Before delegating a subtask, you review your instruction "
            "by predicting, carefully and critically, how the receiving worker would read it.")


def simulate_request(original_task: str, draft: str, worker: dict, questions: tuple[str, ...]) -> str:
    return f"""Worker profile:
- role: {worker['role']} ({worker['description']})
- model: {worker['model']}
- tools: {', '.join(worker['tools'])}
- the worker sees only the original task, the instruction and its own tools

Original task:
<<<
{original_task}
>>>

Subtask instruction you are about to send:
<<<
{draft}
>>>

Write the answers this worker would most plausibly give to the questions below, in the worker's voice. Do not \
idealise the worker: include the misreadings, unstated assumptions, missing conditions and failure modes that are \
plausible for it.
{probe_questions_block(questions)}"""


def analyze_system() -> str:
    return ("You are the orchestrator of a team of workers. You review a subtask instruction before delegating it. "
            "You cannot use tools yourself; facts can only be checked by delegating checks to workers.")


def analyze_request(original_task: str, draft: str, target: dict, responses: list[dict], source: str,
                    max_verifications: int, roles: list[dict], followups_allowed: int) -> str:
    resp = "\n\n".join(f"[{r['id']}] ({r['who']})\n{r['text']}" for r in responses)
    roles_txt = "\n".join(f"- {r['id']}: {r['description']} Tools: {', '.join(r['tools'])}." for r in roles)
    origin = ("given by the worker(s) who would receive it" if source == "probe"
              else "that you predicted for the worker who would receive it")
    follow = (f"\nYou may ask up to {followups_allowed} follow-up questions in total to the workers who answered "
              "(refer to an answer by its id), when an answer is unclear in a way that matters."
              if followups_allowed else "\nDo not ask follow-up questions (leave `followups` empty).")
    return f"""Original task:
<<<
{original_task}
>>>

Subtask instruction to be sent to {target['role']}:
<<<
{draft}
>>>

Answers to review questions about this instruction, {origin}:
{resp}

Find issues in the instruction: places where its scope, targets or direction can be misunderstood; important \
unstated assumptions or wrong premises; likely failures with no stated handling; missing or wrongly ordered steps. \
Differences between answers point to ambiguity, but neither agreement nor disagreement decides what is correct: \
judge against the original task. For each issue choose a decision:
- resolved_from_task: the original task or the instruction itself settles it; give the resolution.
- needs_verification: a fact must be checked first (in the files or on the web).
- not_relevant: it does not affect the result.
For issues that need verification you may request up to {max_verifications} checks, each delegated to one of these \
workers (it receives the original task and your check instruction; keep checks short and specific):
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
            "decision": {"type": "string", "enum": ["resolved_from_task", "needs_verification", "not_relevant"]},
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
                    target: dict) -> str:
    import json

    ver = "\n\n".join(f"[{v['issue_id']}] check by {v['worker_id']}: {v['instruction']}\nResult:\n{v['report']}"
                      for v in verifications) or "(none)"
    return f"""Original task:
<<<
{original_task}
>>>

Current subtask instruction (it will be executed by {target['role']}, whose tools are: \
{', '.join(target['tools'])}):
<<<
{draft}
>>>

Issues found in the review:
{json.dumps(issues, ensure_ascii=False, indent=1)}

Verification results:
{ver}

Write the final version of the subtask instruction, once. Rules:
- Keep the current subtask's goal and scope, but correct the instruction where it conflicts with the original \
task. Turn contradictions found in the review into checks, and into conditions on how to proceed depending on what \
the checks find. Do not turn a subtask that produces the requested result into an assessment of whether the \
problem holds, merely because a contradiction was found.
- Turn resolved issues into explicit criteria, conditions or steps.
- State verified facts explicitly; the worker will not see this review.
- Do not state unverified claims as facts or requirements; instead tell the worker to check them first and how to \
proceed depending on the result.
- Write a self-contained instruction (the worker sees only the original task and this instruction); do not paste \
the review. Where it helps, use the parts "Task:", "Criteria:", "Checks:", "Report:".
- Keep the subtask doable by the executing worker with its tools; do not ask it for work its tools cannot do.
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
