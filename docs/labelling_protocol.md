# Trace labelling protocol (min_pilot v1)

For labelling finished runs with `docs/failure_codebook.md`. A labeller (a person or a Claude subagent) gets one
run's transcript and its outcome, and writes one JSON label and a short rationale. Adapted from the old pilot's
protocol: the objectivity rules are kept; the run description, actors and fields are min_pilot's.

## How a min_pilot run works (read first)

- The **orchestrator** (`luna-high`, no tools) sees the task. Each turn it returns a JSON action: `delegate` (a
  role and an instruction) or `finish` (the final answer). It sees each report before its next action.
- A **worker** (`luna`, tools) receives only the original task and the instruction. It runs a tool loop (at most
  20 tool calls, then a forced report turn) and returns a free-text report. Workers keep no memory between
  delegations, so anything a worker needs from earlier reports must be in the instruction.
- Roles (`role_routing` pool): `web_researcher` → `web_luna` (web_search, read_url with an optional Wayback date,
  run_python); `file_analyst` → `file_luna` (read_file, view_image, run_python). The `redundant` and `single`
  pools have one `generalist` role with all tools.
- Delegation indices are 0-based in events, checkpoints and labels (`d0`, `d1`, ...). The orchestrator's own
  prompt numbers reports from 1 ("Report from ... (delegation 1)" is d0).
- In restore runs (conditions B/C), a **refiner** may revise the instruction before execution. The transcript
  then shows the probe answers, the analysis, any verification checks and the rewrite, followed by "FINAL
  instruction sent to the worker".
- The run has no separate answerer: the orchestrator's `finish.answer` is the final answer that is scored.

## Inputs per run

- `transcripts/<run>.md`: the whole run in time order, from `scripts/render_trace.py`. It contains every model
  request's new input messages (system prompts, instructions, tool results), the outputs and tool calls, the
  orchestrator's reasoning summaries when the API returned them, events, a tool-call summary and the refinement
  records. It is long: read all of it, in chunks.
- The raw run directory (path in `transcripts/index.txt`) when something is unclear: `events.jsonl`,
  `llm_calls.jsonl`, `messages.jsonl`, `tool_calls.jsonl`, `work/`.
- The outcome: `correct`, `wrong`, or the run status (`budget_exceeded`, `error`, ...). **You are not given the
  ground-truth answer.**

## Hard rules (objectivity)

1. **Never** read the GAIA dataset files (`~/data2/datasets/GAIA/**`, `metadata*.parquet`), score files beyond
   the outcome you were given, or anything else with ground-truth answers. **Never** search the web for the task
   or its answer. No web access is needed: judge from what the agents saw and did.
2. Support every claim with evidence from the trajectory: quote the exact text (short) and say where it is
   (transcript heading such as "LLM call 31 [stage=execution delegation=0 ...]", plus a few-word anchor).
3. Judge the process, not the outcome. A wrong run does not prove any particular error. Find the step where the
   trajectory first goes wrong in a way you can show: an unsupported claim, a misread tool output, a calculation
   you can re-check, an instruction that drops a constraint of the task, a tool or infrastructure failure. If you
   cannot show it, say so and use confidence `low`.
4. Re-check computations and readings yourself where the data is in the trajectory (recount rows, redo
   arithmetic, compare a report with the tool output it cites). Do not trust an agent's summary of a tool output.
   You may run local Python on files in the run's `work/` directory.
5. Separate the agents' failures from ours: tool and backend failures, sandbox denials, blocklist false
   positives, paging, tool bugs, framework bugs and budget limits are implementation-induced and take precedence
   when they are the first error.
6. Label `correct` runs too: was the success well supported or lucky, and were there process problems?
7. For `would_a_better_instruction_help`, use only what was available at that delegation (the task, the
   attachment, earlier reports). Hindsight from later reports is allowed to *find* the problem, but say whether
   the fix needed information that the orchestrator did not have yet.

## Output

One JSON file per run, `labels/<run>.json`:
```json
{
  "run": "<run name as in transcripts/>",
  "task_id": "...",
  "outcome": "correct | wrong | <status>",
  "category": "<primary codebook category, or 'success'>",
  "secondary": ["..."],
  "implementation_induced": false,
  "location": {"actor": "orchestrator|worker:<id>|refiner", "delegation": 0, "phase": "instruction|execution|report|decision|final_answer|refine"},
  "first_error": "<one sentence: the earliest step that made the run fail, stated as a fact you can show>",
  "first_error_evidence": ["<quote + location>", "..."],
  "error_chain": "<2-4 sentences>",
  "delegation_related": "yes | no | unclear",
  "delegation_note": "<which d<k>, and how its instruction caused or did not cause the first error>",
  "first_meaningful_delegation": {"index": 0, "is_d0": true, "instruction": "<text>", "flawed": "yes|no|unclear", "why": "<...>"},
  "would_a_better_instruction_help": "yes | no | unclear",
  "better_instruction_note": "<what was missing or wrong, and whether it was available at that point>",
  "framework_events": {"invalid_actions": 0, "tool_limit_reports": 0, "empty_reports": 0, "forced_finish": false, "n_delegations": 0},
  "tool_issues": ["<with evidence>"],
  "process_notes": "<anything else; for correct runs: well supported or lucky, and why>",
  "confidence": "high | medium | low"
}
```
Also write `labels/<run>.md`: a short readable rationale (at most 40 lines) with the step-by-step account, ending
with the label.
