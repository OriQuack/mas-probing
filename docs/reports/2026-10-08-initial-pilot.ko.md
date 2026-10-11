> 과거 실험 보고서입니다. 해석·수치의 정정은 [최신 종합 보고서](2026-10-10-synthesis.ko.md)를 우선하세요.

# min_pilot: live test, bug fixes, pilot baseline and trace labels (night of 2026-10-08)

## What was run

| Session | What | Runs | Result |
|---|---|---|---|
| `../live1/` | Live test on 3 non-pilot exploration tasks (image 9318445f, text file 389793a7, L2 web 023e9d44): fresh A (`role_routing`, `redundant`), then restores under B, C, C-redundant (Gemini probe), C with probe tools, C connected | 11 | All mechanics worked (7/7 fingerprint matches). Found the refiner goal-drift bug (below) |
| `pilot-base-20261008T155247Z` | Baseline A on the 12 pilot tasks × 3 (tools v1, blocklist v3). **Bug-finding pass; superseded** | 36 | acc 0.583; all labelled; `labels/SUMMARY.md` |
| `../live2/` | Check of the refiner fix (refiner prompts r2) on 023e9d44: B ×2, C ×2 from one checkpoint | 4 | 3/4 correct (was 0/3: B, C and C-redundant had all answered "Cannot be determined") |
| `pilot-base-v2-20261008T160736Z` | **The baseline**: A on the 12 pilot tasks × 3 (tools v2, blocklist v5) | 36 | **acc 0.667**; all labelled; `labels/SUMMARY.md`. de9887f5 r0, r2 contaminated (excluded) |
| `pilot-base-v2-supp-20261008T162036Z` | 3 clean reps of de9887f5 under blocklist v6 | 3 | 3/3 correct, clean; labelled |
| `aborted-pilot-base-v2-20261008T160501Z` | Stopped after ~1 min to add more blocklist fixes | — | Ignore |

Total model spend for everything above: about **$0.55**. All runs ended `ok` (no infra errors, no budget overruns).

## Bugs found and fixed (details and IDs in `docs/history/decisions-before-cleanup.md`)

1. **Refiner goal drift (R14, refiner prompts r2).** The B/C review verified the task's premises ("I-40 does not
   reach Cincinnati"), and the rewrite turned the subtask into "is the route valid?". B, C and C-redundant all
   answered "Cannot be determined" where A was correct. The analysis and rewrite prompts now treat the task's
   premises as given and keep the subtask's goal. Refiner prompts got their own version (R16), so later method
   changes do not invalidate baseline checkpoints.
2. **Answer leaks through the blocklist (v3 → v5 → v6, K10).** Labellers found a Q/A-aggregator snippet stating
   an answer (bda648d7), a GAIA analysis page stating an answer (de9887f5, 2 runs of the v2 baseline, excluded),
   agent traces/papers quoting tasks, and per-snippet inconsistency (the same URL blocked once, passed later).
   Fixes: URL rules, letters-only quote matching, broader trace rules, **sticky per-run blocking**, and an
   audit-only check for mid-question quotes (L7). A restore may now use a newer blocklist than its checkpoint
   (T8), so these fixes do not invalidate checkpoints.
3. **DuckDuckGo fallback never worked** (the env has `ddgs`, the copied code imported `duckduckgo_search`) (K6a).
4. **Tool records said `ok` for failures** (failed reads/searches, "Error:" outputs) (K6).
5. **`.docx` tables were moved to the end of the text** (K6).
6. **`read_url(date=...)` on a Wayback URL looked up a snapshot of the snapshot** (K6b).
7. **Recovered invalid orchestrator replies were not logged** (F15); **no hard deadline** for stuck runs (T3).
8. Tooling for this work: `run_batch.py`, `render_trace.py`, `audit_contamination.py`, `prepare_labelling.py`,
   `summarize_labels.py`; `docs/evaluation/failure-codebook.md` and `docs/evaluation/labelling-protocol.md` written for min_pilot's
   actors (not the old OWL codebook, L2). Tests: 39 → 49, all passing.

## What the baseline says (pilot-base-v2; details in its `labels/SUMMARY.md`)

- Solid: 3ff6b7a9, b7f857e4 (partly lucky), bda648d7, 114d5fd0, 65638e28, de9887f5 (clean reps), 42576abe.
- Failures by type:
  - **4d51c4bf r2: instruction_error at d0** ("count even-numbered addresses" drops "back of the house"). The
    study's target failure type; the only clear delegation-related failure.
  - 9b54f9d9, cffe0e32: worker reasoning errors (unsupported matching claims, nothing computed); a better
    instruction ("list all pairs / the leftover") is plausible help for 9b54f9d9.
  - 708b99c5: final-answer wording ("Citation count"); F16 would address it.
  - ded28325: GAIA reference typo (reviewer, per the old pilot).
- **Design issues for you to decide:**
  - **F14:** 2 of 12 tasks are answered with **zero delegations** (no intervention point).
  - **F12/R3:** most runs delegate the whole task at d0, so the "first meaningful delegation" is d0 everywhere
    and the instruction is close to a restatement of the task.
  - **Headroom is thin on these 12 tasks:** 1 clear delegation-related failure plus about 2 "better instruction
    plausibly helps" cases. Exp 1 needs more exploration tasks.

## Open items (not changed tonight; each needs a version bump or is a design choice)

F16 (answer field), K7 (search inside long documents), K8 (Wayback "on or before" date), K9 (tell the worker
why a read failed; workers retried blocked URLs up to 22 times), K11 (`file_analyst` sandbox message mentions
`read_url`), K13 (pages written around a task on unknown hosts), K14 (non-English anti-bot stubs), the R3
rubric, and git: nothing is committed yet (each session has `code_snapshot.tar.gz`).
