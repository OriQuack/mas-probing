from minpilot import prompts
from minpilot.prompts.orchestrator import ORCHESTRATOR
from minpilot.prompts.schemas import action_tools


def test_prompt_versions_and_report_contract():
    assert (prompts.PROMPTS_VERSION, prompts.PROBE_PROMPTS_VERSION) == ("v24", "r24")
    text = prompts.worker_system("worker", ())
    assert "Title:" not in text and "Interpretation:" not in text and "Unfinished:" not in text
    assert "Your final message is your report to the orchestrator." in text and "access blocking" in text
    probe = prompts.probe_instruction("draft", True, 3)
    assert "Title:" not in probe and probe.index("understanding:") < probe.index("plan:")
    assert "which conditions of the original task apply to it" in probe
    assert "If a check reveals the answer, write it in that step's `observed:` line" in probe


def test_orchestrator_prompt_contract():
    # Contract checks on the text, not claims about a real model's behavior.
    for phrase in ["new source, method or clue", "inclusion and exclusion criteria", "A condition stated in the original task is not an assumption",
                   "your assignment was unclear; state what you meant", "Compare the plans separately from the understandings",
                   "say what you meant", "whose work it is, what it found", "call `execute` for every registered worker in the same message", "call `probe` once per assignment", "Give `answer` as one value in the answer format",
                   "the reading that best fits the original question", "When the `probe` tool is available, start the run with `probe`"]:
        assert phrase in ORCHESTRATOR, phrase
    for retired in ["`state`", "state_rows", "evaluator", "evaluation", "read_memory", "catalog", "historical role", "price"]:
        assert retired not in ORCHESTRATOR.lower(), retired


def test_action_tools_are_closed_and_named_as_actions():
    tools = action_tools(["probe", "execute", "finish"])
    assert [t["function"]["name"] for t in tools] == ["probe", "execute", "finish"]
    assert all(t["function"]["parameters"]["additionalProperties"] is False for t in tools)
    assert tools[1]["function"]["parameters"]["required"] == ["worker_id", "instruction", "artifact_ids", "rationale"]
    assert tools[0]["function"]["parameters"]["required"] == ["instruction", "artifact_ids", "rationale"]
    assert "Every call includes `rationale`" in ORCHESTRATOR
