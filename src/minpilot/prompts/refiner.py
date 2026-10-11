"""Orchestrator-side review prompts: prediction, analysis, verification and rewrite."""

from __future__ import annotations
from .worker import worker_request
from .probe import probe_system, probe_instruction
from .schemas import ANALYZE_SCHEMA, REWRITE_SCHEMA, DECISIONS


REVIEW_HEAD = ("[Pre-delegation review. This turn is a review step, not an action: reply as asked below, not with "
               "an action.]")


def simulate_request(original_task: str, draft: str, worker: dict, context: str = "") -> str:
    """Predict answers to the same system prompt and request used by a real tool-free probe."""
    system = probe_system(worker.get("system_prompt") or worker["description"], tuple(worker["tools"]))
    message = worker_request(original_task, probe_instruction(draft, False, 0), context=context, kind="probe")
    return f"""{REVIEW_HEAD}
Before your delegation above is sent, predict how the worker who would receive it would answer the review questions. Use the worker's voice and give its most plausible answers, not an improved instruction. Be concrete and brief.

The worker sees only its system prompt and the message below, not this conversation. Base the prediction on those inputs.

===== worker's system prompt =====
{system}
===== end of system prompt =====

===== message to the worker =====
{message}
===== end of message ====="""


def analyze_request(target: dict, responses: list[dict], source: str, max_verifications: int, roles: list[dict],
                    followups_allowed: int, has_context: bool, observations: bool = False) -> str:
    """Review the pending delegation in the orchestrator's private conversation copy.

    source: real probe or self-review prediction.
    observations: real probes may include sourced tool observations.
    """
    roles_txt = "\n".join(f"- {r['id']}: {r['description']} Tools: {', '.join(r['tools'])}." for r in roles)
    follow = (f"You may ask up to {followups_allowed} follow-up questions in total when an answer is unclear "
              "in a way that affects the review. Refer to the answer by its id."
              if followups_allowed else "Do not ask follow-up questions (leave `followups` empty).")
    receives = ("the original task, the context and your check instruction" if has_context
                else "the original task and your check instruction")
    origin = ("given by the worker(s) who would receive it" if source == "probe"
              else "that you predicted for the worker who would receive it")
    resp = "\n\n".join(f"[{r['id']}] ({r['who']})\n{r['text']}" for r in responses)
    answers = f"## Probe answers\nAnswers about how the instruction would be read and carried out, {origin}:\n{resp}\n\n"
    several = len({r["id"].split(".")[0] for r in responses}) > 1
    compare = " Compare the answer sets as well." if several else ""
    obs = (" For factual claims, cite the reported tool observation and its source; "
           "do not treat the worker's interpretation as something the tool directly observed."
           if observations else "")
    ctx_issue = (" An issue may concern a wrong, unverified or misapplied context claim that the instruction relies on."
                 if has_context else "")
    sees = "the original task, the context and the instruction" if has_context else \
        "the original task and the instruction"
    return f"""{REVIEW_HEAD}
Review the pending instruction for {target['role']}. Identify consequential mismatches between the intended subtask and how the worker would understand or carry it out. Recommend only the changes needed to address them; leaving an adequate instruction unchanged is a valid outcome.

The worker receives only {sees} of that delegation, not this conversation.

{answers}## Review the delegation
Review in this order:
1. The original task: identify its target, requested result and stated conditions.
2. The instruction (with the context): check whether it communicates your intended subtask and the information this conversation established that the subtask needs.

A subtask may cover only part of the original task. Preserve that assigned scope; do not expand it to the whole problem. Distinguish this division of work from changing the original question's target, conditions or what counts as a valid answer. Correct the latter when it occurs. You may request evidence or intermediate results needed for the subtask. Do not require extra proof that would exclude an answer supported by the original task's criteria.

3. The answers: compare the understanding, assumptions, risks and plan with the intended subtask.{compare} A different execution method is not an issue by itself if it can achieve the assigned result.
Answers indicate how the worker reads and intends to execute the instruction; predicted answers indicate how you expect it to do so. Neither a claim nor agreement between answers establishes an external fact.{obs}

## Identify consequential issues
For an issue that requires a change or check, identify:
- the instruction phrase or omission at issue;
- evidence for a concrete path to an incorrect result or incomplete subtask;
- the change or check needed to address it.
Omit generic or speculative concerns and points the instruction already handles. If a specific concern raised in the answers does not affect the assigned result, record it as not_relevant.{ctx_issue}

## Choose how to resolve them
Use the original task, the intended subtask, this conversation and available evidence. For each issue choose a decision:
- clarify: the available information or your intention settles it; state the interpretation or requirement the worker should apply.
- needs_verification: a fact must be checked before execution because its outcome changes the instruction you should write.
- defer_to_execution: the worker can resolve it while doing the assigned work; state the check and how its outcome informs the result. Where needed, explain how to proceed if the check is inconclusive without treating missing evidence as confirmation.
- not_relevant: it does not affect this subtask's result or completion; no change.

Request checks only for needs_verification issues, most important first; checks for other decisions are not run. You may request up to {max_verifications} checks. Each check receives {receives}; specify the fact to check and the evidence to report. Available workers:
{roles_txt}
{follow}

Reply using the required response schema. If there are no issues, leave `issues` empty; leave `verifications` empty when no pre-execution checks are needed."""


def verify_instruction(check: str) -> str:
    return f"""This is a short check requested before the main subtask is delegated. Do only this check and report what you found, with evidence. If you cannot settle it, report what you tried and what remains uncertain.

Check:
{check}"""


def rewrite_request(verifications: list[dict], target: dict, has_context: bool) -> str:
    """Apply accepted resolutions; existing context stays fixed and new observations go in additions."""
    ver = "\n\n".join(f"[{v['issue_id']}] check by {v['worker_id']}: {v['instruction']}\nResult:\n{v['report']}"
                      for v in verifications) or "(none)"
    sees = "the original task, the context and this instruction" if has_context else \
        "the original task and this instruction"
    return f"""{REVIEW_HEAD}
Write the final instruction for your pending delegation, addressing the accepted issues other than not_relevant. It will be executed by {target['role']}, whose tools are: {', '.join(target['tools'])}.

## Check results
{ver}

## Apply the accepted resolutions
Change only what the accepted issues require and keep unaffected parts of the instruction. Use check results as evidence, including failures or inconclusive findings; do not assume a requested check succeeded.

State interpretations that the task, conversation and evidence resolve. When an interpretation remains unresolved, specify a targeted check and how its outcome guides the assigned work rather than forcing an unsupported choice or requesting several alternative final answers.

## Preserve the intended task
Preserve the result requested by the original task and the assigned subtask's scope. Do not expand the delegation to solve the whole problem or introduce conditions that change which answers are acceptable.

Allow a supported inference when the task does not require a source to state the answer explicitly or a separate proof of uniqueness. Do not tell the worker to withhold a supported answer because an extra check you introduced is unavailable. When the evidence does not settle the answer, ask for useful partial findings and what remains unverified.

## Write for the executor
The executor sees only {sees}, not this conversation. These review rules guide your writing; they are not instructions to copy into the delegation.

Put what the worker should do in the instruction, within its tool capabilities. The context is sent as you wrote it. Put needed observations absent from the original task and context in `context_additions`, with their source and verification status. Keep observations separate from interpretations, do not present unverified claims as facts, and do not repeat the original task or context there.

Return the final instruction in the required response schema. If no accepted resolution requires a change to the instruction or additional context, return the current instruction unchanged, leave `context_additions` empty and set `unchanged` to true."""
