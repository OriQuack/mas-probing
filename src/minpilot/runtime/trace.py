"""Run trace and budgets: one `Trace` per run.

Records (JSONL files in the run dir):
- `llm_calls.jsonl`  one record per model request attempt (`started`, then `ok` / `error`), with the stage tags
                     below, usage, cost, provider and latency. Request messages are stored by hash.
- `messages.jsonl`   each distinct message once (`{"h", "m"}`).
- `tool_calls.jsonl` one record per tool call (`started`, then the result record), with the stage tags.
- `events.jsonl`     orchestrator actions, delegations, refinement steps, checkpoints, errors.

Stage tags. Every record carries the current tags (`stage`, `delegation`, `worker`, `role`, ...), set with
`trace.tags(...)`. Stages used by the harness: `orchestrator`, `execution`, and the refinement stages
`refine.review` (B's simulated worker responses), `refine.probe`, `refine.followup`, `refine.analyze`,
`refine.verify`, `refine.rewrite`. Cost buckets of the design (prefix / extra deliberation / verification /
rewrite / post-delegation execution) are computed from (stage, delegation) relative to the intervention point.

Budgets. A stack of `BudgetScope`s: the run's scope is always active; refinement pushes its own scope, so a
refinement is capped on its own and still counts toward the run. Every model request reserves its worst-case
cost first (`before_llm`), every tool call checks first (`before_tool`), and the request timeout is capped at
the remaining wall time. Exceeding any active scope raises `BudgetExceeded(scope_name)`.

Costs (review 2026-10-09, F5). `cost_usd` = `llm_usd` + `tool_usd` (paid tool calls priced in runtime/costs.py);
budgets limit the total. `tool_usd_cold` prices the same tool calls as if the cache were empty, so condition order
(warm cache) can be separated from cost differences. LLM attempts that end without a bill (timeouts, transport
errors) count as $0 and are counted in `unknown_cost_calls`.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from minpilot.runtime.costs import MAX_TOOL_CALL_USD, TOOL_USD_PER_CREDIT, credits_usd


class InfraError(Exception):
    """Account, credit, routing or provider-verification failure: the run ends as `error_infra`."""


class BudgetExceeded(Exception):
    def __init__(self, scope: str, what: str):
        super().__init__(f"budget exceeded in scope {scope!r}: {what}")
        self.scope = scope
        self.what = what


@dataclass
class Limits:
    max_llm_calls: int | None = None
    max_tool_calls: int | None = None
    max_cost_usd: float | None = None
    max_wall_s: float | None = None
    max_worker_calls: int | None = None  # refinement scopes: worker calls (probes, follow-ups, verifications)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Limits":
        return cls(**(d or {}))


@dataclass
class BudgetScope:
    name: str
    limits: Limits
    llm_calls: int = 0
    tool_calls: int = 0
    worker_calls: int = 0
    cost_usd: float = 0.0          # total: LLM + paid tools (what budgets limit)
    llm_usd: float = 0.0
    tool_usd: float = 0.0          # billed tool calls (cache hits cost nothing)
    tool_usd_cold: float = 0.0     # the same calls as if the cache were empty (cold-cache equivalent)
    unknown_cost_calls: int = 0    # LLM attempts whose billing is unknown (timeouts, transport errors), counted $0
    reserved_usd: float = 0.0
    started: float = field(default_factory=time.monotonic)
    wall_offset_s: float = 0.0  # wall time spent before a restore

    def wall_s(self) -> float:
        return self.wall_offset_s + time.monotonic() - self.started

    def remaining_wall_s(self) -> float | None:
        return None if self.limits.max_wall_s is None else self.limits.max_wall_s - self.wall_s()

    def counters(self) -> dict:
        return {"llm_calls": self.llm_calls, "tool_calls": self.tool_calls, "worker_calls": self.worker_calls,
                "cost_usd": round(self.cost_usd, 8), "llm_usd": round(self.llm_usd, 8),
                "tool_usd": round(self.tool_usd, 8), "tool_usd_cold": round(self.tool_usd_cold, 8),
                "unknown_cost_calls": self.unknown_cost_calls, "wall_s": round(self.wall_s(), 3)}


_TAGS: contextvars.ContextVar[dict] = contextvars.ContextVar("minpilot_tags", default={})


def reasoning_tokens(usage: dict) -> int:
    return int(((usage or {}).get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)


class Trace:
    def __init__(self, run_dir: Path | str | None, limits: Limits | None = None):
        self.run_dir = Path(run_dir) if run_dir else None
        if self.run_dir:
            self.run_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._seen: set[str] = set()
        self._ids = 0
        self.scopes: list[BudgetScope] = [BudgetScope("run", limits or Limits())]
        self.usage: dict[str, dict[str, float]] = {}  # stage -> totals

    # -- tags --------------------------------------------------------------------------------
    @contextlib.contextmanager
    def tags(self, **tags) -> Iterator[None]:
        token = _TAGS.set({**_TAGS.get(), **tags})
        try:
            yield
        finally:
            _TAGS.reset(token)

    @staticmethod
    def current_tags() -> dict:
        return dict(_TAGS.get())

    # -- budgets -----------------------------------------------------------------------------
    @property
    def run_scope(self) -> BudgetScope:
        return self.scopes[0]

    @contextlib.contextmanager
    def budget_scope(self, name: str, limits: Limits) -> Iterator[BudgetScope]:
        scope = BudgetScope(name, limits)
        with self._lock:
            self.scopes.append(scope)
        try:
            yield scope
        finally:
            with self._lock:
                self.scopes.remove(scope)

    def _check(self, scope: BudgetScope, *, llm: int = 0, tool: int = 0, worker: int = 0, usd: float = 0.0) -> None:
        lim = scope.limits
        if lim.max_llm_calls is not None and scope.llm_calls + llm > lim.max_llm_calls:
            raise BudgetExceeded(scope.name, "llm_calls")
        if lim.max_tool_calls is not None and scope.tool_calls + tool > lim.max_tool_calls:
            raise BudgetExceeded(scope.name, "tool_calls")
        if lim.max_worker_calls is not None and scope.worker_calls + worker > lim.max_worker_calls:
            raise BudgetExceeded(scope.name, "worker_calls")
        if lim.max_cost_usd is not None and scope.cost_usd + scope.reserved_usd + usd > lim.max_cost_usd:
            raise BudgetExceeded(scope.name, "cost_usd")
        if lim.max_wall_s is not None and scope.wall_s() > lim.max_wall_s:
            raise BudgetExceeded(scope.name, "wall_s")

    def before_llm(self, reserve_usd: float) -> float | None:
        """Check every active scope, then count the call and reserve its worst-case cost. Returns the smallest
        remaining wall time (seconds) for the request timeout, or None if unlimited."""
        with self._lock:
            for s in self.scopes:
                self._check(s, llm=1, usd=reserve_usd)
            for s in self.scopes:
                s.llm_calls += 1
                s.reserved_usd += reserve_usd
            rem = [r for s in self.scopes if (r := s.remaining_wall_s()) is not None]
        return min(rem) if rem else None

    def settle_llm(self, reserve_usd: float, cost_usd: float, unknown: bool = False) -> None:
        with self._lock:
            for s in self.scopes:
                s.reserved_usd = max(0.0, s.reserved_usd - reserve_usd)
                s.cost_usd += cost_usd
                s.llm_usd += cost_usd
                s.unknown_cost_calls += int(unknown)

    def before_tool(self) -> None:
        with self._lock:
            for s in self.scopes:
                self._check(s, tool=1, usd=MAX_TOOL_CALL_USD)
            for s in self.scopes:
                s.tool_calls += 1

    def settle_tool(self, billed_usd: float, cold_usd: float) -> None:
        with self._lock:
            for s in self.scopes:
                s.cost_usd += billed_usd
                s.tool_usd += billed_usd
                s.tool_usd_cold += cold_usd

    def before_worker_call(self) -> None:
        with self._lock:
            for s in self.scopes:
                self._check(s, worker=1)
            for s in self.scopes:
                s.worker_calls += 1

    # -- records -----------------------------------------------------------------------------
    def next_id(self) -> int:
        with self._lock:
            self._ids += 1
            return self._ids

    def _append(self, name: str, rec: dict) -> None:
        if self.run_dir is None:
            return
        with self._lock, open(self.run_dir / name, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def message_hashes(self, messages: list[dict]) -> list[str]:
        out = []
        for m in messages:
            s = json.dumps(m, sort_keys=True, ensure_ascii=False, default=str)
            h = hashlib.sha256(s.encode()).hexdigest()[:20]
            with self._lock:
                new = h not in self._seen
                self._seen.add(h)
            if new:
                self._append("messages.jsonl", {"h": h, "m": m})
            out.append(h)
        return out

    def llm(self, rec: dict) -> None:
        rec = {"ts": time.time(), **self.current_tags(), **rec}
        if rec.get("status") in ("ok", "error") and rec.get("usage"):
            u = rec["usage"]
            with self._lock:
                b = self.usage.setdefault(rec.get("stage", "?"), {})
                b["llm_calls"] = b.get("llm_calls", 0) + 1
                for k in ("prompt_tokens", "completion_tokens"):
                    b[k] = b.get(k, 0) + (u.get(k) or 0)
                b["reasoning_tokens"] = b.get("reasoning_tokens", 0) + reasoning_tokens(u)
                if rec.get("effort") not in (None, "none"):
                    b["reasoning_calls"] = b.get("reasoning_calls", 0) + 1  # calls that asked for reasoning
                b["cost_usd"] = b.get("cost_usd", 0.0) + float(u.get("cost") or 0.0)
        self._append("llm_calls.jsonl", rec)

    def tool(self, rec: dict) -> None:
        rec = {"ts": time.time(), **self.current_tags(), **rec}
        if rec.get("status") not in (None, "started"):
            billed = credits_usd(rec.get("credits"))
            # cold-cache equivalent: a cache hit from a billing backend would have cost one credit when fetched
            cold = billed or (TOOL_USD_PER_CREDIT.get(rec.get("backend"), 0.0) if rec.get("cache_hit") else 0.0)
            if billed or cold:
                rec["tool_usd"], rec["tool_usd_cold"] = billed, cold
                self.settle_tool(billed, cold)
            with self._lock:
                b = self.usage.setdefault(rec.get("stage", "?"), {})
                b["tool_calls"] = b.get("tool_calls", 0) + 1
                for k, v in (rec.get("credits") or {}).items():
                    b[f"credits_{k}"] = b.get(f"credits_{k}", 0) + v
                if billed or cold:
                    b["tool_usd"] = b.get("tool_usd", 0.0) + billed
                    b["tool_usd_cold"] = b.get("tool_usd_cold", 0.0) + cold
        self._append("tool_calls.jsonl", rec)

    def event(self, kind: str, **data: Any) -> None:
        self._append("events.jsonl", {"ts": time.time(), "event": kind, **self.current_tags(), **data})

    # -- checkpoint support ------------------------------------------------------------------
    def state_dict(self) -> dict:
        s = self.run_scope
        return {"counters": s.counters(), "limits": asdict(s.limits), "usage": self.usage}

    def load_state_dict(self, state: dict) -> None:
        """A restored run starts with the checkpoint's prefix already spent (calls, cost, wall time)."""
        c = state["counters"]
        s = self.run_scope
        s.llm_calls, s.tool_calls, s.worker_calls = c["llm_calls"], c["tool_calls"], c.get("worker_calls", 0)
        s.cost_usd, s.wall_offset_s = c["cost_usd"], c["wall_s"]
        # checkpoints before cost accounting c1 have only cost_usd (= LLM cost then)
        s.llm_usd = c.get("llm_usd", c["cost_usd"])
        s.tool_usd, s.tool_usd_cold = c.get("tool_usd", 0.0), c.get("tool_usd_cold", 0.0)
        s.unknown_cost_calls = c.get("unknown_cost_calls", 0)
        self.usage = {k: dict(v) for k, v in state.get("usage", {}).items()}
