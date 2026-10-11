"""Shared pre-delegation review: collect -> analyze -> optional follow-ups -> verify -> rewrite.

ProbeRefiner collects real worker answers and SelfReviewRefiner predicts them. Both share the review pipeline.
Review turns use a discarded copy of the orchestrator conversation. Answers are anonymous and
shuffled; probes and checks use isolated workspaces. Budget or validation failures execute the original draft.
"""

from __future__ import annotations

import json
import random
import re

from minpilot import prompts
from minpilot.config import RefinerConfig
from minpilot.refine.base import RefineContext, RefineRequest, RefineResult
from minpilot.runtime.trace import BudgetExceeded


# Shuffle answer order so position cannot identify the worker; tests replace the RNG.
ORDER_RNG = random.SystemRandom()


class RefineError(Exception):
    """A refiner model reply that stayed unusable after the retry (truncated, invalid JSON, inconsistent)."""

    def __init__(self, stage: str, problems: list[str]):
        super().__init__(f"{stage}: {problems}")
        self.stage = stage
        self.problems = problems


# defer_to_execution: the executor checks it during execution (the rewrite states the check and how to proceed);
# Only needs_verification issues get pre-execution checks.
DECISIONS = prompts.DECISIONS


def check_analysis(d: dict, response_ids: set[str], role_ids: set[str],
                   decisions: tuple[str, ...] = DECISIONS) -> str | None:
    issues = d.get("issues")
    if not isinstance(issues, list) or not isinstance(d.get("verifications"), list) \
            or not isinstance(d.get("followups"), list):
        return "missing issues/followups/verifications lists"
    ids = [i.get("id") for i in issues if isinstance(i, dict)]
    if len(ids) != len(issues) or len(set(ids)) != len(ids):
        return "issues without unique ids"
    if bad := [i.get("decision") for i in issues if i.get("decision") not in decisions]:
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


def tool_observations(messages: list[dict], max_chars: int = 1500) -> list[dict]:
    """The tool calls of a probe conversation and what they returned (the source is the tool and its arguments):
    the observations a probe with tools made (R21). `result` is clipped; tool_calls.jsonl has the full record."""
    out, calls = [], {}
    for m in messages or []:
        for tc in m.get("tool_calls") or []:
            calls[tc.get("id")] = tc.get("function") or {}
        if m.get("role") == "tool":
            f = calls.get(m.get("tool_call_id"), {})
            text = m.get("content") if isinstance(m.get("content"), str) else str(m.get("content"))
            out.append({"tool": f.get("name"), "args": f.get("arguments"), "result": text[:max_chars],
                        "result_chars": len(text)})
    return out


_TOKENS = (re.compile(r"https?://[^\s<>\"')\]]+"), re.compile(r"\b\d[\d,.]*\d\b"), re.compile(r'"([^"\n]{3,80})"'))


def observation_overlap(final: str, before: list[str], observed: list[str]) -> list[str]:
    """URLs, numbers (2+ characters) and quoted strings that the final instruction / context additions contain,
    the task, context and draft do not, and some probe tool result does: a mechanical sign that a probe
    observation reached the rewrite (R21; ambiguous cases are judged in labelling)."""
    def toks(text: str) -> set[str]:
        out = set()
        for rx in _TOKENS:
            out |= {(m.group(1) if rx.groups else m.group(0)).rstrip(".,;:").lower() for m in rx.finditer(text or "")}
        return out

    prior = set().union(*(toks(t) for t in before)) if before else set()
    obs = "\n".join(observed).lower()
    return sorted(t for t in toks(final) - prior if t and t in obs)


class _ReviewRefiner:
    source = ""  # "probe" | "self_review"
    retries = 1  # one more attempt for an unusable structured reply

    def __init__(self, cfg: RefinerConfig):
        self.cfg = cfg
        self.version = prompts.REFINER_PROMPTS_VERSION

    # -- to implement -------------------------------------------------------------------------
    def collect(self, req: RefineRequest, ctx: RefineContext, log: dict) -> list[dict]:
        raise NotImplementedError

    def followup(self, req: RefineRequest, ctx: RefineContext, responses: list[dict], asks: list[dict],
                 log: dict) -> list[dict]:
        return []

    # -- shared pipeline ----------------------------------------------------------------------
    def refine(self, req: RefineRequest, ctx: RefineContext) -> RefineResult:
        log: dict = {"refiner": self.cfg.name, "kind": self.cfg.kind, "prompts": self.version,
                     "draft": req.draft_instruction,
                     "context": req.context,
                     "target_worker": req.target_worker, "probe_workers": list(req.probe_workers)}
        # The review's copy of the orchestrator's conversation (grows by the analysis turn and its reply)
        self.conv = self._base_conversation(req)
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

    @staticmethod
    def _base_conversation(req: RefineRequest) -> list[dict]:
        """A copy of the orchestrator's conversation up to the pending delegate action. A port without one gets the
        task and the action only."""
        if req.orchestrator_messages:
            return [{"role": m["role"], "content": m["content"]} for m in req.orchestrator_messages]
        action = {"action": "delegate", "context": req.context, "instruction": req.draft_instruction}
        return [{"role": "user", "content": prompts.orchestrator_task_message(req.original_task)},
                {"role": "assistant", "content": json.dumps(action, ensure_ascii=False)}]

    def _messages(self, user: str) -> list[dict]:
        """Append one review turn to the private copy of the orchestrator conversation."""
        return self.conv + [{"role": "user", "content": user}]

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
        verifications = self._verify(req, ctx, analysis, log)
        log["verifications"] = verifications
        if not actionable:
            return RefineResult(req.draft_instruction, False, "no_issues", log,
                                self._execution_history(req, responses))
        target = ctx.worker_profile(req.target_worker)
        msg = prompts.rewrite_request(verifications, target, bool(req.context.strip()))
        out, problems = self._call(ctx, self._messages(msg),
                                   stage="refine.rewrite", schema_name="rewrite", schema=prompts.REWRITE_SCHEMA,
                                   check=check_rewrite)
        log["rewrite"] = out
        if problems:
            log["rewrite_retried"] = problems
        new = (out.get("instruction") or "").strip()
        if not new or out.get("unchanged"):
            return RefineResult(req.draft_instruction, False, "unchanged", log, self._execution_history(req, responses))
        changed = new != req.draft_instruction.strip()
        additions = (out.get("context_additions") or "").strip()
        if self.source == "probe" and self.cfg.probe_tools:
            observed = [o["result"] for r in responses for o in tool_observations(r.get("messages"), 10 ** 7)]
            log["observations_in_rewrite"] = observation_overlap(
                f"{new}\n{additions}", [req.original_task, req.context, req.draft_instruction], observed)
        return RefineResult(new if changed else req.draft_instruction, changed,
                            "rewritten" if (changed or additions) else "unchanged", log,
                            self._execution_history(req, responses), context_additions=additions)

    def _analyze(self, req: RefineRequest, ctx: RefineContext, responses: list[dict], followups: int) -> dict:
        target = ctx.worker_profile(req.target_worker)
        answers = [{"id": r["id"], "who": r["who"], "text": r["text"]} for r in responses]
        msg = prompts.analyze_request(target, answers, self.source, self.cfg.max_verifications, ctx.roles(), followups,
                                bool(req.context.strip()),
                                observations=self.source == "probe" and self.cfg.probe_tools)
        role_ids = {r["id"] for r in ctx.roles()}
        messages = self._messages(msg)
        out, problems = self._call(
            ctx, messages, stage="refine.analyze", schema_name="review_analysis", schema=prompts.ANALYZE_SCHEMA,
            check=lambda d: check_analysis(d, {r["id"] for r in responses}, role_ids, prompts.DECISIONS))
        self.conv = messages + [{"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}]
        return {**out, "retried": problems} if problems else out

    def _verify(self, req: RefineRequest, ctx: RefineContext, analysis: dict, log: dict) -> list[dict]:
        """Run the requested checks (at most max_verifications, in the order given) for `needs_verification`
        issues only; checks requested for issues with another decision are not run (counted by decision)."""
        out = []
        decision = {i.get("id"): i.get("decision") for i in analysis.get("issues") or []}
        requested = analysis.get("verifications") or []
        asked = [v for v in requested if decision.get(v.get("issue_id")) == "needs_verification"]
        skipped: dict[str, int] = {}
        for v in requested:
            if v not in asked:
                d = decision.get(v.get("issue_id"))
                skipped[d] = skipped.get(d, 0) + 1
        if skipped:
            log["verifications_skipped"] = skipped
        for i, v in enumerate(asked[:self.cfg.max_verifications]):
            worker = ctx.role_executor(v.get("worker_id", ""))
            entry = {"issue_id": v.get("issue_id"), "worker_id": v.get("worker_id"), "instruction": v.get("instruction")}
            if worker is None:
                out.append({**entry, "report": "(not run: unknown worker)", "status": "skipped"})
                continue
            call = ctx.call_worker(worker, req.original_task, prompts.verify_instruction(v.get("instruction", "")),
                                   stage="refine.verify", allow_tools=True, context=req.context,
                                   max_tool_calls=self.cfg.verify_max_tool_calls, label=f"verify{i + 1}")
            out.append({**entry, "executed_by": worker, "report": call.report, "status": call.status,
                        "n_tool_calls": call.n_tool_calls})
        return out

    def _parsed(self, text: str) -> dict:
        """The four labelled items of an answer, for the log (None if unlabelled)."""
        return {"parsed": prompts.parse_probe(text)}

    def _execution_history(self, req: RefineRequest, responses: list[dict]) -> list[dict] | None:
        if not (self.cfg.connect_probe_to_execution and self.source == "probe"):
            return None
        # the executor's first probe conversation (with its follow-ups, if any)
        convs = [r for r in responses if r.get("worker_id") == req.target_worker and r.get("messages")]
        return convs[-1]["messages"] if convs else None


class ProbeRefiner(_ReviewRefiner):
    """Collect real worker probe answers."""

    source = "probe"

    def collect(self, req: RefineRequest, ctx: RefineContext, log: dict) -> list[dict]:
        cfg = self.cfg
        instruction = prompts.probe_instruction(req.draft_instruction, cfg.probe_tools, cfg.probe_max_tool_calls)
        log["probe_instruction"] = instruction
        workers = list(req.probe_workers)
        ORDER_RNG.shuffle(workers)
        log["probe_order"] = workers
        out = []
        for k, w in enumerate(workers):
            for s in range(cfg.samples_per_worker):
                rid = f"r{len(out) + 1}"
                call = ctx.call_worker(w, req.original_task, instruction, stage="refine.probe", context=req.context,
                                       allow_tools=cfg.probe_tools, max_tool_calls=cfg.probe_max_tool_calls,
                                       label=f"probe_{rid}")
                who = f"respondent {k + 1}"
                if cfg.samples_per_worker > 1:
                    who += f", sample {s + 1}"
                out.append({"id": rid, "who": who, "worker_id": w, "sample": s,
                            "text": call.report, "status": call.status, "n_tool_calls": call.n_tool_calls,
                            "messages": call.messages, **self._parsed(call.report)})
                if cfg.probe_tools:  # what the probe observed, and from where (R21)
                    log.setdefault("probe_observations", []).extend(
                        {"response_id": rid, **o} for o in tool_observations(call.messages))
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
    """Predict worker probe answers without calling the workers."""

    source = "self_review"

    def collect(self, req: RefineRequest, ctx: RefineContext, log: dict) -> list[dict]:
        out = []
        for w in req.probe_workers:
            profile = ctx.worker_profile(w)
            for s in range(self.cfg.samples_per_worker):
                rid = f"r{len(out) + 1}"
                # Each prediction starts from the copy of the orchestrator's conversation (independent)
                msg = prompts.simulate_request(req.original_task, req.draft_instruction, profile, req.context)
                text, _ = self._call(ctx, self._messages(msg), stage="refine.review")
                who = f"predicted, sample {s + 1}"
                out.append({"id": rid, "who": who, "worker_id": w,
                            "sample": s, "text": text, **self._parsed(text)})
        return out
