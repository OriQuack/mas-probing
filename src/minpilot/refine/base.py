"""The method module: `InstructionRefiner`.

    refine(request, ctx) -> RefineResult

Input (`RefineRequest`): the original task, the draft instruction, the delegation's context, the target
(executing) worker, and the probe workers. Output: the instruction to execute, and facts from pre-execution checks
the executor needs (`context_additions`). The context is read-only: every step (prediction, probes, analysis,
checks, rewrite) sees it, and the harness sends it unchanged, with the additions appended under their own heading
(decision F21). Inside: probe -> compare answers -> decide/verify issues -> rewrite.
Decomposition, assignment and the final synthesis belong to the harness; this module is the unit that is ported
to other frameworks and compared across conditions.

The refiner speaks for the orchestrator: from refiner prompts r7 its steps (prediction, analysis, rewrite) are turns
of a copy of the orchestrator's conversation up to this delegation (`orchestrator_messages`), so it knows what the
orchestrator knows and intends; the copy is discarded and only the result reaches the orchestrator's history
(decision R22). Workers asked by the refiner still get only the original task, the context and their instruction.
It never sees the continuation after the checkpoint, failure traces or the answer.

Everything the refiner does goes through `RefineContext`, which the harness implements:
- `llm(...)`: the orchestrator-side model (no tools), in its own conversation, never appended to the
  orchestrator's history;
- `call_worker(...)`: a worker call on an isolated scratch copy of the workspace (files written there never reach
  the execution); worker conversations stay separate unless the caller passes a history;
- a budget scope (`RefinerConfig.budget`) for the whole refinement, on top of the run budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from minpilot.agents.worker import WorkerCall
from minpilot.config import RefinerConfig
from minpilot.llm.client import ChatResult


@dataclass(frozen=True)
class RefineRequest:
    original_task: str
    draft_instruction: str
    target_role: str               # the role the orchestrator delegated to
    target_worker: str             # the fixed executing worker of that role
    probe_workers: tuple[str, ...]
    context: str = ""              # the orchestrator's context for this delegation (read-only, F21)
    # the orchestrator's conversation up to and including the pending delegate action (role/content only); from
    # refiner prompts r7 the review runs as turns of a copy of it, discarded afterwards (decision R22)
    orchestrator_messages: tuple[dict, ...] = ()


@dataclass
class RefineResult:
    instruction: str
    changed: bool
    status: str                    # unchanged | rewritten | no_issues | budget_exceeded | refine_error | ...
    log: dict = field(default_factory=dict)
    # "connected" condition only: the executor's probe conversation, continued by the execution call
    execution_history: list[dict] | None = None
    # facts for the executor from the review (r7), appended after the unchanged context; "" = none
    context_additions: str = ""


class RefineContext(Protocol):
    def llm(self, messages: list[dict], *, stage: str, schema_name: str | None = None,
            schema: dict | None = None) -> ChatResult: ...

    def call_worker(self, worker_id: str, original_task: str, instruction: str, *, stage: str, allow_tools: bool,
                    max_tool_calls: int | None = None, history: list[dict] | None = None,
                    user_message: str | None = None, label: str = "", context: str = "") -> WorkerCall: ...

    def worker_profile(self, worker_id: str) -> dict[str, Any]: ...

    def roles(self) -> list[dict]: ...

    def role_executor(self, role_id: str) -> str | None: ...

    def budget_scope(self, cfg: RefinerConfig): ...


class InstructionRefiner(Protocol):
    cfg: RefinerConfig

    def refine(self, req: RefineRequest, ctx: RefineContext) -> RefineResult: ...


class NoRefiner:
    """Condition A: the draft is executed as is (no extra calls)."""

    def __init__(self, cfg: RefinerConfig):
        self.cfg = cfg

    def refine(self, req: RefineRequest, ctx: RefineContext) -> RefineResult:
        return RefineResult(req.draft_instruction, False, "unchanged", {"refiner": self.cfg.name, "kind": "none"})


def make_refiner(cfg: RefinerConfig) -> InstructionRefiner:
    from minpilot.refine.review import DirectCheckRefiner, ProbeRefiner, SelfReviewRefiner

    return {"none": NoRefiner, "self_review": SelfReviewRefiner, "probe": ProbeRefiner,
            "direct_check": DirectCheckRefiner}[cfg.kind](cfg)
