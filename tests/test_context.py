"""Context separated from the instruction (decision F21): the orchestrator writes both, every refiner step reads
the context, only the instruction is rewritten, and the executor gets the context unchanged (also after a
restore)."""

from __future__ import annotations

import json

from fakes import ScriptedLLM, delegate, fake_web, finish
from minpilot.agents import prompts
from minpilot.agents.orchestrator import Orchestrator
from minpilot.config import load_refiner
from minpilot.harness import Run
from minpilot.tools.config import ToolConfig
from test_harness import make_run

LUNA, HAIKU = "openai/gpt-6-luna-20260922", "anthropic/claude-haiku-5.5-20261007"
CTX = "An earlier report (not verified) said the sheet has 100 orders, counted as rows."
DRAFT = "Count the orders in attachments/sheet.csv for 2025."
REWRITTEN = "Count UNIQUE order ids in attachments/sheet.csv for 2025; recheck the earlier row count of 100."
ISSUE = {"id": "i1", "kind": "assumption", "summary": "rows vs unique ids", "evidence": "r1 counts rows",
         "decision": "needs_verification", "resolution": "check whether ids repeat"}
CHECK = {"issue_id": "i1", "worker_id": "worker", "instruction": "check whether ids repeat"}


def script(**extra):
    s = {"orchestrator": [delegate("worker", DRAFT, CTX), finish("2")],
         "analyze": [{"issues": [ISSUE], "followups": [], "verifications": [CHECK]}],
         "rewrite": [{"instruction": REWRITTEN, "changes": ["unique ids"], "unchanged": False}]}
    s.update(extra)
    return s


def user_text(body) -> str:
    return body["messages"][1]["content"]


def test_orchestrator_writes_context_and_instruction():
    system = prompts.orchestrator_system([{"id": "worker", "description": "d", "tools": ["web_search"]}], 5, "fmt")
    assert "set `context` and `instruction`" in system and "Keep reported claims as reported" in system
    assert "context" in prompts.orchestrator_action_schema(1)["properties"]
    orch = Orchestrator(None, [{"id": "worker", "description": "d", "tools": []}], 5, answer_format="fmt")
    _, a = orch._parse(delegate("worker", "do x", "  ctx  "), False)
    _, b = orch._parse({"rationale": "r", "action": "delegate", "instruction": "do x"}, False)
    assert (a.context, b.context) == ("ctx", "")


def test_requests_without_context_have_no_context_section():
    text = prompts.worker_request("task", "do x")
    assert "Context (" not in text and text.startswith("Original task:\n<<<\ntask\n>>>\n\nYour instruction:")
    probe = prompts.probe_instruction("do x", ("plan",), False, 0)
    assert "context" not in probe
    with_ctx = prompts.worker_request("task", "do x", context="c")
    assert with_ctx.index("Original task") < with_ctx.index("Context (") < with_ctx.index("Your instruction")


def test_every_c3_step_reads_the_context_and_execution_gets_it_unchanged(tmp_path, task):
    llm = ScriptedLLM(script(**{f"worker:{LUNA}": ["probe answer luna", "ids repeat", "2 unique orders"],
                                f"worker:{HAIKU}": ["probe answer haiku"]}))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c3_probe_multi")
    assert run.run_fresh()["status"] == "ok"
    probes, check, execution = llm.by_kind["worker"][:2], llm.by_kind["worker"][2], llm.by_kind["worker"][3]
    for b in probes:
        assert CTX in user_text(b) and "(with the context above)" in user_text(b)
    assert CTX in user_text(check) and "Do only this check" in user_text(check)
    analysis = user_text(llm.by_kind["analyze"][0])
    assert CTX in analysis and "passed to the worker unchanged" in analysis
    assert "the original task, the context and your check instruction" in analysis
    rewrite = user_text(llm.by_kind["rewrite"][0])
    assert CTX in rewrite and "Only the instruction is rewritten" in rewrite
    sent = user_text(execution)
    assert sent.count(CTX) == 1 and REWRITTEN in sent and DRAFT not in sent
    d = json.loads((run.run_dir / "run.json").read_text())["delegations"][0]
    assert d["context"] == CTX and d["final"] == REWRITTEN and d["changed"]


def test_c1_prediction_sees_the_same_context_as_a_real_probe(tmp_path, task):
    llm = ScriptedLLM(script(simulate=["predicted answers"], worker=["ids repeat", "2 unique orders"]))
    run = make_run(tmp_path, task, llm, pool="multi", refiner="c1_self_review")
    run.run_fresh()
    sim = user_text(llm.by_kind["simulate"][0])
    real = prompts.worker_request(run.original_task, prompts.probe_instruction(DRAFT, run.cfg.refiner.questions, False,
                                                                               0, True), context=CTX, kind="probe")
    assert real in sim


def test_restore_keeps_the_checkpoint_context(tmp_path, task):
    run1 = make_run(tmp_path, task, ScriptedLLM({"orchestrator": [delegate("worker", DRAFT, CTX), finish("2")],
                                                 "worker": ["2"]}), pool="multi", name="rec")
    run1.run_fresh()
    ck = run1.run_dir / "checkpoints" / "d0"
    assert json.loads((ck / "request.json").read_text())["context"] == CTX
    llm2 = ScriptedLLM(script(worker=["probe answer", "ids repeat", "2 unique orders"],
                              orchestrator=[finish("2")]))
    run2 = Run.restore(ck, tmp_path / "r", task=task, transport=llm2, refiner=load_refiner("c2_probe_executor"),
                       web=fake_web(tmp_path, task.question), tool_cfg=ToolConfig(cache_path=tmp_path / "cache.sqlite"))
    assert run2.run_restored()["status"] == "ok"
    assert all(CTX in user_text(b) for b in llm2.by_kind["worker"])
    assert user_text(llm2.by_kind["worker"][-1]).count(CTX) == 1
