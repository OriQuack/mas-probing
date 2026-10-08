"""Conditions B and C: one review pipeline, two sources of answers.

    collect answers -> analyze (issues, follow-ups, verifications) -> [C: follow-ups -> re-analyze]
                    -> verify (checks delegated to workers) -> rewrite once

- C `ProbeRefiner`: the answers come from the real probe workers (call_worker with the probe questions).
- B `SelfReviewRefiner`: the orchestrator-side model predicts each probe worker's answers itself, one prediction
  per (probe worker, sample), i.e. the same slots C fills with real answers.
Everything after collection (analysis prompt, verification access, rewrite rules, budget) is shared, so C-B
isolates where the answers come from.

Stopping rules (same for B and C): no issue that needs a change -> the draft is kept without a rewrite call
(`no_issues`); the refinement budget runs out -> the draft is kept (`budget_exceeded`). The run's own budget
still ends the run.
"""

from __future__ import annotations

from minpilot.agents import prompts
from minpilot.config import RefinerConfig
from minpilot.refine.base import RefineContext, RefineRequest, RefineResult
from minpilot.runtime.trace import BudgetExceeded


class _ReviewRefiner:
    source = ""  # "probe" | "self_review"

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

    def _refine(self, req: RefineRequest, ctx: RefineContext, log: dict) -> RefineResult:
        responses = self.collect(req, ctx, log)
        log["responses"] = [{k: v for k, v in r.items() if k != "messages"} for r in responses]
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
        verifications = self._verify(req, ctx, analysis, log)
        log["verifications"] = verifications
        if not actionable:
            return RefineResult(req.draft_instruction, False, "no_issues", log,
                                self._execution_history(req, responses))
        res = ctx.llm([{"role": "system", "content": prompts.analyze_system()},
                       {"role": "user", "content": prompts.rewrite_request(req.original_task, req.draft_instruction,
                                                                           actionable, verifications)}],
                      stage="refine.rewrite", schema_name="rewrite", schema=prompts.REWRITE_SCHEMA)
        out = res.parsed or {}
        log["rewrite"] = out
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
        res = ctx.llm([{"role": "system", "content": prompts.analyze_system()}, {"role": "user", "content": msg}],
                      stage="refine.analyze", schema_name="review_analysis", schema=prompts.ANALYZE_SCHEMA)
        return res.parsed if isinstance(res.parsed, dict) else {"issues": [], "followups": [], "verifications": [],
                                                                 "parse_error": res.content[:2000]}

    def _verify(self, req: RefineRequest, ctx: RefineContext, analysis: dict, log: dict) -> list[dict]:
        out = []
        for i, v in enumerate((analysis.get("verifications") or [])[:self.cfg.max_verifications]):
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
                res = ctx.llm([{"role": "system", "content": prompts.simulate_system()},
                               {"role": "user", "content": prompts.simulate_request(
                                   req.original_task, req.draft_instruction, profile, self.cfg.questions)}],
                              stage="refine.review")
                out.append({"id": rid, "who": f"predicted for worker {w}, sample {s + 1}", "worker_id": w,
                            "sample": s, "text": res.content})
        return out
