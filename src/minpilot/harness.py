"""Sequential shared-state runtime: direct execution or independent pool probes."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

from minpilot import prompts
from minpilot.controller import DecisionError, decide
from minpilot.memory import Memory
from minpilot.prompts.orchestrator import ORCHESTRATOR
from minpilot.prompts.evaluator import EVALUATOR, EVALUATOR_VERSION
from minpilot.prompts.refiner import REFINER
from minpilot.agents.worker import Worker, WorkerCall
from minpilot.config import RunConfig, run_config_from_dict
from minpilot.data.gaia import ANSWER_FORMAT, GaiaTask
from minpilot.llm.client import LLMClient
from minpilot.llm.specs import get_spec
from minpilot.runtime.costs import COSTS_VERSION, TOOL_USD_PER_CREDIT
from minpilot.runtime.trace import BudgetExceeded, InfraError, Trace
from minpilot.tools.config import REPO_ROOT, ToolConfig
from minpilot.tools.crawl4ai_service import same_identity
from minpilot.tools.reader import PageReader
from minpilot.tools.toolbox import Toolbox
from minpilot.tools.web import WebTools

STATE_FORMAT = 4
RUNS_ROOT = REPO_ROOT / "outputs" / "runs"


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=10)
        dirty = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True,
                               text=True, timeout=10).stdout.strip()
        return (out.stdout.strip() + ("+dirty" if dirty else "")) if out.returncode == 0 else None
    except Exception:
        return None


def new_run_dir(task_id: str, label: str, runs_root: Path | str = RUNS_ROOT) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    d = Path(runs_root) / task_id / f"{stamp}_{label or 'run'}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def dir_digest(root: Path) -> dict[str, str]:
    """Content hash of every file, and the target of every symlink (review 2026-10-09: links were skipped)."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_symlink():
            out[str(p.relative_to(root))] = "symlink->" + os.readlink(p)
        elif p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def escaping_symlinks(root: Path) -> list[str]:
    """Symlinks under root whose target resolves outside root (not restored: the workspace must be closed)."""
    root = Path(root).resolve()
    bad = []
    for p in Path(root).rglob("*"):
        if p.is_symlink():
            target = (p.parent / os.readlink(p)).resolve()
            if root not in (target, *target.parents):
                bad.append(str(p.relative_to(root)))
    return bad


# ToolConfig fields that do not change what a tool returns: where the cache file and the reader service live,
# how many reader parts run at once, and the blocklist version (checked separately: a newer blocklist may continue an older checkpoint, T8).
TOOL_IDENTITY_EXCLUDE = ("cache_path", "crawl4ai_endpoint", "blocklist_version", "reader_max_parallel")


def tool_identity(tools: dict) -> dict:
    return json.loads(json.dumps({k: v for k, v in tools.items() if k not in TOOL_IDENTITY_EXCLUDE}, default=str))


def code_hash() -> str:
    """Hash of the package source (src/minpilot/**/*.py, prompts included), recorded with runs and checkpoints."""
    h = hashlib.sha256()
    pkg = Path(__file__).resolve().parent
    for p in sorted(pkg.rglob("*.py")):
        h.update(str(p.relative_to(pkg)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def _version_num(v: str) -> int:
    return int("".join(c for c in str(v) if c.isdigit()) or 0)


# Effort-high calls with tools rely on undocumented OpenRouter behaviour (llm/specs.py, decision M4): a stage whose
# reasoning calls all report zero reasoning tokens is flagged (single calls may legitimately use none).
MIN_CALLS_FOR_REASONING_WARNING = 3


def reasoning_warnings(usage: dict) -> list[str]:
    return [f"no reasoning tokens in stage {stage!r} ({b['reasoning_calls']} effort>none calls)"
            for stage, b in sorted(usage.items())
            if b.get("reasoning_calls", 0) >= MIN_CALLS_FOR_REASONING_WARNING and not b.get("reasoning_tokens")]


def original_task_of(task: GaiaTask, reference_date: str | None = None) -> str:
    return prompts.original_task_text(task.question, f"attachments/{task.file_name}" if task.file_name else None,
                                      reference_date)


class Run:
    def __init__(self, cfg: RunConfig, task: GaiaTask, run_dir: Path | str, *, transport=None,
                 web=None, tool_cfg=None, reader_identity=None):
        self.cfg, self.task = cfg, task
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = self.run_dir / "work"
        self.tool_cfg = tool_cfg or ToolConfig()
        self.reader_identity = reader_identity
        self.trace = Trace(self.run_dir, cfg.budget)
        self.memory = Memory(self.run_dir / "artifacts", self.trace)
        self.reference_date = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
        self.original_task = original_task_of(task, self.reference_date)
        self.transport, self.clients = transport, {}
        self.web = web or WebTools(self.tool_cfg, question=task.question)
        if self.web.reader is None:
            self.web.reader = PageReader(self.client(self.tool_cfg.reader_model), self.tool_cfg)
        self.toolbox = None
        self.workers = {wid: Worker(spec, self.client(spec.model)) for wid, spec in cfg.pool.workers.items()}
        self.delegations, self.latest_evaluation = [], None
        self.actions, self.latest_probe = [], None
        self.info = {}

    def client(self, key):
        if key not in self.clients:
            self.clients[key] = LLMClient(get_spec(key), self.trace, transport=self.transport)
        return self.clients[key]

    def worker_list(self):
        return [{"id": w.id, "model": w.model, "tools": list(w.tools), "system_prompt": w.system_prompt,
                 "input_formats": ["text", "image"], "max_tool_calls": w.max_tool_calls, "context_window": get_spec(w.model).context_window,
                 "max_tokens": get_spec(w.model).max_tokens,
                 "price_prompt": get_spec(w.model).price_prompt,
                 "price_completion": get_spec(w.model).price_completion}
                for w in self.cfg.pool.workers.values()]

    def model_identities(self):
        keys = {self.cfg.orchestrator_model, self.cfg.evaluator_model, self.cfg.refiner_model,
                self.tool_cfg.reader_model, *(w.model for w in self.cfg.pool.workers.values())}
        return {k: get_spec(k).identity() for k in sorted(keys)}

    def _write_run_json(self, **extra):
        self.info.update(extra)
        (self.run_dir / "run.json").write_text(json.dumps(self.info, ensure_ascii=False, indent=2, default=str))

    def _base_info(self, mode):
        return {"task_id": self.task.task_id, "level": self.task.level, "mode": mode, "label": self.cfg.label,
                "condition": self.cfg.condition.name, "status": "running", "final_answer": None,
                "started_at": time.time(), "git_commit": git_commit(), "code_hash": code_hash(),
                "prompts_version": prompts.PROMPTS_VERSION, "refiner_prompts_version": prompts.REFINER_PROMPTS_VERSION,
                "evaluator_prompts_version": EVALUATOR_VERSION, "config": self.cfg.to_dict(),
                "models": self.model_identities(), "tools": self.tool_cfg.to_dict(),
                "costs": {"version": COSTS_VERSION, "tool_usd_per_credit": TOOL_USD_PER_CREDIT},
                "reader_identity": self.reader_identity, "reference_date": self.reference_date}

    def run_fresh(self):
        self._write_run_json(**self._base_info("fresh"))
        att = self.work_dir / "attachments"
        att.mkdir(parents=True, exist_ok=True)
        if self.task.file_path:
            shutil.copy2(self.task.file_path, att / self.task.file_name)
        self.toolbox = Toolbox(self.work_dir, self.web, self.trace, question=self.task.question)
        return self._guarded(lambda: self._loop(None))

    def _payload(self, **extra):
        # Keep the complete probe record in traces/checkpoints; these fields are already top-level inputs.
        latest_probe = ({k: v for k, v in self.latest_probe.items() if k not in ("instructions", "evaluation")}
                        if self.latest_probe is not None else None)
        return {"available_actions": self.available_actions(), "first_action": not self.actions,
                "instructions": self._instructions(), "latest_probe": latest_probe, "original_task": self.original_task, "state": self.memory.state,
                "artifacts": self.memory.catalog(), "workers": self.worker_list(),
                "condition": self.cfg.condition.name, "evaluation": self.latest_evaluation,
                "remaining_delegations": self.cfg.max_delegations - len(self.delegations),
                "budget": self.trace.state_dict(),
                "active_budgets": [{"scope": s.name, "limits": s.limits.__dict__, "spent": s.counters()}
                                   for s in self.trace.scopes], "paid_search": self.web.state_dict().get("paid_search"),
                "answer_format": ANSWER_FORMAT, **extra}

    def available_actions(self):
        return (["probe"] if self.cfg.condition.name == "adaptive_probe" else []) + ["execute", "finish", "read_memory"]

    def _validate_selection(self, data, *, must_finish=False):
        action = data.get("action")
        if "refine" in data or "changes" in data:
            raise ValueError("retired orchestrator fields refine/changes")
        if not isinstance(data.get("rationale"), str) or not data["rationale"].strip():
            raise ValueError("rationale is required")
        if action == "finish":
            if not isinstance(data.get("answer"), str) or not data["answer"].strip():
                raise ValueError("finish requires answer")
            return
        if must_finish or action not in self.available_actions() or action not in ("probe", "execute"):
            raise ValueError("return finish" if must_finish else "invalid decision action")
        instruction_id = data.get("instruction_id")
        if instruction_id is not None:
            if action != "execute" or data.get("instruction") is not None:
                raise ValueError("instruction_id requires execute and no new instruction")
            saved_instruction = self._instruction(instruction_id)
            if "delivered_instruction" in data and data["delivered_instruction"] != saved_instruction:
                raise ValueError("saved instruction mismatch")
        elif not isinstance(data.get("instruction"), str) or not data["instruction"].strip():
            raise ValueError("instruction required")
        self.memory.context(data.get("artifact_ids"), data.get("state_rows"))
        if action == "probe":
            if data.get("worker_id") is not None:
                raise ValueError("probe worker_id must be null")
            return
        if data.get("worker_id") not in self.workers:
            raise ValueError("select a registered worker_id")

    def _instruction(self, ref):
        record = self.memory.read(ref)
        if record["stage"] == "instruction.draft":
            return record["body"]
        if record["stage"] == "instruction.refined" and record["status"] == "ok":
            result = json.loads(record["body"])
            if result["can_refine"]:
                return result["instruction"]
        raise ValueError("not an executable instruction ID")

    def _instructions(self):
        result = []
        for record in self.memory.artifacts:
            if record["stage"] not in ("instruction.draft", "instruction.refined"):
                continue
            try:
                instruction = self._instruction(record["id"])
            except ValueError:
                continue
            notes = json.loads(record["body"])["context_notes"] if record["stage"] == "instruction.refined" else ""
            result.append({"instruction_id": record["id"], "instruction": instruction, "context_notes": notes})
        return result

    def _orchestrate(self, *, must_finish=False):
        payload = self._payload(must_finish=must_finish)
        data = decide(self.client(self.cfg.orchestrator_model), self.trace, self.memory,
                      stage="orchestrator", system=ORCHESTRATOR, payload=payload,
                      validate=lambda d: self._validate_selection(d, must_finish=must_finish))
        context = self.memory.context(data.get("artifact_ids") or [], data.get("state_rows") or [])
        self.trace.event("context_selection", snapshot=self.memory.state, artifact_ids=data.get("artifact_ids") or [],
                         state_rows=data.get("state_rows") or [], context=context, action=data["action"])
        data["context_snapshot"] = json.loads(json.dumps(self.memory.state))
        self.latest_probe = None
        data["context"] = context
        if data["action"] in ("probe", "execute"):
            ref = data.get("instruction_id")
            if ref is None:
                record = self.memory.add("orchestrator", "instruction.draft", data["instruction"], title="Assignment draft")
                ref = record["id"]
            data["selected_instruction_id"] = ref
            data["delivered_instruction"] = self._instruction(ref)
        return data

    def _evaluate(self, stage, instruction, context, reports):
        payload = self._payload(request=f"evaluate_{stage}", instruction=instruction, context=context, reports=[{k: v for k, v in r.items() if k != "tool_records"} for r in reports])

        def validate(data):
            if data.get("action") != "evaluate":
                raise ValueError("expected evaluate")
            self.memory.validate_state(data.get("state"))
            for field in ("title", "rationale", "changes"):
                if not isinstance(data.get(field), str):
                    raise ValueError(f"missing {field}")
        try:
            assessment, raw_response = decide(self.client(self.cfg.evaluator_model), self.trace, self.memory,
                              stage=f"evaluator.{stage}", system=EVALUATOR, payload=payload, validate=validate, with_raw=True)
            artifact = self.memory.add("evaluator", f"evaluation.{stage}", raw_response, title=assessment["title"])
            self.memory.replace(assessment["state"], evaluation=artifact["id"], reason=assessment["rationale"])
            self.latest_evaluation = {"artifact_id": artifact["id"],
                                      "rationale": assessment["rationale"], "changes": assessment["changes"]}
        except BudgetExceeded as error:
            for raw in getattr(error, "responses", []):
                self.memory.add("evaluator", f"evaluation.{stage}", raw, status="failed")
            raise
        except (DecisionError, InfraError) as error:
            for original in getattr(error, "responses", []) or [str(error)]:
                artifact = self.memory.add("evaluator", f"evaluation.{stage}", original, status="failed")
            self.latest_evaluation = {"artifact_id": artifact["id"], "error": str(error),
                                      "new_report_ids": [r["id"] for r in reports]}

    def _loop(self, pending):
        while True:
            k = len(self.delegations)
            with self.trace.tags(delegation=k, action_index=len(self.actions)):
                if pending is None:
                    action = self._orchestrate(must_finish=k >= self.cfg.max_delegations)
                    self.trace.event("action", **action)
                    if action["action"] == "finish":
                        self.info.update(final_rationale=action["rationale"], forced_finish=k >= self.cfg.max_delegations)
                        return action["answer"], "ok"
                    if self.cfg.checkpoint:
                        self.save_checkpoint(action, len(self.actions))
                else:
                    action, pending = pending, None
                index = len(self.actions)
                self.actions.append({**action, "index": index})
                with self.trace.tags(action_index=index):
                    if action["action"] == "probe":
                        self._probe_round(action, index)
                    else:
                        self._delegate(action, k)

    def _probe(self, worker_id, instruction, context, k):
        scratch = self.run_dir / "scratch" / f"a{k}" / worker_id
        shutil.copytree(self.work_dir, scratch, symlinks=True)
        toolbox = Toolbox(scratch, self.web.fork(), self.trace, question=self.task.question)
        toolbox.load_state_dict(self.toolbox.state_dict())
        with self.trace.tags(stage="probe", worker=worker_id):
            self.workers[worker_id].last_messages = []
            try:
                self.trace.before_worker_call()
                call = self.workers[worker_id].run(self.original_task,
                        prompts.probe_instruction(instruction, True, 3), toolbox, max_tool_calls=3,
                        context=context, kind="probe")
            except BudgetExceeded as error:
                self.memory.add(worker_id, "probe", str(error), status="budget_exceeded",
                                messages=self.workers[worker_id].last_messages)
                raise
            except Exception as error:
                call = WorkerCall(str(error), getattr(self.workers[worker_id], "last_messages", []), "failed")
        return self.memory.add(worker_id, "probe", call.report, status=call.status, messages=call.messages)

    def _probe_round(self, action, index):
        reports = []
        prior_ids = {r["id"] for r in self.memory.artifacts}
        try:
            with self.trace.budget_scope("probe_round", self.cfg.condition.budget):
                for wid in self.workers:
                    reports.append(self._probe(wid, action["instruction"], action["context"], index))
                self._evaluate("probe", action["instruction"], action["context"], reports)
        except BudgetExceeded as error:
            if error.scope == "run":
                raise
            self.trace.event("probe_budget_exceeded", what=error.what)
            self.latest_evaluation = {"error": str(error), "new_report_ids": [r["id"] for r in reports]}
        self.latest_probe = {"instruction": action["instruction"], "context": action["context"],
                             "reports": [{k: v for k, v in r.items() if k != "tool_records"} for r in
                                         self.memory.artifacts if r["stage"] == "probe" and r["id"] not in prior_ids]}
        draft_id = action["selected_instruction_id"]
        refinement = {"status": "evaluation_failed", "instruction_id": draft_id}
        if "error" not in self.latest_evaluation:
            try:
                with self.trace.budget_scope("refinement", self.cfg.condition.budget):
                    refinement = self._refine(action, action["context"])
            except BudgetExceeded as error:
                if error.scope == "run":
                    raise
                refinement = {"status": "refinement_budget_exceeded", "instruction_id": draft_id}
                self.trace.event("refinement_budget_exceeded", what=error.what)
        self.latest_probe.update(draft_instruction_id=draft_id, refinement=refinement,
                                 instructions=self._instructions(), evaluation=self.latest_evaluation)
        self.actions[-1].update(report_ids=[r["id"] for r in self.latest_probe["reports"]],
                                refinement=refinement, evaluation=self.latest_evaluation)
        self.trace.event("probe_refinement", **self.latest_probe)

    def _delegate(self, action, k):
        selected = action
        instruction = self._instruction(action["selected_instruction_id"])
        origin = next((a for a in self.actions if a["action"] == "probe" and
                       action["selected_instruction_id"] in (a.get("selected_instruction_id"),
                       a.get("refinement", {}).get("instruction_id"))), None)
        draft = origin["instruction"] if origin else instruction
        context = action["context"]
        pre_status = origin.get("refinement", {}).get("status", "not_needed") if origin else "not_needed"
        wid = selected["worker_id"]
        self.trace.event("delegation", delegation=k, worker=wid, draft=draft, final=instruction,
                         instruction_id=action["selected_instruction_id"], draft_instruction_id=origin["selected_instruction_id"] if origin else action["selected_instruction_id"], context=context, selection_reason=selected["rationale"], refine_status=pre_status, changed=instruction != draft)
        with self.trace.tags(stage="execution", worker=wid):
            self.workers[wid].last_messages = []
            try:
                call = self.run_worker(wid, self.original_task, instruction, context=context)
            except (BudgetExceeded, InfraError) as error:
                self.memory.add(wid, "execution", str(error), status="failed",
                                messages=self.workers[wid].last_messages)
                raise
            except Exception as error:
                call = WorkerCall(str(error), getattr(self.workers[wid], "last_messages", []), "failed")
        report = self.memory.add(wid, "execution", call.report, status=call.status, messages=call.messages)
        self.trace.event("report", worker=wid, artifact_id=report["id"], status=call.status,
                         n_tool_calls=call.n_tool_calls, report=call.report)
        self._evaluate("execution", instruction, context, [report])
        repeat_of = next((d["index"] for d in self.delegations if " ".join(d["draft"].split()) == " ".join(draft.split())), None)
        self.delegations.append({"changed": instruction != draft, "draft_chars": len(draft),
                                 "final_chars": len(instruction), "repeat_of": repeat_of, "index": k,
                                 "instruction_id": action["selected_instruction_id"], "action_index": len(self.actions) - 1, "worker": wid, "draft": draft, "final": instruction,
                                 "context": context, "artifact_ids": selected.get("artifact_ids", []),
                                 "state_rows": selected.get("state_rows", []), "report_id": report["id"],
                                 "evaluation_id": self.latest_evaluation["artifact_id"],
                                 "selection_reason": selected["rationale"], "refine_status": pre_status,
                                 "report_status": call.status, "n_tool_calls": call.n_tool_calls})

    def _refine(self, selected, context):
        def validate(data):
            if data.get("action") != "refine" or type(data.get("can_refine")) is not bool:
                raise ValueError("expected refine and can_refine boolean")
            for key in ("instruction", "context_notes", "rationale"):
                if not isinstance(data.get(key), str):
                    raise ValueError(f"missing {key}")
            if data["can_refine"] and not data["instruction"].strip():
                raise ValueError("empty refined instruction")
        draft_id = selected["selected_instruction_id"]
        try:
            result, raw = decide(self.client(self.cfg.refiner_model), self.trace, self.memory, stage="refiner",
                            system=REFINER, payload={"original_task": self.original_task,
                            "draft": selected["instruction"], "draft_instruction_id": draft_id,
                            "context": context, "state": self.memory.state,
                            "evaluation": self.latest_evaluation, "workers": self.worker_list(),
                            "artifacts": self.memory.catalog()}, validate=validate, with_raw=True)
            artifact = self.memory.add("refiner", "instruction.refined", raw, title="Refiner response")
            return {"status": "rewritten" if result["can_refine"] else "refiner_unapplied",
                    "instruction_id": artifact["id"] if result["can_refine"] else draft_id,
                    "artifact_id": artifact["id"], "result": result, "draft_instruction_id": draft_id}
        except BudgetExceeded as error:
            for raw in getattr(error, "responses", []):
                self.memory.add("refiner", "instruction.refined", raw, status="failed")
            raise
        except (DecisionError, InfraError) as error:
            ids = [self.memory.add("refiner", "instruction.refined", raw, status="failed")["id"]
                   for raw in getattr(error, "responses", []) or [str(error)]]
            return {"status": "refiner_failed", "instruction_id": draft_id, "failure_ids": ids}

    def run_worker(self, worker_id, original_task, instruction, *, context=""):
        self.trace.before_worker_call()
        return self.workers[worker_id].run(original_task, instruction, self.toolbox, context=context)

    def call_worker(self, worker_id, original_task, instruction, context=""):
        return self.run_worker(worker_id, original_task, instruction, context=context).report

    def _guarded(self, fn):
        try:
            answer, status = fn()
            return self._finish(status, final_answer=answer)
        except BudgetExceeded as error:
            return self._finish("budget_exceeded", error=str(error))
        except InfraError as error:
            return self._finish("error_infra", error=str(error))
        except Exception as error:
            return self._finish("error", error=repr(error), tb=traceback.format_exc())

    def _finish(self, status, **extra):
        self.trace.event("run_end", status=status)
        self._write_run_json(status=status, ended_at=time.time(), n_delegations=len(self.delegations), actions=self.actions,
                             n_probes=sum(a["action"] == "probe" for a in self.actions),
                             n_repeated_delegations=sum(d["repeat_of"] is not None for d in self.delegations),
                             delegations=self.delegations, usage=self.trace.usage,
                             counters=self.trace.run_scope.counters(), state=self.memory.state,
                             artifacts=self.memory.catalog(), paid_search=self.web.state_dict().get("paid_search"),
                             warnings=reasoning_warnings(self.trace.usage), **extra)
        return self.info

    def fingerprint(self, action, k):
        budget = self.trace.state_dict()
        budget["counters"] = {k: v for k, v in budget["counters"].items() if k != "wall_s"}
        return {"budget": _sha(budget), "pending_action": _sha(action), "memory": _sha(self.memory.dump()),
                "evaluation": _sha(self.latest_evaluation), "delegations": _sha(self.delegations),
                "work": _sha(dir_digest(self.work_dir)), "web": _sha(self.web.state_dict()),
                "toolbox": _sha(self.toolbox.state_dict()), "original_task": _sha(self.original_task), "delegation": len(self.delegations), "action_index": k, "actions": _sha(self.actions),
                "first_action": not self.actions, "latest_probe": _sha(self.latest_probe)}

    def save_checkpoint(self, action, k):
        ck = self.run_dir / "checkpoints" / f"a{k}"
        ck.mkdir(parents=True)
        shutil.copytree(self.work_dir, ck / "work", symlinks=True)
        state = {"format": STATE_FORMAT, "task_id": self.task.task_id, "delegation": len(self.delegations),
                 "action_index": k, "first_action": not self.actions, "actions": self.actions, "latest_probe": self.latest_probe,
                 "pending_action": action, "memory": self.memory.dump(), "evaluation": self.latest_evaluation,
                 "delegations": self.delegations, "trace": self.trace.state_dict(), "web": self.web.state_dict(),
                 "toolbox": self.toolbox.state_dict(), "config": self.cfg.to_dict(), "models": self.model_identities(),
                 "tools": self.tool_cfg.to_dict(), "prompts_version": prompts.PROMPTS_VERSION,
                 "refiner_prompts_version": prompts.REFINER_PROMPTS_VERSION,
                 "evaluator_prompts_version": EVALUATOR_VERSION, "reader_identity": self.reader_identity,
                 "code_hash": code_hash(), "reference_date": self.reference_date}
        (ck / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str))
        (ck / "fingerprint.json").write_text(json.dumps(self.fingerprint(action, k), indent=2))
        (ck / "request.json").write_text(json.dumps(self._payload(pending_action=action),
                                                    ensure_ascii=False, indent=2, default=str))
        self.trace.event("checkpoint", delegation=len(self.delegations), action_index=k, path=str(ck))
        return ck

    @classmethod
    def restore(cls, checkpoint, run_dir, *, condition=None, label=None, task=None, **kw):
        ck = Path(checkpoint)
        state = json.loads((ck / "state.json").read_text())
        if state.get("format") != STATE_FORMAT:
            raise ValueError("historical checkpoint requires its code snapshot; no conversion supported")
        data = dict(state["config"])
        if condition is not None:
            data["condition"] = condition.to_dict()
        if label is not None:
            data["label"] = label
        if task is None:
            from minpilot.data.gaia import load_task
            task = load_task(state["task_id"])
        run = cls(run_config_from_dict(data), task, run_dir, **kw)
        if task.task_id != state["task_id"] or state["models"] != run.model_identities():
            raise ValueError("checkpoint task/model mismatch")
        if (state["prompts_version"], state["refiner_prompts_version"], state["evaluator_prompts_version"]) != (
                prompts.PROMPTS_VERSION, prompts.REFINER_PROMPTS_VERSION, EVALUATOR_VERSION):
            raise ValueError("checkpoint prompt version mismatch")
        old_tools, now_tools = state["tools"], run.tool_cfg.to_dict()
        if tool_identity(old_tools) != tool_identity(now_tools):
            raise ValueError("checkpoint tool settings mismatch")
        if _version_num(now_tools["blocklist_version"]) < _version_num(old_tools["blocklist_version"]):
            raise ValueError("checkpoint blocklist is newer than runtime")
        if "crawl4ai" in now_tools["reader_chain"] and (state.get("reader_identity") or run.reader_identity):
            if not same_identity(state.get("reader_identity"), run.reader_identity):
                raise ValueError("checkpoint reader identity mismatch")
        if escaping_symlinks(ck / "work"):
            raise ValueError("checkpoint workspace symlink escapes")
        run.reference_date = state["reference_date"]
        run.original_task = original_task_of(task, run.reference_date)
        shutil.copytree(ck / "work", run.work_dir, symlinks=True)
        run.toolbox = Toolbox(run.work_dir, run.web, run.trace, question=task.question)
        run.memory.load(state["memory"])
        run.latest_evaluation, run.delegations = state["evaluation"], state["delegations"]
        run.trace.load_state_dict(state["trace"])
        run.web.load_state_dict(state["web"])
        run.toolbox.load_state_dict(state["toolbox"])
        run.actions, run.latest_probe = state["actions"], state["latest_probe"]
        if state["first_action"] != (not run.actions):
            raise ValueError("checkpoint first_action mismatch")
        run._pending = state["pending_action"]
        if run._pending.get("action") not in run.available_actions():
            raise ValueError(f"checkpoint pending action {run._pending.get('action')!r} is not allowed by {run.cfg.condition.name}")
        run._validate_selection(run._pending, must_finish=len(run.delegations) >= run.cfg.max_delegations)
        saved = json.loads((ck / "fingerprint.json").read_text())
        now = run.fingerprint(run._pending, state["action_index"])
        checks = {key: saved[key] == now[key] for key in saved}
        (run.run_dir / "restore_check.json").write_text(json.dumps({"match": all(checks.values()), "keys": checks}))
        if not all(checks.values()):
            raise ValueError(f"checkpoint fingerprint mismatch: {checks}")
        run._write_run_json(**run._base_info("restore"), restored_from=str(ck.resolve()),
                            restored_delegation=state["delegation"], restored_action_index=state["action_index"],
                            checkpoint_code_hash=state["code_hash"])
        return run

    def run_restored(self):
        return self._guarded(lambda: self._loop(self._pending))
