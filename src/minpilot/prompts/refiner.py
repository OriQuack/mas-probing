"""Refiner prompts: complete message bodies live beside their input preparation."""

from __future__ import annotations
from .worker import worker_system, worker_request
from .schemas import ANALYZE_SCHEMA, REWRITE_SCHEMA, DECISIONS


PROBE_LABELS = ("understanding", "choices", "risks", "plan")


REVIEW_HEAD = ("[Pre-delegation review. This turn is a review step, not an action: reply as asked below, not with "
               "an action.]")


def probe_tool_policy(tools_allowed: bool, max_tool_calls: int) -> str:
    if not tools_allowed:
        return "Do not use tools or execute the subtask."
    return f"""You may use your tools for limited checks needed to explain your choices and risks, up to {max_tool_calls} tool calls.
Keep tool use focused on those checks rather than completing the full subtask.
When reporting an observation, include what you found and its source."""


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
Interpretations or assumptions you would use where the task, context, or instruction leaves room for judgment. State the choice you would make. Do not merely repeat given conditions.

risks:
Task-specific risks that could produce an incorrect result or prevent completion. Avoid generic possibilities without a concrete reason to expect them here.

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


def simulate_request(original_task: str, draft: str, worker: dict, context: str = "") -> str:
    """Predict the worker's probe answers. The worker's system prompt and the probe message are built by the
    same functions as the real probe (no tools while answering). `worker["system_prompt"]` is the worker's registered
    prompt; without it the role description stands in."""
    system = worker_system(worker.get("system_prompt") or worker["description"], tuple(worker["tools"]))
    message = worker_request(original_task, probe_instruction(draft, False, 0), context=context, kind="probe")
    return f"""{REVIEW_HEAD}
Before your delegation above is sent, predict how the worker who would receive it would answer the message below. The worker sees only the message below, not this conversation; predict its answers from what the message gives it.

===== worker's system prompt =====
{system}
===== end of system prompt =====

===== message to the worker =====
{message}
===== end of message =====

Predict the answers this worker would most plausibly give to the message above, in the worker's voice. Be concrete and brief."""


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
        answers = ""
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
    ctx_issue = (" An issue can also lie in a context claim the instruction relies on (wrong, unverified or applied "
                 "wrongly)." if has_context else "")
    sees = "the original task, the context and the instruction" if has_context else \
        "the original task and the instruction"
    text = f"""{REVIEW_HEAD}
Before your delegation above is sent to {target['role']}, review its instruction. The worker will receive only {sees} of that delegation; it does not see this conversation.

{answers}Review in this order:
1. The original task: its target, the requested result and the conditions it states.
2. The instruction (with the context): whether it adds, removes or changes any of these, and whether it states what you intend for this subtask and what this conversation established that the subtask needs. Requiring evidence or intermediate results is not a conflict by itself; review it when it changes what counts as an acceptable result."""
    if source != "direct":
        text += f"""
3. The answers: compare the reading, choices and plan they report with what you intend. A difference is an issue when it could change the result.{compare} An answer reports how a worker would read and do the subtask: neither an answer nor agreement between answers is evidence of a fact.{obs} Keep what an answer observed (what a file or source says) apart from what it concludes from that, such as that the task is ambiguous or that several results must be given: the conclusion is the worker's interpretation, which you judge yourself."""
    return text + f"""

Accept an issue only when you can state:
- the phrase of the instruction at issue, or what it omits;
- why it can lead to an incorrect result or an incomplete subtask;
- the change or check it needs.
Do not accept generic risks, points the task or the instruction already handles adequately, or other possible interpretations that do not affect the requested result.{ctx_issue}

Resolve an accepted issue toward the reading that the original task's wording and purpose support, as a careful reader would take it. A resolution must not narrow the task's target, scope or conditions beyond what the original task states; where the instruction narrows them, the resolution restores the task's wording.

For each issue choose a decision:
- clarify: you settle it from the original task, this conversation or your intention for this subtask; give the resolution, to be stated in the instruction.
- needs_verification: a fact must be checked before execution, because the correct instruction depends on the result.
- defer_to_execution: the executing worker can check it during execution; give, as the resolution, the check and how its outcome is used to produce the requested result, including when the check cannot be completed (the worker then proceeds with the best available evidence). Request no check for it.
- not_relevant: it does not affect this subtask's result or completion; no change.
Request checks only for needs_verification issues, most important first; checks for other issues are not run. You may request up to {max_verifications} checks, each delegated to one of these workers (it receives {receives}; keep checks short and specific):
{roles_txt}{follow}
If there are no issues, return an empty list."""


def verify_instruction(check: str) -> str:
    return f"""This is a short check requested before the main subtask is delegated. Do only this check and report what you found, with evidence.

Check:
{check}"""


def rewrite_request(verifications: list[dict], target: dict, has_context: bool) -> str:
    """The rewrite turn, after the analysis turn of the same conversation. The context is sent as written; facts the
    executor needs go to `context_additions`, appended after it."""
    ver = "\n\n".join(f"[{v['issue_id']}] check by {v['worker_id']}: {v['instruction']}\nResult:\n{v['report']}"
                      for v in verifications) or "(none)"
    sees = "the original task, the context and this instruction" if has_context else \
        "the original task and this instruction"
    return f"""{REVIEW_HEAD}
Results of checks run before this delegation:
{ver}

Write the final version of the instruction of your delegation above, once, addressing the issues you accepted (those not marked not_relevant). It will be executed by {target['role']}, whose tools are: {', '.join(target['tools'])}. Rules:
- Preserve the result requested by the original task. Change only the work, interpretations or checks that the accepted issues require; keep the rest of the instruction.
- Resolve interpretations using the task, context, this conversation and the evidence, or specify the targeted check needed to resolve them. State the one reading the worker should apply; do not ask for results under several readings.
- Keep evidence requirements appropriate to the task. Do not demand explicit statements or a separate proof of uniqueness when a supported inference is sufficient.
- These rules are for writing the instruction and are not part of it. Do not add conditions under which the worker should withhold the result or report that it cannot be determined; where a check may fail, the worker gives the result best supported by the available evidence and states what it could not check.
- The executor sees only {sees}, not this conversation; the context is sent as you wrote it. Put what it should do in the instruction. Put facts it needs that the task and context do not already contain (from the checks, probe observations or reports in this conversation) in `context_additions`, with their source and whether they were verified: what was observed, not conclusions drawn from it (such as that the task is ambiguous). Do not restate the task or the context there, and do not present unverified claims as facts.
- Write the instruction for use with the original task and context, within the executor's tool capabilities.
If no accepted issue requires a change, return the current instruction unchanged, leave `context_additions` empty and set `unchanged` to true."""
