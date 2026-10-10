"""All prompts of min_pilot, in one place, with two versions recorded per run:
- PROMPTS_VERSION: the orchestrator and worker prompts (what a run and its checkpoints are made of; a restore
  refuses a different version).
- REFINER_PROMPTS_VERSION: the probe, review, analysis, verification and rewrite prompts. They act only after a
  checkpoint, so a restore may use a newer version than the run that recorded the checkpoint. The previous set (r5) is
  kept frozen in prompts_r5.py for the earlier-refiner arm (decision R21). From r7 the review runs inside a
  copy of the orchestrator's conversation (R22); from r8 probe answers are anonymous (R23).

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
# v6 (2026-10-09; stage 3 of E8, user's plan): worker report Result / Evidence / Interpretation / Unfinished (the
#     interpretations and assumptions applied; claims not verified go under Unfinished); the orchestrator delegates a
#     check only for a specific unresolved issue that could change the answer, and the check reports which
#     observations support or change the current result (decision F22)
# v7 (2026-10-10; after stage 4): the date line of the task text names the run date and says it is not the task's
#     time reference (the task may have been written earlier; no filtering or source choice by it); v5-v6 called it
#     "today's date for this run", and drafts and rewrites applied it to "recent" or "just released" (decision F23)
PROMPTS_VERSION = "v7"
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
# r6 (2026-10-09): probe: four labelled items (understanding; choices, risks, plan as lists), tool policy as a
#     condition; analysis in the order original task -> instruction -> answers, an issue is accepted only with the
#     phrase or omission, why it can make the result wrong or incomplete, and the change or check; no generic risks;
#     answers and agreement are not evidence; rewrite keeps the requested result and an appropriate evidence level,
#     "cannot be derived" only for specific missing or conflicting evidence; facts from checks go to
#     `context_additions` (appended after the unchanged context), actions to the instruction; `direct` analysis
#     (no answers) for the direct-check condition (decision R21). r5 is frozen in prompts_r5.py.
# r7 (2026-10-09; user's decisions): the review (c1's prediction, analysis, rewrite) runs as turns of a copy of the
#     orchestrator's own conversation (system prompt, task, earlier actions and reports, the pending delegation),
#     discarded afterwards; `resolved_from_task` -> `clarify` (settled from the task, the conversation or the
#     orchestrator's intention, and stated in the instruction); the analysis compares the answers with the
#     intention; `context_additions` only for facts the task and context do not contain (decision R22). r6 (the
#     separate-conversation version of the same prompts) was run once in stage 1 and is not kept.
# r8 (2026-10-09; user's decision): probe answers are shown without worker ids or model names ("respondent k"),
#     the probe workers answer in an order shuffled per delegation (logged), against the orchestrator model's
#     self-preference; otherwise r7 (decision R23). r7 ran in stages 1-2 and is not kept.
# r9 (2026-10-10; after the stage-4 traces and the user's review): the analysis keeps what an answer observed apart
#     from what it concludes, resolves issues toward the reading the task's wording and purpose support, never
#     narrows the task's target, scope or conditions (and restores them where the instruction narrowed them), and a
#     deferred check says how its outcome, or its failure, leads to the requested result. The rewrite changes only the
#     work, interpretations or checks the issues need, gives one reading, keeps its own rules out of the instruction,
#     adds no conditions for withholding the result, and `context_additions` carries observations, not conclusions
#     (decision R24). r8 ran in stage 4 and is not kept.
REFINER_PROMPTS_VERSION = "r9"

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
        text += (f"\n\nRun date: {reference_date} (the day this run takes place). The task may have been written "
                 "earlier: do not take the run date as the task's time reference, and do not filter data or choose "
                 "sources by it; take the time frame from the task itself.")
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
incomplete. Delegate a check only for a specific unresolved issue that could change the answer, and have the check \
report which observations support or change the current result. Otherwise, build on previous results rather than \
repeating completed work. You can delegate at most {max_delegations} times.

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


def report_message(role_id: str, index: int, report: str, sent_instruction: str | None,
                   added_context: str | None = None) -> str:
    """`role_id`: the name shown for the worker (the harness passes "the worker" when there is one role).
    `added_context`: facts the pre-delegation review appended to your context (refiner r6; F21). Without it the
    message is the v5 one."""
    head = f"Report from {role_id} (delegation {index + 1}):"
    if added_context:
        head = (f"The pre-delegation review appended to your context:\n<<<\n{added_context}\n>>>\n\n" + head)
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
Result: the result, or useful partial findings.
Evidence: what supports it (URLs, files, computations, created file paths).
Interpretation: the interpretations and assumptions you applied where the task or instruction left room for \
judgment.
Unfinished: claims not verified, remaining work, failures and blockers."""


def context_block(context: str) -> str:
    """The context section of a request (empty when there is no context, so such requests read as before)."""
    if not (context or "").strip():
        return ""
    return (f"Context (reported by earlier work; may contain errors or unverified claims):\n<<<\n{context.strip()}"
            "\n>>>\n\n")


CONTEXT_ADDITIONS_HEAD = "Results of checks run before this delegation:"


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


# -- probing (r6/r7, decisions R21, R22) -------------------------------------------------------------
# The probe asks for four labelled items; the worker reports its reading and expected actions, and the orchestrator
# side judges them. understanding is one sentence; choices, risks and plan are lists (parse_probe).
PROBE_LABELS = ("understanding", "choices", "risks", "plan")


def probe_tool_policy(tools_allowed: bool, max_tool_calls: int) -> str:
    if not tools_allowed:
        return "Do not use tools or execute the subtask."
    return (f"You may use your tools for limited checks needed to explain your choices and risks, up to "
            f"{max_tool_calls} tool calls.\nKeep tool use focused on those checks rather than completing the full "
            "subtask.\nWhen reporting an observation, include what you found and its source.")


def probe_instruction(draft: str, tools_allowed: bool, max_tool_calls: int) -> str:
    """The probe (sent with the original task and the context, as every request). Tools: a condition (R21)."""
    return f"""Before executing the subtask, explain how you would approach it.
{probe_tool_policy(tools_allowed, max_tool_calls)}

Subtask instruction:
<<<
{draft}
>>>

Use the four labels below. Keep each item short.
Empty choices and risks lists are valid. Do not invent items to fill the form.

understanding:
One sentence stating the result you would produce and its scope.

choices:
Interpretations or assumptions you would use where the task, context, or instruction leaves room for judgment. \
State the choice you would make. Do not merely repeat given conditions.

risks:
Task-specific risks that could produce an incorrect result or prevent completion. Avoid generic possibilities \
without a concrete reason to expect them here.

plan:
The steps you would take for the whole subtask, including how you would handle relevant risks. One line per step."""


def parse_probe(text: str) -> dict | None:
    """The four labelled items of a probe answer, for the log (the analysis reads the answer text). None when no
    label is found. understanding: a string; choices, risks, plan: lists of strings (bullets stripped)."""
    import re

    out: dict = {}
    cur = None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*[#*_\s]*(understanding|choices|risks|plan)[*_\s]*:[*_\s]*(.*)$", line, re.I)
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
            **{k: items(out.get(k, [])) for k in ("choices", "risks", "plan")}}


def followup_message(question: str) -> str:
    return f"Follow-up question from the orchestrator (still do not execute the subtask):\n{question}"


# -- the review as turns of the orchestrator's own conversation (r7, decision R22) ---------------------
# The review continues a copy of the orchestrator's conversation (its system prompt, the task, earlier actions and
# reports, and the pending delegate action); the copy is discarded afterwards. Each turn below is a user message in
# that copy. The worker never sees the conversation.
REVIEW_HEAD = ("[Pre-delegation review. This turn is a review step, not an action: reply as asked below, not with "
               "an action.]")
DECISIONS = ("clarify", "needs_verification", "defer_to_execution", "not_relevant")


def simulate_request(original_task: str, draft: str, worker: dict, context: str = "") -> str:
    """c1: predict the worker's probe answers. The worker's system prompt and the probe message are built by the
    same functions as the real probe (no tools while answering). `worker["system_prompt"]` is the worker's registered
    prompt; without it the role description stands in."""
    system = worker_system(worker.get("system_prompt") or worker["description"], tuple(worker["tools"]))
    message = worker_request(original_task, probe_instruction(draft, False, 0), context=context, kind="probe")
    return f"""{REVIEW_HEAD}
Before your delegation above is sent, predict how the worker who would receive it would answer the message below. \
The worker sees only the message below, not this conversation; predict its answers from what the message gives it.

===== worker's system prompt =====
{system}
===== end of system prompt =====

===== message to the worker =====
{message}
===== end of message =====

Predict the answers this worker would most plausibly give to the message above, in the worker's voice. Be concrete \
and brief."""


# adapters: uniform calls from refine/review.py for r5 (prompts_r5) and r7
def probe_for(draft: str, cfg, with_context: bool) -> str:
    return probe_instruction(draft, cfg.probe_tools, cfg.probe_max_tool_calls)


def simulate_for(original_task: str, draft: str, worker: dict, cfg, context: str = "") -> str:
    return simulate_request(original_task, draft, worker, context)


def analyze_request(target: dict, responses: list[dict], source: str, max_verifications: int, roles: list[dict],
                    followups_allowed: int, has_context: bool, observations: bool = False) -> str:
    """source: "probe" (real answers), "self_review" (predicted answers) or "direct" (no answers: issues and checks
    are chosen from the inputs alone). `observations`: the probe allowed tools, so answers may report tool
    observations with their source. The task, the context and the draft are in the conversation above."""
    roles_txt = "\n".join(f"- {r['id']}: {r['description']} Tools: {', '.join(r['tools'])}." for r in roles)
    follow = (f"\nYou may ask up to {followups_allowed} follow-up questions in total to the workers who answered "
              "(refer to an answer by its id), when an answer is unclear in a way that matters."
              if followups_allowed else "\nDo not ask follow-up questions (leave `followups` empty).")
    receives = ("the original task, the context and your check instruction" if has_context
                else "the original task and your check instruction")
    if source == "direct":
        answers, step3 = "", ""
    else:
        origin = ("given by the worker(s) who would receive it" if source == "probe"
                  else "that you predicted for the worker who would receive it")
        resp = "\n\n".join(f"[{r['id']}] ({r['who']})\n{r['text']}" for r in responses)
        answers = f"Answers about how the instruction would be read and carried out, {origin}:\n{resp}\n\n"
        # independent answer sets (follow-up answers, ids "r1.f1", belong to their set)
        several = len({r["id"].split(".")[0] for r in responses}) > 1
        compare = " Compare the answer sets as well." if several else ""
        obs = (" Tool observations that answers report, with their source, can serve as evidence; cite the ones you "
               "rely on in the issue's evidence." if observations else "")
        step3 = (f"\n3. The answers: compare the reading, choices and plan they report with what you intend. A "
                 f"difference is an issue when it could change the result.{compare} An answer reports how a worker "
                 "would read and do the subtask: neither an answer nor agreement between answers is evidence of a "
                 f"fact.{obs} Keep what an answer observed (what a file or source says) apart from what it concludes "
                 "from that, such as that the task is ambiguous or that several results must be given: the "
                 "conclusion is the worker's interpretation, which you judge yourself.")
    ctx_issue = (" An issue can also lie in a context claim the instruction relies on (wrong, unverified or applied "
                 "wrongly)." if has_context else "")
    sees = "the original task, the context and the instruction" if has_context else \
        "the original task and the instruction"
    return f"""{REVIEW_HEAD}
Before your delegation above is sent to {target['role']}, review its instruction. The worker will receive only \
{sees} of that delegation; it does not see this conversation.

{answers}Review in this order:
1. The original task: its target, the requested result and the conditions it states.
2. The instruction (with the context): whether it adds, removes or changes any of these, and whether it states \
what you intend for this subtask and what this conversation established that the subtask needs. Requiring evidence \
or intermediate results is not a conflict by itself; review it when it changes what counts as an acceptable \
result.{step3}

Accept an issue only when you can state:
- the phrase of the instruction at issue, or what it omits;
- why it can lead to an incorrect result or an incomplete subtask;
- the change or check it needs.
Do not accept generic risks, points the task or the instruction already handles adequately, or other possible \
interpretations that do not affect the requested result.{ctx_issue}

Resolve an accepted issue toward the reading that the original task's wording and purpose support, as a careful \
reader would take it. A resolution must not narrow the task's target, scope or conditions beyond what the original \
task states; where the instruction narrows them, the resolution restores the task's wording.

For each issue choose a decision:
- clarify: you settle it from the original task, this conversation or your intention for this subtask; give the \
resolution, to be stated in the instruction.
- needs_verification: a fact must be checked before execution, because the correct instruction depends on the \
result.
- defer_to_execution: the executing worker can check it during execution; give, as the resolution, the check and \
how its outcome is used to produce the requested result, including when the check cannot be completed (the worker \
then proceeds with the best available evidence). Request no check for it.
- not_relevant: it does not affect this subtask's result or completion; no change.
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
            "target": {"type": "string", "description": "The phrase of the instruction at issue, or what it omits."},
            "impact": {"type": "string", "description": "Why it can lead to an incorrect result or an incomplete "
                                                        "subtask."},
            "evidence": {"type": "string", "description": "What shows it: the original task's text, answer ids, "
                                                          "reported observations with their source."},
            "decision": {"type": "string", "enum": list(DECISIONS)},
            "resolution": {"type": "string", "description": "The change or check it needs."},
        }, "required": ["id", "target", "impact", "evidence", "decision", "resolution"]}},
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


def rewrite_request(verifications: list[dict], target: dict, has_context: bool) -> str:
    """The rewrite turn, after the analysis turn of the same conversation. The context is sent as written; facts the
    executor needs go to `context_additions`, appended after it (decision F21)."""
    ver = "\n\n".join(f"[{v['issue_id']}] check by {v['worker_id']}: {v['instruction']}\nResult:\n{v['report']}"
                      for v in verifications) or "(none)"
    sees = "the original task, the context and this instruction" if has_context else \
        "the original task and this instruction"
    return f"""{REVIEW_HEAD}
Results of checks run before this delegation:
{ver}

Write the final version of the instruction of your delegation above, once, addressing the issues you accepted \
(those not marked not_relevant). It will be executed by {target['role']}, whose tools are: \
{', '.join(target['tools'])}. Rules:
- Preserve the result requested by the original task. Change only the work, interpretations or checks that the \
accepted issues require; keep the rest of the instruction.
- Resolve interpretations using the task, context, this conversation and the evidence, or specify the targeted \
check needed to resolve them. State the one reading the worker should apply; do not ask for results under several \
readings.
- Keep evidence requirements appropriate to the task. Do not demand explicit statements or a separate proof of \
uniqueness when a supported inference is sufficient.
- These rules are for writing the instruction and are not part of it. Do not add conditions under which the worker \
should withhold the result or report that it cannot be determined; where a check may fail, the worker gives the \
result best supported by the available evidence and states what it could not check.
- The executor sees only {sees}, not this conversation; the context is sent as you wrote it. Put what it should do \
in the instruction. Put facts it needs that the task and context do not already contain (from the checks, probe \
observations or reports in this conversation) in `context_additions`, with their source and whether they were \
verified: what was observed, not conclusions drawn from it (such as that the task is ambiguous). Do not restate the \
task or the context there, and do not present unverified claims as facts.
- Write the instruction for use with the original task and context, within the executor's tool capabilities.
If no accepted issue requires a change, return the current instruction unchanged, leave `context_additions` empty \
and set `unchanged` to true."""


REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "instruction": {"type": "string"},
        "context_additions": {"type": "string", "description": "Facts the executor needs that the task and context "
                                                              "do not contain, with source and verification status; "
                                                              "empty if none."},
        "changes": {"type": "array", "items": {"type": "string"}},
        "unchanged": {"type": "boolean"},
    },
    "required": ["instruction", "context_additions", "changes", "unchanged"],
}
