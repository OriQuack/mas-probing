"""The harness: one GAIA task, one run directory, one dynamic orchestrator loop.

    loop:  orchestrator action
             finish   -> final answer, done
             delegate -> [DELEGATION POINT k: checkpoint] -> refiner (if refine_at selects k) or override
                         -> call_worker(executor, original_task, instruction) on the main workspace
                         -> report appended to the orchestrator's history

`call_worker(worker_id, original_task, instruction) -> report` is the only way work gets done. The orchestrator
never touches tools or files. Workers are stateless between calls, so the run state at a delegation point is
small: the orchestrator's messages, the pending action, the delegation log, budget counters, tool counters
(search pin, code-run numbering) and the workspace files. That is exactly what a checkpoint saves.

Restores: `Run.restore(checkpoint, ...)` copies the checkpoint's workspace into a new run dir, verifies a
fingerprint of everything the continuation starts from, and resumes at the pending delegation with the given
refiner (condition) or a given instruction override (Exp 1, post-hoc). With `refine_at="first"` the refiner acts
on the first delegation this run handles: d0 for a fresh run, the restored delegation for a restore.

Run dir (outputs/runs/<task_id>/<stamp>_<label>/):
  run.json, events.jsonl, llm_calls.jsonl, messages.jsonl, tool_calls.jsonl
  work/                     the main workspace (attachments/ inside)
  checkpoints/d<k>/         state.json, fingerprint.json, request.json (the refiner's input), work/
  refine/d<k>.json          everything the refiner did at delegation k (answers, analysis, checks, rewrite)
  scratch/d<k>/<label>/     scratch workspaces of probes and verifications
"""

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

from minpilot.agents import prompts
from minpilot.agents.orchestrator import Action, InvalidAction, Orchestrator
from minpilot.agents.worker import Worker, WorkerCall
from minpilot.config import RefinerConfig, RunConfig, run_config_from_dict
from minpilot.data.gaia import ANSWER_FORMAT, GaiaTask
from minpilot.llm.client import LLMClient, Transport, json_schema_format
from minpilot.llm.specs import get_spec
from minpilot.refine.base import RefineRequest, RefineResult, make_refiner
from minpilot.runtime.costs import COSTS_VERSION, TOOL_USD_PER_CREDIT
from minpilot.runtime.trace import BudgetExceeded, InfraError, Trace
from minpilot.tools.config import REPO_ROOT, ToolConfig
from minpilot.tools.crawl4ai_service import same_identity
from minpilot.tools.reader import PageReader
from minpilot.tools.toolbox import Toolbox
from minpilot.tools.web import WebTools

STATE_FORMAT = 1
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
    """Hash of the package source (src/minpilot/**/*.py), recorded with runs and checkpoints."""
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


def original_task_of(task: GaiaTask) -> str:
    return prompts.original_task_text(task.question, f"attachments/{task.file_name}" if task.file_name else None)


class Run:
    def __init__(self, cfg: RunConfig, task: GaiaTask, run_dir: Path | str, *, transport: Transport | None = None,
                 web: WebTools | None = None, tool_cfg: ToolConfig | None = None, reader_identity: dict | None = None):
        self.cfg = cfg
        self.task = task
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = self.run_dir / "work"
        self.tool_cfg = tool_cfg or ToolConfig()
        self.reader_identity = reader_identity
        self.trace = Trace(self.run_dir, cfg.budget)
        self.original_task = original_task_of(task)
        self.transport = transport
        self.clients: dict[str, LLMClient] = {}
        self.web = web or WebTools(self.tool_cfg, question=task.question)
        if self.web.reader is None:  # read_url's page reader: a fixed model on the run's client and budgets
            self.web.reader = PageReader(self.client(self.tool_cfg.reader_model), self.tool_cfg)
        self.toolbox: Toolbox | None = None
        self.workers = {wid: Worker(spec, self.client(spec.model)) for wid, spec in cfg.pool.workers.items()}
        # the answer rules come from the benchmark (GAIA's own), not from the framework
        self.orchestrator = Orchestrator(self.client(cfg.orchestrator_model), self.role_list(), cfg.max_delegations,
                                         answer_format=ANSWER_FORMAT)
        self.refiner = make_refiner(cfg.refiner)
        self.messages: list[dict] = []
        self.delegations: list[dict] = []
        self.handled = 0                    # delegations handled by this process (refine_at="first")
        self.info: dict[str, Any] = {}

    # -- building blocks ---------------------------------------------------------------------
    def client(self, key: str) -> LLMClient:
        if key not in self.clients:
            self.clients[key] = LLMClient(get_spec(key), self.trace, transport=self.transport)
        return self.clients[key]

    def role_list(self) -> list[dict]:
        return [{"id": r.id, "description": r.description, "tools": list(self.cfg.pool.role_tools(r.id))}
                for r in self.cfg.pool.roles.values()]

    def model_identities(self) -> dict:
        keys = {self.cfg.orchestrator_model, self.cfg.refiner_model, self.tool_cfg.reader_model,
                *(w.model for w in self.cfg.pool.workers.values())}
        return {k: get_spec(k).identity() for k in sorted(keys)}

    def _setup_workspace(self) -> None:
        att = self.work_dir / "attachments"
        att.mkdir(parents=True, exist_ok=True)
        if self.task.file_path:
            shutil.copy2(self.task.file_path, att / self.task.file_name)

    def _write_run_json(self, **extra) -> None:
        self.info.update(extra)
        (self.run_dir / "run.json").write_text(json.dumps(self.info, indent=1, ensure_ascii=False, default=str))

    def _base_info(self, mode: str) -> dict:
        return {"task_id": self.task.task_id, "level": self.task.level, "mode": mode, "label": self.cfg.label,
                "condition": self.cfg.refiner.name, "refine_at": self.cfg.refine_at, "status": "running",
                "final_answer": None, "started_at": time.time(), "git_commit": git_commit(), "code_hash": code_hash(),
                "prompts_version": prompts.PROMPTS_VERSION,
                "refiner_prompts_version": prompts.REFINER_PROMPTS_VERSION, "config": self.cfg.to_dict(),
                "costs": {"version": COSTS_VERSION, "tool_usd_per_credit": TOOL_USD_PER_CREDIT},
                "models": self.model_identities(), "tools": self.tool_cfg.to_dict(),
                "reader_identity": self.reader_identity}

    # -- entry points ------------------------------------------------------------------------
    def run_fresh(self) -> dict:
        self._write_run_json(**self._base_info("fresh"))
        try:
            self._setup_workspace()
            self.toolbox = Toolbox(self.work_dir, self.web, self.trace, question=self.task.question)
            self.messages = self.orchestrator.initial_messages(self.original_task)
        except Exception as e:
            return self._finish("error_init", error=repr(e), tb=traceback.format_exc())
        return self._guarded(lambda: self._loop(None))

    @classmethod
    def restore(cls, checkpoint: Path | str, run_dir: Path | str, *, refiner: RefinerConfig | None = None,
                refine_at: str | None = None, label: str | None = None, override: str | None = None,
                override_source: str | None = None, task: GaiaTask | None = None, **kw) -> "Run":
        """Build a run that continues from `checkpoint`. The pool, models, budgets and tools come from the
        checkpoint; only the refiner (condition), refine_at and label may differ, or an instruction override."""
        ck = Path(checkpoint)
        state = json.loads((ck / "state.json").read_text())
        if state.get("format") != STATE_FORMAT:
            raise ValueError(f"checkpoint format {state.get('format')} != {STATE_FORMAT}")
        d = dict(state["config"])
        if refiner is not None:
            d["refiner"] = refiner.to_dict()
        if refine_at is not None:
            d["refine_at"] = refine_at
        if label is not None:
            d["label"] = label
        cfg = run_config_from_dict(d)
        if task is None:
            from minpilot.data.gaia import load_task

            task = load_task(state["task_id"])
        if task.task_id != state["task_id"]:
            raise ValueError(f"checkpoint is for task {state['task_id']}, not {task.task_id}")
        run = cls(cfg, task, run_dir, **kw)
        run._restore_state(ck, state, override, override_source)
        return run

    def _restore_state(self, ck: Path, state: dict, override: str | None, override_source: str | None) -> None:
        self.info = self._base_info("restore")
        self.info.update(restored_from=str(ck.resolve()), restored_delegation=state["delegation"],
                         override=override is not None, override_source=override_source)
        self._write_run_json()
        problems = []
        if state["models"] != self.model_identities():
            problems.append("model identities differ from the checkpoint")
        now_tools = self.tool_cfg.to_dict()
        if state["tools"]["tools_version"] != now_tools["tools_version"]:
            problems.append(f"tools_version differs ({state['tools']['tools_version']} vs {now_tools['tools_version']})")
        # every setting that changes what a tool returns (page size, reader chain, timeouts, ...), not only versions
        old_id, new_id = tool_identity(state["tools"]), tool_identity(now_tools)
        if diff := sorted(k for k in set(old_id) | set(new_id) if old_id.get(k) != new_id.get(k)):
            problems.append(f"tool settings differ: {diff}")
        # the page-reader service (image digest) when the chain uses it
        if "crawl4ai" in now_tools["reader_chain"]:
            saved, now = state.get("reader_identity"), self.reader_identity
            if (saved or now) and not same_identity(saved, now):
                problems.append("page-reader service identity differs from the checkpoint's")
        if bad := escaping_symlinks(ck / "work"):
            problems.append(f"checkpoint workspace has symlinks leading outside it: {bad[:5]}")
        # code changes are recorded, not refused: the versions above are the restore contract (decision T9)
        saved_code = state.get("code_hash")
        self.info["checkpoint_code_hash"] = saved_code
        # None = unknown (checkpoints recorded before code hashes existed)
        self.info["code_changed_since_checkpoint"] = None if not saved_code else saved_code != code_hash()
        # A newer blocklist may continue an older checkpoint (it only removes leak paths, and every condition of a
        # paired comparison restores under the same one); an older blocklist may not.
        if _version_num(now_tools["blocklist_version"]) < _version_num(state["tools"]["blocklist_version"]):
            problems.append(f"blocklist_version is older than the checkpoint's ({now_tools['blocklist_version']} < "
                            f"{state['tools']['blocklist_version']})")
        self.info["checkpoint_blocklist_version"] = state["tools"]["blocklist_version"]
        if state["prompts_version"] != prompts.PROMPTS_VERSION:
            problems.append("prompts version differs")
        if problems:
            raise ValueError("refusing to restore: " + "; ".join(problems))
        shutil.copytree(ck / "work", self.work_dir, symlinks=True)
        self.toolbox = Toolbox(self.work_dir, self.web, self.trace, question=self.task.question)
        self.messages = state["messages"]
        self.delegations = state["delegations"]
        self.trace.load_state_dict(state["trace"])
        self.web.load_state_dict(state["web"])
        self.toolbox.load_state_dict(state["toolbox"])
        self._pending = (Action(**state["pending_action"]), state["delegation"])
        self._override = (override, override_source)
        saved = json.loads((ck / "fingerprint.json").read_text())
        now = self.fingerprint(self._pending[0], state["delegation"])
        check = {k: saved[k] == now[k] for k in saved}
        (self.run_dir / "restore_check.json").write_text(json.dumps({"match": all(check.values()), "keys": check},
                                                                     indent=1))
        self.trace.event("restore_check", match=all(check.values()), keys=check, checkpoint=str(ck))
        if not all(check.values()):
            raise ValueError(f"restore fingerprint mismatch: {[k for k, v in check.items() if not v]}")

    def run_restored(self) -> dict:
        action, k = self._pending
        return self._guarded(lambda: self._loop((action, k)))

    # -- the loop ----------------------------------------------------------------------------
    def _guarded(self, fn) -> dict:
        try:
            answer, status = fn()
            return self._finish(status, final_answer=answer)
        except BudgetExceeded as e:
            self.trace.event("budget_exceeded", scope=e.scope, what=e.what)
            return self._finish("budget_exceeded", error=str(e))
        except InfraError as e:
            self.trace.event("error_infra", error=str(e))
            return self._finish("error_infra", error=str(e))
        except InvalidAction as e:
            self.trace.event("invalid_action", error=str(e))
            return self._finish("error", error=f"invalid_action: {e}")
        except Exception as e:
            self.trace.event("error", error=repr(e), tb=traceback.format_exc())
            return self._finish("error", error=repr(e), tb=traceback.format_exc())

    def _loop(self, pending: tuple[Action, int] | None) -> tuple[str | None, str]:
        override = getattr(self, "_override", (None, None))
        while True:
            if pending is not None:
                action, k = pending
                pending = None
            else:
                k = len(self.delegations)
                must_finish = k >= self.cfg.max_delegations
                with self.trace.tags(stage="orchestrator", delegation=k):
                    action = self.orchestrator.next_action(self.messages, must_finish=must_finish)
                self.trace.event("action", delegation=k, action=action.kind, worker_id=action.worker_id,
                                 instruction=action.instruction, answer=action.answer, rationale=action.rationale,
                                 forced=must_finish, invalid_before=self.orchestrator.last_invalid)
                if action.kind == "finish":
                    # the answer is kept exactly as given (scoring extracts separately); the rationale is kept for
                    # post-hoc reading of qualified answers (decisions F16)
                    self.info.update(forced_finish=must_finish, final_rationale=action.rationale)
                    return action.answer, "ok"
                if self.cfg.checkpoint:
                    self.save_checkpoint(action, k)
            self._delegate(action, k, override)
            override = (None, None)

    # -- the worker interface (spec: call_worker(worker_id, original_task, instruction) -> report) --------
    def call_worker(self, worker_id: str, original_task: str, instruction: str) -> str:
        """The spec's interface: run `worker_id` on the main workspace and return its report. Ports to other
        frameworks implement this; the harness itself uses `run_worker`, which also returns status and tool
        counts."""
        return self.run_worker(worker_id, original_task, instruction).report

    def run_worker(self, worker_id: str, original_task: str, instruction: str, *,
                   history: list[dict] | None = None) -> WorkerCall:
        self.trace.before_worker_call()
        return self.workers[worker_id].run(original_task, instruction, self.toolbox, history=history)

    def _refine_here(self) -> bool:
        return self.cfg.refine_at == "all" or (self.cfg.refine_at == "first" and self.handled == 0)

    def _delegate(self, action: Action, k: int, override: tuple[str | None, str | None]) -> None:
        role = self.cfg.pool.roles[action.worker_id]
        req = RefineRequest(self.original_task, action.instruction, role.id, role.executor, role.probe_workers)
        result: RefineResult
        if override[0] is not None:
            result = RefineResult(override[0], override[0] != action.instruction, "override",
                                  {"override_source": override[1]})
        elif self._refine_here():
            with self.trace.tags(delegation=k, role=role.id):
                result = self.refiner.refine(req, _Ctx(self, k))
        else:
            result = RefineResult(action.instruction, False, "not_selected", {})
        self.handled += 1
        if result.log:
            (self.run_dir / "refine").mkdir(exist_ok=True)
            (self.run_dir / "refine" / f"d{k}.json").write_text(json.dumps(
                {**result.log, "status": result.status, "final": result.instruction}, indent=1, ensure_ascii=False))
        self.trace.event("delegation", delegation=k, role=role.id, worker=role.executor, draft=action.instruction,
                         final=result.instruction, changed=result.changed, refine_status=result.status,
                         refiner=self.cfg.refiner.name, connected=result.execution_history is not None)
        with self.trace.tags(stage="execution", delegation=k, role=role.id, worker=role.executor):
            call = self.run_worker(role.executor, self.original_task, result.instruction,
                                   history=result.execution_history)
        self.trace.event("report", delegation=k, worker=role.executor, status=call.status,
                         n_tool_calls=call.n_tool_calls, report=call.report)
        self.delegations.append({"index": k, "role": role.id, "worker": role.executor, "draft": action.instruction,
                                 "final": result.instruction, "changed": result.changed,
                                 "refine_status": result.status, "report_status": call.status,
                                 "n_tool_calls": call.n_tool_calls})
        sent = result.instruction if (result.changed and self.cfg.show_final_instruction) else None
        self.messages.append({"role": "user", "content": prompts.report_message(role.id, k, call.report, sent)})

    def _finish(self, status: str, **extra) -> dict:
        warnings = reasoning_warnings(self.trace.usage)
        self.trace.event("run_end", status=status, warnings=warnings)
        self._write_run_json(status=status, ended_at=time.time(), n_delegations=len(self.delegations),
                             delegations=self.delegations, usage=self.trace.usage,
                             counters=self.trace.run_scope.counters(), warnings=warnings, **extra)
        return self.info

    # -- checkpoints -------------------------------------------------------------------------
    def fingerprint(self, action: Action, k: int) -> dict:
        """Everything the continuation from delegation k starts from."""
        return {"orchestrator_messages": _sha(self.messages), "pending_action": _sha(action.__dict__),
                "delegations": _sha(self.delegations), "work": _sha(dir_digest(self.work_dir)),
                "web": _sha(self.web.state_dict()), "toolbox": _sha(self.toolbox.state_dict()),
                "original_task": _sha(self.original_task), "delegation": k}

    def save_checkpoint(self, action: Action, k: int) -> Path:
        ck = self.run_dir / "checkpoints" / f"d{k}"
        ck.mkdir(parents=True)
        shutil.copytree(self.work_dir, ck / "work", symlinks=True)
        state = {"format": STATE_FORMAT, "task_id": self.task.task_id, "delegation": k,
                 "pending_action": action.__dict__, "messages": self.messages, "delegations": self.delegations,
                 "trace": self.trace.state_dict(), "web": self.web.state_dict(), "toolbox": self.toolbox.state_dict(),
                 "config": self.cfg.to_dict(), "models": self.model_identities(), "tools": self.tool_cfg.to_dict(),
                 "prompts_version": prompts.PROMPTS_VERSION,
                 "refiner_prompts_version": prompts.REFINER_PROMPTS_VERSION, "reader_identity": self.reader_identity,
                 "code_hash": code_hash()}
        (ck / "state.json").write_text(json.dumps(state, indent=1, ensure_ascii=False, default=str))
        (ck / "fingerprint.json").write_text(json.dumps(self.fingerprint(action, k), indent=1))
        role = self.cfg.pool.roles[action.worker_id]
        # the refiner's whole input (and nothing after the checkpoint): for post-hoc rewrites and audits
        (ck / "request.json").write_text(json.dumps(
            {"original_task": self.original_task, "draft_instruction": action.instruction, "target_role": role.id,
             "target_worker": role.executor, "probe_workers": list(role.probe_workers)}, indent=1, ensure_ascii=False))
        self.trace.event("checkpoint", delegation=k, path=str(ck))
        return ck


class _Ctx:
    """`RefineContext` for delegation k of a run."""

    def __init__(self, run: Run, k: int):
        self.run = run
        self.k = k
        self.toolboxes: dict[str, Toolbox] = {}

    def llm(self, messages, *, stage, schema_name=None, schema=None):
        fmt = json_schema_format(schema_name, schema) if schema else None
        with self.run.trace.tags(stage=stage):
            return self.run.client(self.run.cfg.refiner_model).chat(messages, response_format=fmt)

    def toolbox(self, label: str) -> Toolbox:
        """A toolbox on a scratch copy of the main workspace as it is now; one per label (a probe and its
        follow-ups share it). Code-run numbering continues from the main workspace's. Web: the shared cache, but
        a forked search pin and blocked-URL set (WebTools.fork)."""
        label = label or f"call{self.run.trace.next_id()}"
        if label not in self.toolboxes:
            d = self.run.run_dir / "scratch" / f"d{self.k}" / label
            shutil.copytree(self.run.work_dir, d, symlinks=True)
            tb = Toolbox(d, self.run.web.fork(), self.run.trace, question=self.run.task.question)
            tb.load_state_dict(self.run.toolbox.state_dict())
            self.toolboxes[label] = tb
        return self.toolboxes[label]

    def call_worker(self, worker_id, original_task, instruction, *, stage, allow_tools, max_tool_calls=None,
                    history=None, user_message=None, label="") -> WorkerCall:
        run = self.run
        toolbox = self.toolbox(label)
        with run.trace.tags(stage=stage, worker=worker_id, scratch=label):
            run.trace.before_worker_call()
            call = run.workers[worker_id].run(original_task, instruction, toolbox, allow_tools=allow_tools,
                                              max_tool_calls=max_tool_calls, history=history,
                                              user_message=user_message)
        run.trace.event("refine_worker_call", stage=stage, worker=worker_id, scratch=label, status=call.status,
                        n_tool_calls=call.n_tool_calls, report=call.report)
        return call

    def worker_profile(self, worker_id: str) -> dict:
        pool = self.run.cfg.pool
        spec = pool.workers[worker_id]
        role = next((r for r in pool.roles.values() if worker_id == r.executor or worker_id in r.probe_workers), None)
        return {"id": worker_id, "role": role.id if role else worker_id, "description": role.description if role else "",
                "model": spec.model, "tools": list(spec.tools)}

    def roles(self) -> list[dict]:
        return self.run.role_list()

    def role_executor(self, role_id: str) -> str | None:
        role = self.run.cfg.pool.roles.get(role_id)
        return role.executor if role else None

    def budget_scope(self, cfg: RefinerConfig):
        return self.run.trace.budget_scope("refine", cfg.budget)
