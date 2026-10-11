"""Worker reporting and targeted orchestrator rechecks."""

from __future__ import annotations

from minpilot import prompts


def test_worker_report_order():
    s = prompts.worker_system("You are a worker.", ("read_file",))
    i = [s.index(f"\n{k}:") for k in ("Result", "Evidence", "Interpretation", "Unfinished")]
    assert i == sorted(i) and "Assumptions:" not in s
    assert "claims not verified, remaining work" in s


def test_orchestrator_recheck_rule():
    roles = [{"id": "worker", "description": "Does things.", "tools": ["read_file"]}]
    s = prompts.orchestrator_system(roles, 12, "a number")
    assert ("Delegate a check only for a specific unresolved issue that could change the answer, and have the check "
            "report which observations support or change the current result.") in s
    assert "When an important result is in doubt" not in s
    assert prompts.PROMPTS_VERSION == "v7"
