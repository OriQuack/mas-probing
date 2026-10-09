# What min_pilot takes from the previous pilot, and what it leaves out

The previous pilot (`../pilot`) ran on OWL's Workforce. min_pilot shares its research goal but **none of its
framework**. This file records what was copied and why that is safe, and lists the OWL-specific choices that
were deliberately left behind. Check it before copying anything else over.

## Copied (framework-independent)

| min_pilot | From pilot | Change |
|---|---|---|
| `tools/backends.py` | `tools/backends.py` (tools v3) | Firecrawl removed; the endpoint path comes from the config |
| `tools/cache.py`, `tools/antibot.py`, `tools/documents.py` | same | Docstrings only |
| `tools/blocklist.py` | same (rules v3) | Docstring only |
| `tools/crawl4ai_service.py`, `scripts/crawl4ai/*` | same | Endpoint configurable (`CRAWL4AI_ENDPOINT`), env name |
| `tools/sandbox.py` (`run_python`) | `tools/local.py` `execute_code` | New name; plain `[stdout]/[stderr]/[exit code]` output instead of OWL's "Executed the code below" format |
| `tools/web.py` internals (`_call`, `_search`, `_read`, `page_issue`, paging) | `tools/web.py` | New tool names and signatures; no Wikipedia tools and no browser agent |
| `data/gaia.py`, `eval/gaia_scorer.py`, `eval/answer.py` | same | Docstrings; `load_task` added |
| `llm/specs.py` (model keys, routing, cost reservation) | `models/openrouter.py` | No camel; reasoning re-sending is now just a field kept on the message |
| `data/splits/*.csv` | same | None (pre-registered; never redraw) |
| `docs/cluster/slurm.md`, `scripts/slurm/gpu_job.sbatch` | same | Job name |
| `scripts/audit_contamination.py` | same | Rewritten for min_pilot records; browser checks dropped; read URLs checked |
| `scripts/render_trace.py` | same (idea only) | Rewritten for min_pilot's records and actors |
| `docs/failure_codebook.md`, `docs/labelling_protocol.md` | `docs/failure_codebook.md`, session `labels/PROTOCOL.md` | Objectivity rules and implementation-induced categories kept; actors, categories and fields re-defined for min_pilot (decision L2) |
| `scripts/run_batch.py` | `scripts/run_batch.py` (idea only) | Written new: subprocess per run, rep-major, session cost cap |

## Not carried over (OWL-specific)

- **Roles:** the Planner / Coordinator / answerer split. Here one orchestrator decides, delegates and answers.
- **Control flow:** up-front decomposition plus replanning after a failure (at most 2 attempts). Here the loop is dynamic.
- **Coordinator assignment** (`TaskAssignResult`): the orchestrator names the worker itself.
- **Answerer agent:** it saw only subtask results, never the Planner's composed answer, which lost correct answers.
- **Final-subtask "special format" template** from OWL's decompose prompt: it made the Planner invent label formats.
- **Structured worker output** (`TaskResult` via `return_json_response`), including the rule that the first structured result wins and later corrections are dropped.
- **Tool cap behaviour:** 15 calls (+1) and then a failed, unparseable subtask. Here: 20 calls, then a forced report.
- **Dependency results** automatically appended to worker prompts. Here the instruction has to carry what the worker needs (the spec's interface).
- **OWL prompts**, worker descriptions and tool names/signatures (`search_google`, `extract_document_content`, `browse_url`, ...).
- **`browse_url`**, OWL's screenshot browser sub-agent.
- **OWL's attachment sentence** in the question.
- **Thinking policy rationale tied to camel:** native `response_format` for the Coordinator only. Here the split is the same (effort high without tools, effort none with tools), but it follows from the API, not from camel.

## Results that do not carry over

The OWL-era scores, failure labels and checkpoints in `../pilot/outputs/` cannot be compared with min_pilot runs.
The failure *classes* found there are useful hypotheses for Exp 1 candidates:
- Planner constraint drops: 4d51c4bf, 42576abe.
- Answer formatting: 708b99c5.
- Worker matching errors: cffe0e32, 9b54f9d9.
- Tool-blocked task: 65638e28.
- GAIA reference typo: ded28325.

Re-establish each one on min_pilot baselines before using it.
