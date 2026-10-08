# Implementation decisions to revisit

These choices are **not fixed by the spec** (`minimal framework.md`) or the study design, but they affect the
results. Each entry gives the choice, the main alternative, and where it lives. Revise them here and in code
together. Mark revised entries with a date.

Fixed by the user on 2026-10-08: dynamic loop (F1), `refine_at` configurable with default `first` (R3),
Luna split for models (M1), minimal tool set (K1).

## Framework (harness, orchestrator, workers)

| ID | Choice | Alternative | Where |
|---|---|---|---|
| F1 | **Dynamic loop** (AOrchestra-style). Each turn the orchestrator either delegates one subtask or finishes. There is no up-front plan and no replanning step | Plan first, then execute | `harness.py` `_loop` |
| F2 | Orchestrator actions come as **strict JSON-schema output** `{rationale, action, worker_id, instruction, answer}`, not function calls. Luna at effort high cannot call functions on Chat Completions | Function calling (needs a model or effort that allows tools) | `agents/orchestrator.py`, `prompts.ORCHESTRATOR_ACTION_SCHEMA` |
| F3 | The **orchestrator gives the final answer itself** (`finish.answer`); there is no separate answerer. GAIA's own format rule is in its system prompt | A separate formatting step (OWL had one and it lost correct answers) | `prompts.orchestrator_system` |
| F4 | The orchestrator delegates to **roles**. A role maps to one fixed executor worker and to its probe workers. The `worker_id` in an action is a role id | Expose workers directly (then worker selection mixes with instruction effects) | `config.py` `RoleSpec`, `configs/pools/` |
| F5 | A worker receives **only `original_task` + `instruction`** (per the spec), never earlier reports. The orchestrator must copy needed results into the instruction. Workers keep no state between calls | Pass dependency results automatically | `prompts.worker_request`, `agents/worker.py` |
| F6 | After a refined delegation, the orchestrator's history shows **the instruction actually sent**, followed by the report (`show_final_instruction: true`). It never sees the probe dialogue | Show only the report (the orchestrator would not know the instruction changed) | `harness._delegate`, `prompts.report_message` |
| F7 | `max_delegations` = 12, then a forced `finish`. An invalid action (unknown worker, missing field) gets error feedback, up to 2 retries, then the run ends as `error` | Other caps; a skip instead of an error | `RunConfig`, `Orchestrator` |
| F8 | Worker tool cap: 20 calls per request. At the cap, one forced **report turn** (`tool_choice: none`); the subtask does not fail | Fail the subtask (OWL) | `WorkerSpec.max_tool_calls`, `Worker.run` |
| F9 | The report is **free text**. The worker prompt asks for the result with evidence, assumptions, failures and created file paths. There is no structured success flag | Structured report (a JSON schema with status) | `prompts.worker_system` |
| F10 | **Sequential** everything: one delegation at a time, and probes run one after another | Parallel probes (faster; the order of calls would no longer be deterministic) | `harness`, `refine/review.py` |
| F11 | The original task is the GAIA question plus `Attached file: attachments/<name>` when there is an attachment | Other phrasing; inline file content | `prompts.original_task_text` |
| F12 | The orchestrator prompt already asks for specific instructions (scope, interpretation and conditions, what to report). This **makes condition A stronger and may reduce headroom** | A neutral prompt | `prompts.orchestrator_system` |
| F13 | Worker system prompt = the worker's own text from YAML + a shared block (team context, tool list, report rules) | Fully per-worker prompts | `prompts.worker_system`, `configs/pools/*.yaml` |

## Refiner (the method module)

| ID | Choice | Alternative | Where |
|---|---|---|---|
| R1 | The refiner sees **only `RefineRequest`** (original task, draft, target worker, probe workers) plus the worker profiles. It never sees the orchestrator's history, other reports, traces or answers | Give it the orchestrator's history (more context, but less portable, and B/C would see more than the worker) | `refine/base.py` |
| R2 | The refiner uses the orchestrator's model (`luna-high`) in its **own conversation**. Nothing it does enters the orchestrator's history | Refine inside the orchestrator's conversation | `RunConfig.refiner_model`, `harness._Ctx.llm` |
| R3 | `refine_at: first` = the first delegation **this run handles**: d0 for a fresh run, the restored delegation for a restore. The design's "first *meaningful* delegation" (a versioned LLM-judge rubric) is **not implemented yet**; today it is simply the first delegation | Implement the judge before Exp 2 | `harness._refine_here` |
| R4 | **B = predicted answers for the same probe slots as C** (one per probe worker × sample), followed by the same analyze → verify → rewrite pipeline. C−B then isolates where the answers come from. B's prediction prompt includes the worker's model name | B as a single free-form self-critique | `refine/review.py`, `prompts.simulate_request` |
| R5 | Probe questions: English versions of the spec's four questions (understanding, assumptions, failure, plan), all in one message. A subset can be configured | One question per turn; the Korean text | `prompts.PROBE_QUESTION_TEXT` |
| R6 | Probes run **without tools** by default (no tool schemas are sent, but the system prompt lists the tools). The variant `C_probe_tools` allows up to 6 calls on a scratch copy | Tools on by default | `RefinerConfig.probe_tools`, `configs/refiners/` |
| R7 | **Follow-ups: C only**, up to 2 in total. Each continues its probe conversation and its scratch workspace, followed by one re-analysis. B has none | Follow-ups for B too (simulated); more rounds | `ProbeRefiner.followup` |
| R8 | **Verification in B and C**: the analysis may request up to 2 checks. Each runs on the role's executor worker, with tools (cap 10), on a scratch copy. The orchestrator never uses tools itself (spec) | No verification; verification by the probe worker | `_ReviewRefiner._verify` |
| R9 | No actionable issue (none, or all `not_relevant`) → the draft is kept and **no rewrite call** is made (`no_issues`). The rewrite step may also return `unchanged` | Always rewrite | `_ReviewRefiner._refine` |
| R10 | Refinement budget per delegation, **the same for B and C**: 60 LLM calls, $1.00, 8 worker calls. When it is exceeded, the **draft is kept** (`budget_exceeded`). Actual spend is logged per stage | Use the best partial result | `RefinerConfig.budget` |
| R11 | Rewrite rules: keep the goal; state verified facts explicitly; turn unverified claims into checks; write a self-contained instruction; suggested structure `Task / Criteria / Checks / Report` (the spec's example) | Free form | `prompts.rewrite_request` |
| R12 | Connected condition: execution continues the executor's **latest** probe conversation (including follow-ups), with the final instruction as a new turn. Files are never carried over | Continue the first sample; summarise the probe instead | `_ReviewRefiner._execution_history` |
| R13 | The analysis prompt says agreement between answers does not decide correctness; differences only point to ambiguity (design §4) | — | `prompts.analyze_request` |

## Worker pools (configs/pools)

| ID | Choice | Alternative |
|---|---|---|
| P1 | `role_routing`: `web_researcher` (`web_search`, `read_url`, `run_python`) and `file_analyst` (`read_file`, `view_image`, `run_python`), all on `luna`. probe_workers = the executor. `samples_per_worker` = 1 by default (set it above 1 for repeated probes) | More or different roles; "varied" probes (rephrased questions) are not implemented |
| P2 | `redundant`: one `generalist` role; candidates `gen_luna` and `gen_gemini` (same prompt and tools); executor fixed to `gen_luna` | GPT-4o as the second candidate; **the Gemini model is an open decision** |
| P3 | `single`: one generalist on `luna`, used as the smallest baseline and in tests | — |
| P4 | A role's probe workers must have **the same tools as its executor** (checked in tests) | Allow heterogeneous tools |

## Runtime

| ID | Choice | Alternative | Where |
|---|---|---|---|
| T1 | A **checkpoint at every delegation point**, taken before refinement. State: orchestrator messages, pending action, delegation log, budget counters, web pin, code-run counter, a copy of the workspace. The fingerprint is verified on restore. A restore refuses if the model identities, tools/blocklist version or prompts version differ | Checkpoint only the chosen point | `harness.save_checkpoint`, `Run.restore` |
| T2 | Each probe or verification label gets a **scratch copy** of the workspace at that point, kept under `scratch/` for audit. The **web cache is shared**: a probe can warm the cache, so the execution gets identical results for identical requests, not new information | Separate cache per condition | `harness._Ctx.toolbox` |
| T3 | Run budget: 400 LLM calls, 400 tool calls, $5, 3 h. **No hard-deadline watchdog** (the old pilot had one), so a tool stuck inside a library can overrun the wall time | Add the watchdog | `RunConfig.budget`, `scripts/run_task.py` |
| T4 | Transient errors (timeout, connection, 429, 5xx) are retried up to 2× with 5 s/20 s backoff; every attempt counts toward the budget. 401/402/404, a wrong provider, or a missing or too-high cost → `error_infra` | — | `llm/client.py` |
| T5 | **Plain HTTP to OpenRouter** (no SDK, no framework). `luna-high`'s reasoning is not re-sent across orchestrator turns. Workers keep `reasoning_details` when the model returns them (needed for Gemini) | Responses API (would allow tools with reasoning) | `llm/client.py`, `llm/specs.py` |
| T6 | Run statuses: `ok`, `budget_exceeded`, `error_infra`, `error`, `error_init`. All count as failures in scoring except `ok` | — | `harness._guarded` |

## Tools

| ID | Choice | Alternative | Where |
|---|---|---|---|
| K1 | Tool set `web_search`, `read_url` (+ `date` → Wayback snapshot), `read_file`, `view_image`, `run_python`. **Dropped:** Wikipedia tools, the revision lookup, the interactive browser, Firecrawl | Add a browser, or a Wikipedia revisions tool (some GAIA tasks need page history) | `tools/toolbox.py` |
| K2 | Backends, cache, blocklist v3 and anti-bot detection were copied with **no behaviour change**. New cache file `outputs/cache/tools_v1.sqlite`, not shared with the old pilot | Reuse the old pilot's `tools_v3.sqlite` (warmer, and the same reader behaviour) | `tools/config.py` |
| K3 | `view_image` accepts local paths or URLs; images over 4096 px are downscaled; images arrive as a user message after that turn's tool results | Return a description from a model (an uncontrolled extra model) | `tools/toolbox.py`, `agents/worker.py` |
| K4 | `run_python` output: `[stdout]` / `[stderr]` / `[exit code]`; 60 s timeout; 40K characters; Landlock sandbox with no network and no processes | — | `tools/sandbox.py` |
| K5 | The Crawl4AI service can be shared with the old pilot through the env var `CRAWL4AI_ENDPOINT`; only one instance can hold the default port | Run a separate instance (`CRAWL4AI_PORT`) | `tools/config.py`, `scripts/crawl4ai/` |

## Data, models, evaluation

| ID | Choice | Alternative |
|---|---|---|
| E1 | Splits and scope were copied unchanged from the old pilot: 153 in-scope tasks, `eval_v1` (24, Exp 2 only, guarded by `--allow-eval`) and `exploration_v1` (129). `executor_selection_v1` (12 exploration tasks) serves as a dev set with known OWL-era failure labels | Redraw (would need a new version suffix) |
| E2 | Scoring: extraction rule v1 + the official GAIA scorer. Per-task success over reps, then the equal-weight mean over tasks | — |
| M1 | Orchestrator and refiner: `luna-high`; workers: `luna`; `gemini` only as the second candidate in `redundant` | `gpt4o` for every role |
| M2 | Only OpenRouter keys (`luna-high`, `luna`, `gpt4o`, `gemini`); **no vLLM path** | Port the vLLM adapter if open models return |
