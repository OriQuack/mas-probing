"""The method module: `InstructionRefiner`.

    refine(request, ctx) -> RefineResult

Input (`RefineRequest`): the original task, the draft instruction, the target (executing) worker, and the probe
workers. Output: the instruction to execute. Inside: probe -> compare answers -> decide/verify issues -> rewrite.
Decomposition, assignment and the final synthesis belong to the harness; this module is the unit that is ported
to other frameworks and compared across conditions.

The refiner sees exactly what the executing worker would see (original task + instruction) plus the worker
profiles. It never sees the orchestrator's history, other reports, failure traces or the answer.

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


@dataclass
class RefineResult:
    instruction: str
    changed: bool
    status: str                    # unchanged | rewritten | no_issues | budget_exceeded | error
    log: dict = field(default_factory=dict)
    # "connected" condition only: the executor's probe conversation, continued by the execution call
    execution_history: list[dict] | None = None


class RefineContext(Protocol):
    def llm(self, messages: list[dict], *, stage: str, schema_name: str | None = None,
            schema: dict | None = None) -> ChatResult: ...

    def call_worker(self, worker_id: str, original_task: str, instruction: str, *, stage: str, allow_tools: bool,
                    max_tool_calls: int | None = None, history: list[dict] | None = None,
                    user_message: str | None = None, label: str = "") -> WorkerCall: ...

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
    from minpilot.refine.review import ProbeRefiner, SelfReviewRefiner

    return {"none": NoRefiner, "self_review": SelfReviewRefiner, "probe": ProbeRefiner}[cfg.kind](cfg)
