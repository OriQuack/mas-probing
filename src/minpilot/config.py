"""Configuration: worker pool, refiner (the condition) and run settings. Loaded from YAML under configs/.

Vocabulary
- **worker**: a registered (model key, system prompt, tools) setting. Workers are stateless between calls.
- **role**: what the orchestrator sees and delegates to (id, description, tools). A role maps to one fixed
  `executor` worker and to its `probe_workers` (who answers probes for this role).
  - role routing: each role's probe_workers is [its executor] (repeated/varied probes of the same worker);
  - redundant candidates: one role whose probe_workers are several workers (different models) that could all do
    the subtask; the executor stays fixed, so instruction effects are not mixed with worker selection.
- **refiner**: the `InstructionRefiner` and its settings: the experimental condition (A none, B self-review,
  C probe).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from minpilot.runtime.trace import Limits
from minpilot.tools.toolbox import TOOL_NAMES

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"
PROBE_QUESTIONS = ("understanding", "assumptions", "failure", "plan")


@dataclass(frozen=True)
class WorkerSpec:
    id: str
    model: str
    tools: tuple[str, ...]
    system_prompt: str            # the worker's own instructions; the harness appends the shared report rules
    max_tool_calls: int = 20

    def __post_init__(self):
        bad = [t for t in self.tools if t not in TOOL_NAMES]
        if bad:
            raise ValueError(f"worker {self.id}: unknown tools {bad}; known: {TOOL_NAMES}")


@dataclass(frozen=True)
class RoleSpec:
    id: str
    description: str
    executor: str
    probe_workers: tuple[str, ...]


@dataclass(frozen=True)
class PoolConfig:
    name: str
    workers: dict[str, WorkerSpec]
    roles: dict[str, RoleSpec]

    def __post_init__(self):
        for r in self.roles.values():
            for w in (r.executor, *r.probe_workers):
                if w not in self.workers:
                    raise ValueError(f"role {r.id}: unknown worker {w!r}")

    def role_tools(self, role_id: str) -> tuple[str, ...]:
        return self.workers[self.roles[role_id].executor].tools

    def to_dict(self) -> dict:
        return {"name": self.name, "workers": {k: asdict(v) for k, v in self.workers.items()},
                "roles": {k: asdict(v) for k, v in self.roles.items()}}


@dataclass(frozen=True)
class RefinerConfig:
    name: str
    kind: str = "none"                       # none | self_review | probe
    # Probing (C) and simulated probing (B): which questions, how many answers per probe worker.
    questions: tuple[str, ...] = PROBE_QUESTIONS
    samples_per_worker: int = 1              # repeated probes of the same worker (role routing: >1 for variation)
    probe_tools: bool = False                # may probe workers use tools (on a scratch copy) while answering
    probe_max_tool_calls: int = 6
    max_followups: int = 0                   # C variants only: follow-up questions in total (each continues one
                                             # probe conversation); 0 in the main B/C contrast
    max_verifications: int = 2               # B and C: verification calls delegated to workers (with tools)
    verify_max_tool_calls: int = 10
    connect_probe_to_execution: bool = False # continue the executor's probe conversation into execution
    rewrite: bool = True                     # False: collect answers only, execute the draft unchanged (with
                                             # connect_probe_to_execution: the information-without-rewrite arm)
    budget: Limits = field(default_factory=lambda: Limits(max_llm_calls=60, max_cost_usd=1.0, max_worker_calls=8))

    def __post_init__(self):
        if self.kind not in ("none", "self_review", "probe"):
            raise ValueError(f"unknown refiner kind {self.kind!r}")
        bad = [q for q in self.questions if q not in PROBE_QUESTIONS]
        if bad:
            raise ValueError(f"unknown probe questions {bad}; known: {PROBE_QUESTIONS}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RunConfig:
    pool: PoolConfig
    refiner: RefinerConfig
    orchestrator_model: str = "luna-high"
    refiner_model: str = "luna-high"         # the refiner speaks for the orchestrator (same model by default)
    refine_at: str = "first"                 # first | all | none: which delegations go through the refiner
    max_delegations: int = 12
    show_final_instruction: bool = True      # the orchestrator's history shows the instruction actually sent
    budget: Limits = field(default_factory=lambda: Limits(max_llm_calls=400, max_tool_calls=400,
                                                          max_cost_usd=5.0, max_wall_s=3 * 3600))
    checkpoint: bool = True                  # save a checkpoint at every delegation point
    label: str = ""

    def __post_init__(self):
        if self.refine_at not in ("first", "all", "none"):
            raise ValueError(f"refine_at must be first|all|none, not {self.refine_at!r}")

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k not in ("pool", "refiner")}
        d["pool"] = self.pool.to_dict()
        d["refiner"] = self.refiner.to_dict()
        return d


# -- loading -----------------------------------------------------------------------------------
def _resolve(path_or_name: str | Path, sub: str) -> Path:
    p = Path(path_or_name)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return p
    return CONFIG_DIR / sub / f"{path_or_name}.yaml"


def load_pool(path_or_name: str | Path) -> PoolConfig:
    d = yaml.safe_load(_resolve(path_or_name, "pools").read_text())
    workers = {w["id"]: WorkerSpec(id=w["id"], model=w["model"], tools=tuple(w["tools"]),
                                   system_prompt=w["system_prompt"].strip(),
                                   max_tool_calls=int(w.get("max_tool_calls", 20))) for w in d["workers"]}
    roles = {r["id"]: RoleSpec(id=r["id"], description=" ".join(r["description"].split()), executor=r["executor"],
                               probe_workers=tuple(r.get("probe_workers") or [r["executor"]])) for r in d["roles"]}
    return PoolConfig(name=d["name"], workers=workers, roles=roles)


def load_refiner(path_or_name: str | Path) -> RefinerConfig:
    d = yaml.safe_load(_resolve(path_or_name, "refiners").read_text())
    if "questions" in d:
        d["questions"] = tuple(d["questions"])
    if "budget" in d:
        d["budget"] = Limits.from_dict(d["budget"])
    return RefinerConfig(**d)


def refiner_from_dict(d: dict) -> RefinerConfig:
    d = dict(d)
    d["questions"] = tuple(d.get("questions", PROBE_QUESTIONS))
    d["budget"] = Limits.from_dict(d.get("budget"))
    return RefinerConfig(**d)


def pool_from_dict(d: dict) -> PoolConfig:
    workers = {k: WorkerSpec(**{**v, "tools": tuple(v["tools"])}) for k, v in d["workers"].items()}
    roles = {k: RoleSpec(**{**v, "probe_workers": tuple(v["probe_workers"])}) for k, v in d["roles"].items()}
    return PoolConfig(name=d["name"], workers=workers, roles=roles)


def run_config_from_dict(d: dict) -> RunConfig:
    d = dict(d)
    d["pool"] = pool_from_dict(d["pool"])
    d["refiner"] = refiner_from_dict(d["refiner"])
    d["budget"] = Limits.from_dict(d.get("budget"))
    return RunConfig(**d)
