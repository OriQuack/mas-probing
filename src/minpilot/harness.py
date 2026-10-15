"""Sequential runtime: the orchestrator's conversation directs probes and executions; each worker keeps one conversation and workspace."""
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
from minpilot.agents.orchestrator import Orchestrator
from minpilot.agents.worker import Worker
from minpilot.records import Records
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

STATE_FORMAT = 6
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
        self.records = Records(self.run_dir / "artifacts", self.trace)
        self.reference_date = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
        self.original_task = original_task_of(task, self.reference_date)
        self.transport, self.clients = transport, {}
        self.web = web or WebTools(self.tool_cfg, question=task.question)
        if self.web.reader is None:
            self.web.reader = PageReader(self.client(self.tool_cfg.reader_model), self.tool_cfg)
        self.toolboxes = {}
        self.workers = {wid: Worker(spec, self.client(spec.model)) for wid, spec in cfg.pool.workers.items()}
        self.conversations = {wid: [] for wid in self.workers}  # report IDs in each worker's conversation
        # The orchestrator knows workers by position in the pool, not by model.
        self.aliases = {wid: f"worker_{i + 1}" for i, wid in enumerate(self.workers)}
        self.by_alias = {alias: wid for wid, alias in self.aliases.items()}
        self.orchestrator = Orchestrator(self.client(cfg.orchestrator_model), self.trace)
        self.delegations, self.actions = [], []
        self.info = {}

    def client(self, key):
        if key not in self.clients:
            self.clients[key] = LLMClient(get_spec(key), self.trace, transport=self.transport)
        return self.clients[key]

    def worker_list(self):
        return [{"id": self.aliases[w.id], "tools": list(w.tools), "max_tool_calls": w.max_tool_calls,
                 "context_window": get_spec(w.model).context_window} for w in self.cfg.pool.workers.values()]

    def model_identities(self):
        keys = {self.cfg.orchestrator_model, self.tool_cfg.reader_model, *(w.model for w in self.cfg.pool.workers.values())}
        return {k: get_spec(k).identity() for k in sorted(keys)}

    def _write_run_json(self, **extra):
        self.info.update(extra)
        (self.run_dir / "run.json").write_text(json.dumps(self.info, ensure_ascii=False, indent=2, default=str))

    def _base_info(self, mode):
        return {"task_id": self.task.task_id, "level": self.task.level, "mode": mode, "label": self.cfg.label,
                "condition": self.cfg.condition.name, "status": "running", "final_answer": None,
                "started_at": time.time(), "git_commit": git_commit(), "code_hash": code_hash(),
                "prompts_version": prompts.PROMPTS_VERSION, "probe_prompts_version": prompts.PROBE_PROMPTS_VERSION,
                "config": self.cfg.to_dict(), "worker_aliases": self.aliases,
                "models": self.model_identities(), "tools": self.tool_cfg.to_dict(),
                "costs": {"version": COSTS_VERSION, "tool_usd_per_credit": TOOL_USD_PER_CREDIT},
                "reader_identity": self.reader_identity, "reference_date": self.reference_date}

    def run_fresh(self):
        self._write_run_json(**self._base_info("fresh"))
        for wid in self.workers:
            att = self.work_dir / wid / "attachments"
            att.mkdir(parents=True, exist_ok=True)
            if self.task.file_path:
                shutil.copy2(self.task.file_path, att / self.task.file_name)
        self._open_toolboxes()
        self.orchestrator.start(prompts.orchestrator_start(self.original_task, self.worker_list(),
                                                           self._budget_text(opening=True), ANSWER_FORMAT))
        return self._guarded(lambda: self._loop(None))

    def _open_toolboxes(self):
        self.toolboxes = {wid: Toolbox(self.work_dir / wid, self.web, self.trace, question=self.task.question)
                          for wid in self.workers}

    def available_actions(self, must_finish=False):
        if must_finish:
            return ["finish"]
        return (["probe"] if self.cfg.condition.name == "adaptive_probe" else []) + ["execute", "finish"]

    def _budget_text(self, opening=False):
        remaining = self.cfg.max_delegations - len(self.delegations)
        limits, spent = self.cfg.budget, self.trace.run_scope.counters()
        if opening:
            lines = [f"At most {self.cfg.max_delegations} executions in this run. Probe requests do not count toward this limit."]
        else:
            lines = [f"Remaining executions: {remaining}."]
        if limits.max_cost_usd is not None:
            lines.append(f"Cost: ${spent['cost_usd']:.4f} spent of ${limits.max_cost_usd:.2f}.")
        if limits.max_llm_calls is not None:
            lines.append(f"Model calls: {spent['llm_calls']} made of {limits.max_llm_calls}.")
        if not opening and remaining <= 0:
            lines.append(prompts.NO_EXECUTIONS_LEFT)
        return "\n".join(lines)

    def _validate(self, name, args, must_finish=False, accepted=()):
        """The action for a tool call, with the worker ID resolved and the context assembled; ValueError otherwise.
        `accepted`: actions already accepted from the same message (their executions count toward the limit)."""
        if name not in self.available_actions(must_finish):
            raise ValueError(f"{name!r} is not available")
        expected = {"probe": {"instruction", "artifact_ids", "rationale"},
                    "execute": {"worker_id", "instruction", "artifact_ids", "rationale"},
                    "finish": {"answer", "rationale"}}[name]
        if set(args) != expected:
            raise ValueError(f"{name} takes exactly: {', '.join(sorted(expected))}")
        for field in ("answer", "rationale") if name == "finish" else ("instruction", "rationale"):
            if not isinstance(args[field], str) or not args[field].strip():
                raise ValueError(f"{name} requires a nonempty {field}")
        if name == "finish":
            return {"action": "finish", "answer": args["answer"], "rationale": args["rationale"]}
        context = self.records.context(args["artifact_ids"], label=self.aliases.get)
        action = {"action": name, "instruction": args["instruction"], "artifact_ids": list(args["artifact_ids"]),
                  "context": context, "worker_id": None, "rationale": args["rationale"]}
        if name == "probe" and any(a["action"] == "probe" for a in accepted):
            raise ValueError("a single `probe` call already sends the assignment to every worker; "
                             "call it once per message")
        if name == "execute":
            planned = sum(a["action"] == "execute" for a in accepted)
            if len(self.delegations) + planned >= self.cfg.max_delegations:
                raise ValueError("no executions remain for this call")
            if args["worker_id"] not in self.by_alias:
                raise ValueError(f"unknown worker_id {args['worker_id']!r}; use one of {', '.join(self.by_alias)}")
            action.update(worker_id=self.by_alias[args["worker_id"]], worker_alias=args["worker_id"])
        return action

    def _decide(self):
        must_finish = len(self.delegations) >= self.cfg.max_delegations
        with self.trace.tags(stage="orchestrator"):
            return self.orchestrator.next_actions(
                self.available_actions(must_finish),
                lambda name, args, accepted: self._validate(name, args, must_finish, accepted))

    def _loop(self, pending):
        """`pending`: actions of the current message not yet run (a restored checkpoint's actions), else None.
        Each probe or execute is checkpointed before it runs, with the message's remaining actions."""
        restored = pending is not None
        while True:
            if not pending:
                with self.trace.tags(delegation=len(self.delegations), action_index=len(self.actions)):
                    pending = self._decide()
                    if pending[0]["action"] == "finish":
                        action = pending[0]
                        self.trace.event("action", **action)
                        self.info.update(final_rationale=action["rationale"], final_note=action["note"],
                                         forced_finish=len(self.delegations) >= self.cfg.max_delegations)
                        return action["answer"], "ok"
                restored = False
            k = len(self.delegations)
            with self.trace.tags(delegation=k, action_index=len(self.actions)):
                if not restored and self.cfg.checkpoint:
                    self.save_checkpoint(pending, len(self.actions))
                restored = False
                action, pending = pending[0], pending[1:]
                self.trace.event("action", **action)
                action["instruction_artifact_id"] = self.records.add("orchestrator", "instruction", action["instruction"])["id"]
                index = len(self.actions)
                self.actions.append({**action, "index": index})
                with self.trace.tags(action_index=index):
                    result = self._probe_round(action) if action["action"] == "probe" else self._delegate(action, k)
                self.orchestrator.reply(action["tool_call_id"], f"{result}\n\n{self._budget_text()}")

    def _request(self, wid, stage, instruction, context, **kw):
        """One request in a worker's conversation, saved as a report. A request that completes joins the
        conversation; a failed one is saved but leaves the conversation unchanged."""
        worker = self.workers[wid]
        worker.last_messages = []
        try:
            self.trace.before_worker_call()
            call = worker.run(self.original_task, instruction, self.toolboxes[wid], context=context, **kw)
        except (BudgetExceeded, InfraError) as error:
            status = "budget_exceeded" if stage == "probe" and isinstance(error, BudgetExceeded) else "failed"
            self.records.add(wid, stage, str(error), status=status, messages=worker.last_messages)
            raise
        except Exception as error:
            return self.records.add(wid, stage, str(error), status="failed", messages=worker.last_messages), None
        report = self.records.add(wid, stage, call.report, status=call.status, messages=call.messages)
        self.conversations[wid].append(report["id"])
        return report, call

    def _report_text(self, report):
        return prompts.report_block(report["id"], self.aliases[report["worker_id"]], report["stage"],
                                    report["status"], report["body"])

    def _probe_round(self, action):
        prior_ids = {r["id"] for r in self.records.artifacts}
        stopped = None
        try:
            with self.trace.budget_scope("probe_round", self.cfg.condition.budget):
                for wid in self.workers:
                    with self.trace.tags(stage="probe", worker=wid):
                        self._request(wid, "probe", prompts.probe_instruction(action["instruction"], True, 3),
                                      action["context"], max_tool_calls=3, kind="probe")
        except BudgetExceeded as error:
            if error.scope == "run":
                raise
            stopped = error
            self.trace.event("probe_budget_exceeded", what=error.what)
        reports = [r for r in self.records.artifacts if r["stage"] == "probe" and r["id"] not in prior_ids]
        self.actions[-1].update(report_ids=[r["id"] for r in reports])
        self.trace.event("probe_round", instruction=action["instruction"], context=action["context"],
                         report_ids=[r["id"] for r in reports], stopped=str(stopped) if stopped else None)
        text = "\n\n".join(self._report_text(r) for r in reports)
        if stopped:
            text += f"\n\nThe probe stopped at its budget ({stopped.what}); workers without a report above were not asked."
        return text

    def _delegate(self, action, k):
        wid, instruction, context = action["worker_id"], action["instruction"], action["context"]
        prior = list(self.conversations[wid])
        self.trace.event("delegation", delegation=k, worker=wid, worker_alias=self.aliases[wid],
                         instruction=instruction, instruction_id=action["instruction_artifact_id"], context=context,
                         rationale=action["rationale"], note=action["note"], conversation_report_ids=prior)
        with self.trace.tags(stage="execution", worker=wid):
            report, call = self._request(wid, "execution", instruction, context)
        self.trace.event("report", worker=wid, artifact_id=report["id"], status=report["status"],
                         n_tool_calls=call.n_tool_calls if call else 0, report=report["body"])
        repeat_of = next((d["index"] for d in self.delegations
                          if " ".join(d["instruction"].split()) == " ".join(instruction.split())), None)
        self.delegations.append({"repeat_of": repeat_of, "index": k, "instruction_id": action["instruction_artifact_id"],
                                 "action_index": len(self.actions) - 1, "worker": wid, "worker_alias": self.aliases[wid],
                                 "instruction": instruction, "conversation_report_ids": prior,
                                 "context": context, "artifact_ids": action["artifact_ids"], "report_id": report["id"],
                                 "rationale": action["rationale"], "note": action["note"],
                                 "report_status": report["status"],
                                 "n_tool_calls": call.n_tool_calls if call else 0})
        return self._report_text(report)

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
        with (self.run_dir / "orchestrator.jsonl").open("w") as stream:
            for message in self.orchestrator.messages:
                stream.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
        self._write_run_json(status=status, ended_at=time.time(), n_delegations=len(self.delegations), actions=self.actions,
                             n_probes=sum(a["action"] == "probe" for a in self.actions),
                             n_repeated_delegations=sum(d["repeat_of"] is not None for d in self.delegations),
                             delegations=self.delegations, usage=self.trace.usage,
                             counters=self.trace.run_scope.counters(), artifacts=self.records.catalog(),
                             paid_search=self.web.state_dict().get("paid_search"),
                             warnings=reasoning_warnings(self.trace.usage), **extra)
        return self.info

    def fingerprint(self, action, k):
        budget = self.trace.state_dict()
        budget["counters"] = {k: v for k, v in budget["counters"].items() if k != "wall_s"}
        return {"budget": _sha(budget), "pending_actions": _sha(action), "records": _sha(self.records.dump()),
                "delegations": _sha(self.delegations), "work": _sha(dir_digest(self.work_dir)),
                "web": _sha(self.web.state_dict()), "toolboxes": _sha(self._toolbox_states()),
                "sessions": _sha(self._sessions()), "orchestrator": _sha(self.orchestrator.messages),
                "original_task": _sha(self.original_task), "delegation": len(self.delegations), "action_index": k,
                "actions": _sha(self.actions)}

    def _toolbox_states(self):
        return {wid: toolbox.state_dict() for wid, toolbox in self.toolboxes.items()}

    def _sessions(self):
        return {wid: {"messages": w.messages, "input_tokens": w.input_tokens, "report_ids": self.conversations[wid]}
                for wid, w in self.workers.items()}

    def save_checkpoint(self, action, k):
        ck = self.run_dir / "checkpoints" / f"a{k}"
        ck.mkdir(parents=True)
        shutil.copytree(self.work_dir, ck / "work", symlinks=True)
        state = {"format": STATE_FORMAT, "task_id": self.task.task_id, "delegation": len(self.delegations),
                 "action_index": k, "actions": self.actions, "pending_actions": action, "records": self.records.dump(),
                 "delegations": self.delegations, "trace": self.trace.state_dict(), "web": self.web.state_dict(),
                 "toolboxes": self._toolbox_states(), "sessions": self._sessions(),
                 "orchestrator": self.orchestrator.messages, "worker_aliases": self.aliases,
                 "config": self.cfg.to_dict(), "models": self.model_identities(),
                 "tools": self.tool_cfg.to_dict(), "prompts_version": prompts.PROMPTS_VERSION,
                 "probe_prompts_version": prompts.PROBE_PROMPTS_VERSION, "reader_identity": self.reader_identity,
                 "code_hash": code_hash(), "reference_date": self.reference_date}
        (ck / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str))
        (ck / "fingerprint.json").write_text(json.dumps(self.fingerprint(action, k), indent=2))
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
        if (state["prompts_version"], state["probe_prompts_version"]) != (prompts.PROMPTS_VERSION,
                                                                         prompts.PROBE_PROMPTS_VERSION):
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
        if state["worker_aliases"] != run.aliases:
            raise ValueError("checkpoint workers mismatch")
        run.reference_date = state["reference_date"]
        run.original_task = original_task_of(task, run.reference_date)
        shutil.copytree(ck / "work", run.work_dir, symlinks=True)
        run._open_toolboxes()
        run.records.load(state["records"])
        run.delegations = state["delegations"]
        run.trace.load_state_dict(state["trace"])
        run.web.load_state_dict(state["web"])
        if set(state["toolboxes"]) != set(run.workers) or set(state["sessions"]) != set(run.workers):
            raise ValueError("checkpoint workers mismatch")
        for wid, worker in run.workers.items():
            run.toolboxes[wid].load_state_dict(state["toolboxes"][wid])
            session = state["sessions"][wid]
            worker.messages, worker.input_tokens = session["messages"], session["input_tokens"]
            run.conversations[wid] = list(session["report_ids"])
        run.orchestrator.messages = state["orchestrator"]
        run.actions = state["actions"]
        pending = state["pending_actions"]
        must_finish = len(run.delegations) >= run.cfg.max_delegations
        if not pending:
            raise ValueError("checkpoint has no pending action")
        for i, action in enumerate(pending):
            resolved = run._validate(action["action"], action["args"], must_finish, pending[:i])
            if any(resolved[key] != action[key] for key in resolved):
                raise ValueError("checkpoint pending action does not match its tool call")
        run._pending = pending
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
