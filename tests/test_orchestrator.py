"""Orchestrator actions with one role (no routing) and with several roles (decision P6)."""

from minpilot.agents import prompts
from minpilot.agents.orchestrator import Orchestrator
from minpilot.llm.client import json_schema_format

ONE = [{"id": "generalist", "description": "Does everything.", "tools": ["web_search", "read_file"]}]
TWO = [{"id": "web", "description": "Web.", "tools": ["web_search"]},
       {"id": "file", "description": "Files.", "tools": ["read_file"]}]


def orch(roles):
    return Orchestrator(None, roles, max_delegations=3, answer_format="a number")


def test_single_role_has_no_routing_choice():
    o = orch(ONE)
    system = o.initial_messages("task")[0]["content"]
    assert "worker_id" not in system and "Workers:" not in system and "generalist" in system
    assert "worker_id" not in o.format["json_schema"]["schema"]["properties"]
    problem, action = o._parse({"rationale": "r", "action": "delegate", "instruction": "do x"}, False)
    assert problem == "" and action.worker_id == "generalist" and action.instruction == "do x"


def test_multi_role_keeps_routing():
    o = orch(TWO)
    assert "worker_id" in o.initial_messages("task")[0]["content"]
    assert o.format == json_schema_format("orchestrator_action", prompts.ORCHESTRATOR_ACTION_SCHEMA)
    problem, action = o._parse({"rationale": "r", "action": "delegate", "instruction": "do x"}, False)
    assert action is None and "worker_id" in problem
    _, action = o._parse({"rationale": "r", "action": "delegate", "worker_id": "file", "instruction": "x"}, False)
    assert action.worker_id == "file"
