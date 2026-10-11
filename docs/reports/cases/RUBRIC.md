# Deep trace analysis rubric (min_pilot, GAIA validation, 2026-10-10)

You analyse saved runs of a multi-agent system on GAIA tasks. Read this whole file first. Work read-only: do not
run experiments, do not search the web, do not edit anything except your own output files in
`/tmp/claude-1014/-home-dohyun-mas-uncertainty/f2a1cd4a-4e4a-431c-8ced-9c0f6b672004/scratchpad/deep/analysis/`.
The repository is `/home/dohyun/mas-uncertainty/min_pilot` (run dirs in the cards are relative to it). Never print
or copy API keys or `.env` contents.

## 1. The system
- An **orchestrator** (model luna-high) receives the GAIA task, writes an **instruction** for a worker and delegates
  (delegation 0 = d0, then d1, d2, ...). The worker (gen_luna, with tools: web_search, read_url, read_url_text,
  find_in_url, read_file, view_image, run_python) executes and returns a **report**. The orchestrator then delegates
  again or **finishes** with a final answer. Most tasks need 1-3 delegations.
- The worker sees the original task text + the instruction (+ optional context), not the orchestrator's conversation.
- A **refiner** may sit between the orchestrator and the worker, only at d0. It reviews the orchestrator's draft
  instruction before execution:
  1. **probe**: the would-be worker(s) are asked how they would approach the subtask, with four labelled items
     (exact wording of the probe):
     - `understanding`: "One sentence stating the result you would produce and its scope."
     - `choices`: "Interpretations or assumptions you would use where the task, context, or instruction leaves room
       for judgment. State the choice you would make. Do not merely repeat given conditions."
     - `risks`: "Task-specific risks that could produce an incorrect result or prevent completion. Avoid generic
       possibilities without a concrete reason to expect them here."
     - `plan`: "The steps you would take for the whole subtask, including how you would handle relevant risks."
     In c2/c3 the probe may use up to 3 tool calls for limited checks (these are the **tool observations**).
  2. **analysis**: the orchestrator model, continuing its own conversation, compares the task, the draft and the
     probe answers and lists **issues**, each with a decision: clarify / needs_verification (a check run before
     execution) / defer_to_execution / not_relevant.
  3. **rewrite**: if there are accepted issues, the instruction is rewritten (field `final`), optionally with
     `context_additions` (facts appended to the context). If no issues: status `no_issues`, the draft is sent
     unchanged (that run is then processed like A).
- **Arms**: `A_none` (no refiner), `c2_probe_tools` (one probe: luna), `c3_probe_multi` (two probes: luna + haiku,
  shown anonymously as "respondent 1/2" in random order).

## 2. The run phases in the cards
| phase | what | instruction at d0 |
|---|---|---|
| `v5__fresh` | prompts v5, fresh run, no refiner, search degraded to DuckDuckGo (~46% of web_search calls failed) | its own draft |
| `v6__fresh` | prompts v6, fresh run, no refiner, same degraded search; it saved the d0 checkpoint used by s4 and rA | its own draft |
| `s4__*` | restore of the v6 d0 checkpoint (same draft as v6 fresh), Serper search, refiner prompts r8, 1 rep | v6 draft (A) / r8 rewrite |
| `rA__*` | restore of the same v6 d0 checkpoint, refiner prompts r9, 2 reps (r0, r1) | v6 draft (A) / r9 rewrite |
| `rBfresh__base_r0` | prompts v7 (date line fixed), fresh run, no refiner | its own v7 draft |
| `rB__*`, `rBredo__*` | restore of the v7 d0 checkpoint, refiner r9 | v7 draft / r9 rewrite |

- Restores start from the same orchestrator state, so arms on the same checkpoint share the identical d0 draft. Runs
  are not deterministic: even with the identical draft and no refiner change, ~17% of task outcomes differed.
- Prompts v5/v6 ended the task text with "Run reference date: 2026-10-09 (today's date for this run; a date or time
  stated in the task takes precedence)." This sometimes made models treat the run date as the task's time reference.
  v7 changed it to say the run date is not the task's time reference.
- r8 (s4) rewrite rules contained "Report that the result cannot be derived only when a specific missing or
  conflicting piece of evidence prevents ..."; r9 removed it and forbids withholding conditions and multi-reading
  answers. Treat these as context, not as conclusions to confirm.
- Scoring is GAIA's official normalised string/number match. Known scorer-side issues: curly apostrophe (366e2f2b),
  "Citations" vs "Citation count" (708b99c5), gold typo "Ploybius" (ded28325).

## 3. Files
- Task card: `deep/cards/<task8>.md` — question, gold, attachment name, GAIA annotator steps (the human solution
  path), and the run table with run dirs and rendered transcripts.
- Rendered transcript `deep/tr/<task8>/<run>.md` (large; tool results truncated at 6000 chars). Navigate with grep:
  - `grep -n '^## \[event\]' FILE` lists orchestrator actions, delegations, reports, refiner status, run_end.
  - `grep -n 'stage=refine' FILE` lists probe / analysis / rewrite calls.
  - Orchestrator rationale appears in the LLM call just before each `orchestrator action`.
  - Read every worker report and every orchestrator action in full; read tool results selectively.
- Raw run dir (`<run dir>/`): `run.json` (final answer, delegations with draft/final instruction), `events.jsonl`,
  `tool_calls.jsonl`, `messages.jsonl` (full texts), `refine/d0.json` (refiner record: `draft`, `responses[]`
  with `text` and `parsed` {understanding, choices, risks, plan}, `probe_observations`, `analysis[].issues[]`
  {id, target, impact, evidence, decision, resolution}, `verifications`, `rewrite`, `final`, `context_additions`,
  `status`). `refine/d0.json` is the easiest source for the refiner part.
- Attachments, if needed: `/home/dohyun/data2/datasets/GAIA/2023/validation/<file_name>`; the card gives the file name. Prefer what the runs
  read.

## 4. What to produce for each task
Write `deep/analysis/<task8>.md` in Korean prose (keep quotes from traces verbatim in English), with:

### 4.1 Task and intended solution
What the task asks, what the gold requires (from the annotator steps), and the key points where a solver can go wrong.

### 4.2 Run-by-run path
For every run in the card (group identical paths briefly): d0 instruction (what it said that matters), what the
worker did and reported, later delegations, the finish and its rationale. For failed runs, identify the **decisive
failure point**: the first point after which the correct answer was no longer reached or was dropped. Quote the
evidence and give the transcript line number(s). For correct runs, say what made them succeed, especially when
other runs on the same instruction failed.

### 4.3 Cause codes (failed runs)
Use one primary code and optional secondary codes:
- `I-DRAFT`: the orchestrator's d0 instruction deviated from the task (narrowed or changed target, scope, time
  frame, conditions or format, added a filter) and that caused the failure.
- `I-REWRITE`: the refiner's rewrite introduced the deviation or condition that caused the failure.
- `I-OMIT`: the instruction was faithful but left unstated a reading or requirement that the task text itself
  determines, and the worker took a wrong reading.
- `X-RETRIEVE`: the needed source was not found or not accessible (search failure, unreadable page, missing archive).
- `X-READ`: a source or file was found but misread (wrong row, OCR, table parsing, wrong version of a page).
- `X-REASON`: reasoning, counting, matching or arithmetic error with the needed information at hand.
- `X-BUDGET`: tool limit, runaway reading, or the run gave up for budget.
- `O-RECHECK`: the orchestrator's later delegations led away from a correct or near-correct intermediate result.
- `O-FINISH`: the orchestrator's final choice, hedge or non-answer, with the needed information available.
- `O-FORMAT`: substance right but formatting, rounding or units the task did not ask for.
- `S-SCORER`: equivalent answer rejected by the scorer, or gold error.

### 4.4 Pre-execution preventability (the key question)
For each failed run, judge whether **fixing the d0 instruction before execution** would likely have prevented the
failure:
- `YES-FAITHFUL`: the instruction contained a deviation from the task; an instruction faithful to the task text
  would likely have prevented it.
- `YES-TASKTEXT`: the instruction was faithful, but adding a statement derivable from the task text alone (a
  reading, a definition, an exact-value or format requirement) would likely have prevented it.
- `MAYBE-KNOWHOW`: a pre-execution hint about method or source might have helped, but it needs domain or
  source knowledge. Say whether a careful reviewer could plausibly know it **before** execution, without hindsight.
- `NO`: not addressable by the d0 instruction (execution, later orchestrator decisions, scorer).

Be strict about hindsight. A fix must not contain facts that were discovered only during execution or that
encode the answer (names, values, which page has it), unless the task text states them. Write the minimal fix as
instruction sentence(s), with confidence (high / med / low) and why. Note the base rate: if A-equivalent runs on
the same instruction sometimes succeed, the failure may be noise rather than instruction-caused; say so.

### 4.5 Refiner records (c2 / c3 runs, every phase)
For each refiner record:
- For each probe item (understanding, choices, risks, plan) and the tool observations: what each respondent said
  that matters (brief). Flag items that (a) correctly identified a real deviation of the draft from the task,
  (b) raised a spurious or harmful ambiguity, (c) foresaw the cause of a failure that actually occurred in some run
  of this task.
- For each accepted issue: its source (`r1.choices`, `r2.risks`, `r1.observation`, `draft-vs-task` when no probe
  answer is its basis, etc.; check the issue's `evidence` and compare with the answers), the decision, and a
  quality label:
  - `CORRECT-CATCH`: fixes a real deviation, or adds a clarification that matches the task's intended reading and
    could matter.
  - `REDUNDANT`: correct but changes nothing the worker would not have done anyway.
  - `HARMFUL-STRICT`: makes the evidence standard stricter than the task needs.
  - `HARMFUL-NARROW`: narrows the target, scope or candidate set.
  - `HARMFUL-AMBIG`: introduces ambiguity, multiple answers, or a withholding / cannot-determine condition.
  - `WRONG-READING`: resolves toward an interpretation the task does not intend.
  - `OTHER` (explain).
- The effect on the outcome compared with the A-equivalent runs on the same checkpoint (`helped` / `hurt` /
  `none` / `unclear`) and why. Be careful with noise.
- Whether the probe answers contained a signal of the failure cause that actually occurred in any run of this task,
  and whether the analysis used it.

### 4.6 Summary block
End the file with a fenced ```json block:
```
{
 "task": "<task8>", "gold": "...", "summary": "<2-3 sentences>",
 "runs": [{"run": "<name>", "ok": true/false, "answer": "...", "primary_cause": "<code or null>",
           "causes": ["..."], "failure_point": "<short>", "preventable": "<YES-FAITHFUL|YES-TASKTEXT|MAYBE-KNOWHOW|NO|null>",
           "fix": "<instruction sentence(s) or null>", "confidence": "<high|med|low|null>", "notes": "..."}],
 "refine": [{"run": "<name>", "status": "<rewritten|no_issues|...>",
             "probe_items": {"understanding": "...", "choices": "...", "risks": "...", "plan": "...", "observations": "..."},
             "issues": [{"id": "...", "source": "...", "decision": "...", "quality": "...", "note": "..."}],
             "foresaw_failure": true/false/null, "effect_vs_A": "<helped|hurt|none|unclear>", "note": "..."}],
 "task_level": {"preventable": "<YES-FAITHFUL|YES-TASKTEXT|MAYBE-KNOWHOW|NO|NA>",
                "explanation": "...",
                "test_with_counterfactual": true/false,
                "counterfactual_instruction": "<a complete d0 instruction to test, faithful to the task, with the fix, no answer leakage; or null>"}
}
```
`task_level.preventable` is about the A-equivalent failures on the shared drafts (v6 draft for s4/rA, v7 draft for
rB): could a d0 instruction fix have turned those failures into successes? Use `NA` if A-equivalent runs did not
fail. Propose a counterfactual instruction only when you judge the failure plausibly preventable (YES-* or a
MAYBE-KNOWHOW that a reviewer could know before execution); it will be tested by restoring the checkpoint and
sending this instruction instead of the draft, so write it as a full instruction for the worker.

## 5. Final reply
Reply with a short summary (at most 15 lines per task): the per-task conclusion, the preventability judgment, and
anything surprising. The analysis file is the main output.
