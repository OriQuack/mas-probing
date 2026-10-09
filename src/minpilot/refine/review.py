"""Conditions B and C: one review pipeline, two sources of answers.

    collect answers -> analyze (issues, follow-ups, verifications) -> [C: follow-ups -> re-analyze]
                    -> verify (checks delegated to workers) -> rewrite once

- C `ProbeRefiner`: the answers come from the real probe workers (call_worker with the probe questions).
- B `SelfReviewRefiner`: the orchestrator-side model predicts each probe worker's answers itself, one prediction
  per (probe worker, sample), i.e. the same slots C fills with real answers.
Everything after collection (analysis prompt, verification access, rewrite rules, budget) is shared, so C-B
isolates where the answers come from.

Stopping rules (same for B and C): no issue that needs a change -> the draft is kept without a rewrite call
(`no_issues`); the refinement budget runs out -> the draft is kept (`budget_exceeded`); a structured reply
(prediction, analysis, rewrite) that is truncated, not valid JSON or inconsistent (unknown ids) after one retry
-> the draft is kept (`refine_error`), never merged into `no_issues`/`unchanged`. The run's own budget still ends
the run.
"""

from __future__ import annotations

from minpilot.agents import prompts
from minpilot.config import RefinerConfig
from minpilot.refine.base import RefineContext, RefineRequest, RefineResult
from minpilot.runtime.trace import BudgetExceeded


class RefineError(Exception):
    """A refiner model reply that stayed unusable after the retry (truncated, invalid JSON, inconsistent)."""

    def __init__(self, stage: str, problems: list[str]):
        super().__init__(f"{stage}: {problems}")
        self.stage = stage
        self.problems = problems


DECISIONS = ("resolved_from_task", "needs_verification", "not_relevant")


def check_analysis(d: dict, response_ids: set[str], role_ids: set[str]) -> str | None:
    issues = d.get("issues")
    if not isinstance(issues, list) or not isinstance(d.get("verifications"), list) \
            or not isinstance(d.get("followups"), list):
        return "missing issues/followups/verifications lists"
    ids = [i.get("id") for i in issues if isinstance(i, dict)]
    if len(ids) != len(issues) or len(set(ids)) != len(ids):
        return "issues without unique ids"
    if bad := [i.get("decision") for i in issues if i.get("decision") not in DECISIONS]:
        return f"unknown decisions {bad}"
    if bad := [v.get("issue_id") for v in d["verifications"] if v.get("issue_id") not in ids]:
        return f"verifications refer to unknown issues {bad}"
    if bad := [v.get("worker_id") for v in d["verifications"] if v.get("worker_id") not in role_ids]:
        return f"verifications name unknown workers {bad}"
    if bad := [f.get("response_id") for f in d["followups"] if f.get("response_id") not in response_ids]:
        return f"follow-ups refer to unknown answers {bad}"
    return None


def check_rewrite(d: dict) -> str | None:
    if d.get("unchanged") is True:
        return None
    if not (d.get("instruction") or "").strip():
        return "empty instruction without unchanged=true"
    return None


class _ReviewRefiner:
    source = ""  # "probe" | "self_review"
    retries = 1  # one more attempt for an unusable structured reply

    def __init__(self, cfg: RefinerConfig):
        self.cfg = cfg

    # -- to implement -------------------------------------------------------------------------
    def collect(self, req: RefineRequest, ctx: RefineContext, log: dict) -> list[dict]:
        raise NotImplementedError

    def followup(self, req: RefineRequest, ctx: RefineContext, responses: list[dict], asks: list[dict],
                 log: dict) -> list[dict]:
        return []

    # -- shared pipeline ----------------------------------------------------------------------
    def refine(self, req: RefineRequest, ctx: RefineContext) -> RefineResult:
        log: dict = {"refiner": self.cfg.name, "kind": self.cfg.kind, "draft": req.draft_instruction,
                     "target_worker": req.target_worker, "probe_workers": list(req.probe_workers)}
        try:
            with ctx.budget_scope(self.cfg):
                return self._refine(req, ctx, log)
        except BudgetExceeded as e:
            if e.scope != "refine":
                raise
            log["budget_exceeded"] = e.what
            return RefineResult(req.draft_instruction, False, "budget_exceeded", log)
        except RefineError as e:
            log["refine_error"] = {"stage": e.stage, "problems": e.problems}
            return RefineResult(req.draft_instruction, False, "refine_error", log)

    def _call(self, ctx: RefineContext, messages: list[dict], *, stage: str, schema_name: str | None = None,
              schema: dict | None = None, check=None) -> tuple[dict | str, list[str]]:
        """A refiner model call with validation: retried once if the reply is truncated, empty, not JSON (for
        schema calls) or fails `check`; raises RefineError if it is still unusable."""
        problems = []
        for _ in range(1 + self.retries):
            res = ctx.llm(messages, stage=stage, schema_name=schema_name, schema=schema)
            if res.finish_reason == "length":
                problem = "truncated (finish_reason=length)"
            elif schema is None:
                problem = None if (res.content or "").strip() else "empty reply"
            elif not isinstance(res.parsed, dict):
                problem = f"not valid JSON: {(res.content or '')[:200]!r}"
            else:
                problem = check(res.parsed) if check else None
            if problem is None:
                return (res.parsed if schema is not None else res.content), problems
            problems.append(problem)
        raise RefineError(stage, problems)

    def _refine(self, req: RefineRequest, ctx: RefineContext, log: dict) -> RefineResult:
        responses = self.collect(req, ctx, log)
        log["responses"] = [{k: v for k, v in r.items() if k != "messages"} for r in responses]
        if not self.cfg.rewrite:  # answers only: no analysis, checks or rewrite; the draft is executed as is
            return RefineResult(req.draft_instruction, False, "answers_only", log,
                                self._execution_history(req, responses))
        n_follow = self.cfg.max_followups if self.source == "probe" else 0
        analysis = self._analyze(req, ctx, responses, n_follow)
        log["analysis"] = [analysis]
        asks = (analysis.get("followups") or [])[:n_follow]
        if asks:
            extra = self.followup(req, ctx, responses, asks, log)
            log["followups"] = [{k: v for k, v in r.items() if k != "messages"} for r in extra]
            if extra:
                responses = responses + extra
                analysis = self._analyze(req, ctx, responses, 0)
                log["analysis"].append(analysis)
        issues = analysis.get("issues") or []
        actionable = [i for i in issues if i.get("decision") != "not_relevant"]
        verifications = self._verify(req, ctx, analysis, {i.get("id") for i in issues if i not in actionable}, log)
        log["verifications"] = verifications
        if not actionable:
            return RefineResult(req.draft_instruction, False, "no_issues", log,
                                self._execution_history(req, responses))
        out, problems = self._call(
            ctx, [{"role": "system", "content": prompts.analyze_system()},
                  {"role": "user", "content": prompts.rewrite_request(req.original_task, req.draft_instruction,
                                                                      actionable, verifications,
                                                                      ctx.worker_profile(req.target_worker))}],
            stage="refine.rewrite", schema_name="rewrite", schema=prompts.REWRITE_SCHEMA, check=check_rewrite)
        log["rewrite"] = out
        if problems:
            log["rewrite_retried"] = problems
        new = (out.get("instruction") or "").strip()
        if not new or out.get("unchanged"):
            return RefineResult(req.draft_instruction, False, "unchanged", log, self._execution_history(req, responses))
        changed = new != req.draft_instruction.strip()
        return RefineResult(new, changed, "rewritten" if changed else "unchanged", log,
                            self._execution_history(req, responses))

    def _analyze(self, req: RefineRequest, ctx: RefineContext, responses: list[dict], followups: int) -> dict:
        target = ctx.worker_profile(req.target_worker)
        msg = prompts.analyze_request(req.original_task, req.draft_instruction, target,
                                      [{"id": r["id"], "who": r["who"], "text": r["text"]} for r in responses],
                                      self.source, self.cfg.max_verifications, ctx.roles(), followups)
        role_ids = {r["id"] for r in ctx.roles()}
        out, problems = self._call(
            ctx, [{"role": "system", "content": prompts.analyze_system()}, {"role": "user", "content": msg}],
            stage="refine.analyze", schema_name="review_analysis", schema=prompts.ANALYZE_SCHEMA,
            check=lambda d: check_analysis(d, {r["id"] for r in responses}, role_ids))
        return {**out, "retried": problems} if problems else out

    def _verify(self, req: RefineRequest, ctx: RefineContext, analysis: dict, not_relevant_ids: set,
                log: dict) -> list[dict]:
        """Run the requested checks (at most max_verifications), except those for issues marked `not_relevant`."""
        out = []
        asked = [v for v in analysis.get("verifications") or [] if v.get("issue_id") not in not_relevant_ids]
        skipped = len(analysis.get("verifications") or []) - len(asked)
        if skipped:
            log["verifications_skipped_not_relevant"] = skipped
        for i, v in enumerate(asked[:self.cfg.max_verifications]):
            worker = ctx.role_executor(v.get("worker_id", ""))
            entry = {"issue_id": v.get("issue_id"), "worker_id": v.get("worker_id"), "instruction": v.get("instruction")}
            if worker is None:
                out.append({**entry, "report": "(not run: unknown worker)", "status": "skipped"})
                continue
            call = ctx.call_worker(worker, req.original_task, prompts.verify_instruction(v.get("instruction", "")),
                                   stage="refine.verify", allow_tools=True,
                                   max_tool_calls=self.cfg.verify_max_tool_calls, label=f"verify{i + 1}")
            out.append({**entry, "executed_by": worker, "report": call.report, "status": call.status,
                        "n_tool_calls": call.n_tool_calls})
        return out

    def _execution_history(self, req: RefineRequest, responses: list[dict]) -> list[dict] | None:
        if not (self.cfg.connect_probe_to_execution and self.source == "probe"):
            return None
        # the executor's first probe conversation (with its follow-ups, if any)
        convs = [r for r in responses if r.get("worker_id") == req.target_worker and r.get("messages")]
        return convs[-1]["messages"] if convs else None


class ProbeRefiner(_ReviewRefiner):
    """C: real worker probes."""

    source = "probe"

    def collect(self, req: RefineRequest, ctx: RefineContext, log: dict) -> list[dict]:
        cfg = self.cfg
        instruction = prompts.probe_instruction(req.draft_instruction, cfg.questions, cfg.probe_tools,
                                                cfg.probe_max_tool_calls)
        log["probe_instruction"] = instruction
        out = []
        for w in req.probe_workers:
            for s in range(cfg.samples_per_worker):
                rid = f"r{len(out) + 1}"
                call = ctx.call_worker(w, req.original_task, instruction, stage="refine.probe",
                                       allow_tools=cfg.probe_tools, max_tool_calls=cfg.probe_max_tool_calls,
                                       label=f"probe_{rid}")
                out.append({"id": rid, "who": f"worker {w}, sample {s + 1}", "worker_id": w, "sample": s,
                            "text": call.report, "status": call.status, "n_tool_calls": call.n_tool_calls,
                            "messages": call.messages})
        return out

    def followup(self, req, ctx, responses, asks, log):
        by_id = {r["id"]: r for r in responses}
        out = []
        for a in asks:
            r = by_id.get(a.get("response_id"))
            if r is None:
                continue
            # the follow-up continues that probe conversation (and its scratch workspace, see harness)
            call = ctx.call_worker(r["worker_id"], req.original_task, "", stage="refine.followup",
                                   allow_tools=self.cfg.probe_tools, max_tool_calls=self.cfg.probe_max_tool_calls,
                                   history=r["messages"], user_message=prompts.followup_message(a["question"]),
                                   label=f"probe_{r['id']}")
            new = {"id": f"{r['id']}.f{len(out) + 1}", "who": f"{r['who']}, follow-up: {a['question']}",
                   "worker_id": r["worker_id"], "sample": r["sample"], "text": call.report, "status": call.status,
                   "n_tool_calls": call.n_tool_calls, "messages": call.messages}
            r["messages"] = call.messages  # later follow-ups / connected execution continue the longer conversation
            out.append(new)
        return out


class SelfReviewRefiner(_ReviewRefiner):
    """B: the orchestrator-side model predicts the probe answers itself (no worker probes)."""

    source = "self_review"

    def collect(self, req: RefineRequest, ctx: RefineContext, log: dict) -> list[dict]:
        out = []
        for w in req.probe_workers:
            profile = ctx.worker_profile(w)
            for s in range(self.cfg.samples_per_worker):
                rid = f"r{len(out) + 1}"
                text, _ = self._call(ctx, [{"role": "system", "content": prompts.simulate_system()},
                                           {"role": "user", "content": prompts.simulate_request(
                                               req.original_task, req.draft_instruction, profile, self.cfg.questions)}],
                                     stage="refine.review")
                out.append({"id": rid, "who": f"predicted for worker {w}, sample {s + 1}", "worker_id": w,
                            "sample": s, "text": text})
        return out
