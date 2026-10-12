"""Current runtime configuration. Historical presets require their code snapshots."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from minpilot.prompts import REFINER_PROMPTS_VERSION
from minpilot.runtime.trace import Limits
from minpilot.tools.toolbox import TOOL_NAMES

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"
CONDITIONS = ("direct_execution", "multi_worker_probe")


@dataclass(frozen=True)
class WorkerSpec:
    id: str
    model: str
    tools: tuple[str, ...]
    system_prompt: str
    max_tool_calls: int = 20

    def __post_init__(self):
        if bad := [t for t in self.tools if t not in TOOL_NAMES]:
            raise ValueError(f"worker {self.id}: unknown tools {bad}")
        if not self.id or self.max_tool_calls < 0:
            raise ValueError("invalid worker id/tool limit")


@dataclass(frozen=True)
class PoolConfig:
    name: str
    workers: dict[str, WorkerSpec]

    def __post_init__(self):
        if not self.workers or any(k != w.id for k, w in self.workers.items()):
            raise ValueError("pool requires registered workers with matching keys")

    def to_dict(self):
        return {"name": self.name, "workers": {k: asdict(v) for k, v in self.workers.items()}}


@dataclass(frozen=True)
class ConditionConfig:
    name: str = "direct_execution"
    prompts: str = REFINER_PROMPTS_VERSION
    budget: Limits = field(default_factory=lambda: Limits(max_llm_calls=60, max_cost_usd=1.0))

    def __post_init__(self):
        if self.name not in CONDITIONS or self.prompts != REFINER_PROMPTS_VERSION:
            raise ValueError("unsupported condition/prompt version; use historical code snapshot")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class RunConfig:
    pool: PoolConfig
    condition: ConditionConfig = field(default_factory=ConditionConfig)
    orchestrator_model: str = "luna-high"
    evaluator_model: str = "luna-high"
    refiner_model: str = "luna-high"
    max_delegations: int = 12
    budget: Limits = field(default_factory=lambda: Limits(max_llm_calls=400, max_tool_calls=400,
                                                          max_cost_usd=5.0, max_wall_s=3 * 3600))
    checkpoint: bool = True
    label: str = ""

    def __post_init__(self):
        if {self.orchestrator_model, self.evaluator_model, self.refiner_model} != {"luna-high"}:
            raise ValueError("orchestrator, evaluator and refiner must use luna-high")
        if self.max_delegations < 0:
            raise ValueError("max_delegations must be nonnegative")

    def to_dict(self):
        return {**asdict(self), "pool": self.pool.to_dict(), "condition": self.condition.to_dict()}


def _resolve(value, sub):
    path = Path(value)
    return path if path.suffix in (".yaml", ".yml") and path.exists() else CONFIG_DIR / sub / f"{value}.yaml"


def load_pool(value):
    data = yaml.safe_load(_resolve(value, "pools").read_text())
    if "roles" in data:
        raise ValueError("fixed role/executor pools are retired; use historical snapshot or a worker-only pool")
    workers = {w["id"]: WorkerSpec(**{**w, "tools": tuple(w["tools"]),
                                   "system_prompt": w["system_prompt"].strip()}) for w in data["workers"]}
    if len(workers) != len(data["workers"]):
        raise ValueError("duplicate worker IDs")
    return PoolConfig(data["name"], workers)


def load_condition(value):
    data = yaml.safe_load(_resolve(value, "conditions").read_text())
    if "budget" in data:
        data["budget"] = Limits.from_dict(data["budget"])
    return ConditionConfig(**data)


def pool_from_dict(data):
    if "roles" in data:
        raise ValueError("historical pool requires its code snapshot")
    return PoolConfig(data["name"], {k: WorkerSpec(**{**w, "tools": tuple(w["tools"])})
                                    for k, w in data["workers"].items()})


def run_config_from_dict(data):
    data = dict(data)
    data["pool"] = pool_from_dict(data["pool"])
    cond = dict(data["condition"])
    cond["budget"] = Limits.from_dict(cond.get("budget"))
    data["condition"] = ConditionConfig(**cond)
    data["budget"] = Limits.from_dict(data.get("budget"))
    return RunConfig(**data)


def load_refiner(*args, **kwargs):
    raise ValueError("refiner presets are retired; select --condition direct_execution or multi_worker_probe")
