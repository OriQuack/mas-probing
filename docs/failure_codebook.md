# Failure codebook (min_pilot v1, for trace labelling)

The old pilot's codebook (`../pilot/docs/failure_codebook.md`) used OWL's actors (Planner, Coordinator, answerer,
browser sub-agent) and OWL framework events (unparseable worker output, invalid assignee, replans). min_pilot has
none of those. This version keeps what is framework-independent and re-defines the rest for min_pilot's actors:
- **Kept:** the OWL paper's GAIA taxonomy as the base; one primary category per run; implementation-induced
  categories kept separate and taking precedence; the contamination classes; label from the trace only.
- **Re-defined:** the actors are `orchestrator` (writes instructions, reads reports, decides, gives the final
  answer), `worker:<id>` (executes one instruction with tools, writes a free-text report) and, in B/C restores,
  `refiner` (probe, analysis, verification, rewrite). The location is a **delegation index** `d<k>`, not
  attempt/subtask. "Planner error" is split into an instruction error (one delegation) and an orchestration error
  (decisions across delegations). "Responding error" becomes the orchestrator's final-answer error, since there is
  no answerer.

**Label from the trace only, never from the ground truth's content.** The outcome (correct/wrong) says *that* a
run failed, not *why*.

## Primary categories

One primary `category` per failed run: the earliest error that made the run fail. Secondary categories are
allowed.

**Agent errors**

| Category | Definition (min_pilot) | Typical evidence |
|---|---|---|
| `instruction_error` | A delegation instruction drops, inverts or adds a constraint, scope, target or approach relative to the original task, or leaves out information from earlier reports that the worker needs (workers see only the task and the instruction). The worker's result follows the flaw | Quote the instruction next to the part of the task it contradicts or omits |
| `orchestration_error` | An orchestrator decision across delegations: it accepts a report that is unsupported or contradicted by evidence in that report, finishes before the needed facts are established, misreads or mis-combines reports, routes to a role without the needed tools (multi-role pools only), or answers with no supporting report (a guess) | The report text vs the orchestrator's next action and rationale |
| `final_answer_error` | The content needed is established in the reports, but the orchestrator's `finish.answer` gets it wrong: wrong format (units, extra words, list form), a transcription slip, or a different item from what the reports support | The supporting report vs the final answer |
| `worker_error` | The worker departs from a sound instruction, misreads a tool output, computes wrongly, stops early, or states unsupported claims in its report | The tool output vs the worker's report; recomputation |
| `model_capability` | The needed input reached the model, but the model cannot perceive or reason about it well enough: dense image reading, long exact transcription, hard puzzles. There is no clear deviation from instructions or evidence | What was shown (tool output, image) and what the model produced |
| `tool_capability` | The needed information is out of reach of the tool set **by design**: interactive pages, video, page history beyond Wayback snapshots, paywalls | The routes tried and why each one cannot work |
| `question_ambiguity` | The task admits several readings and the run took a defensible one | The two readings and where the run chose |

**Implementation-induced (ours).** Label these separately and never fold them into the agent categories. When
one is the first error, it is the primary category.

| Category | Definition |
|---|---|
| `backend_failure` | Every search or reader backend failed or was rate-limited, or a block, captcha or rate-limit page was served as content |
| `blocklist_false_positive` | A legitimate page or result was blocked |
| `sandbox_denied` | `run_python` was denied a file, process or host access the task legitimately needs (`sandbox_denied` in the tool record) |
| `paging` | The needed content was on a later page of a tool's output, and the tool's paging made this easy to miss |
| `tool_bug` | A tool returned wrong, garbled or misleading content, or its schema/description promises something it does not do |
| `framework_bug` | A harness or prompt problem: invalid actions, a lost report, a wrong message, a worker cap that hid a result, refiner plumbing |
| `budget_exceeded` | The run or refine budget ended the run (state which limit) |

**Benchmark**

| Category | Definition |
|---|---|
| `reference_error` | The run's answer is what the inputs determine, but the GAIA reference differs (e.g. a typo). Set only by the reviewer after the fact, with the scorer's reference; the run still counts as wrong under the pre-registered scorer |

## Fields per run

| Field | Content |
|---|---|
| `category`, `secondary` | As above; `success` for correct runs |
| `implementation_induced` | true if the primary category is one of ours |
| `location` | `{"actor": "orchestrator" \| "worker:<id>" \| "refiner", "delegation": k, "phase": "instruction" \| "execution" \| "report" \| "decision" \| "final_answer" \| "refine"}` |
| `first_error`, `first_error_evidence` | One sentence stated as a fact you can show, with quotes and locations (transcript heading, LLM call id, tool call number) |
| `error_chain` | 2–4 sentences: how the first error reached the final answer |
| `delegation_related` | Is the first error at, or caused by, a delegation's instruction? `yes` / `no` / `unclear`, plus which `d<k>` |
| `first_meaningful_delegation` | The first delegation whose instruction involves a choice of goal, scope or approach (not merely "read the attached file"). Give the index, whether it is d0, whether it is flawed, and why. This feeds the R3 rubric (`docs/decisions.md`) |
| `would_a_better_instruction_help` | `yes` / `no` / `unclear`: could a better instruction at the first meaningful delegation plausibly change the outcome, with the executor fixed? Say what was missing and whether that was **available at that point** (task, attachment, earlier reports). Never use the ground truth |
| `framework_events` | `invalid_actions`, `tool_limit_reports` (reports with status `tool_limit`), `empty_reports`, `forced_finish`, `n_delegations` |
| `tool_issues` | Backend failures, fallbacks, sandbox denials, blocked pages, paging, with evidence |
| `contamination` | From `scripts/audit_contamination.py`: `confirmed_exposure` (flagged content in a tool result a model received) or `blocked_attempt` (refused; the blocklist worked, not contamination). Contaminated runs are reported separately and excluded from accuracy and headroom estimates |
| `process_notes` | Anything else; for correct runs: well supported or lucky, and why |
| `confidence` | `high` / `medium` / `low` |

## Rules

- The earliest error that made the run fail is the primary category. If an instruction error and a worker error
  both appear, ask which came first and whether the run would have failed without the later one.
- Implementation-induced categories take precedence when they are the first error, because those failures are
  ours, not the model's.
- Infrastructure failures (`backend_failure`, `budget_exceeded`) are reported with their cause and the rerun
  decision, applied the same way in every condition.
- Correct runs are labelled too (`success`): were they well supported or lucky, and were there process problems?
