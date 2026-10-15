"""Portable function-calling contracts for the orchestrator's actions, with semantic checks in the harness."""
STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}

ACTIONS = {
    "probe": ("Send the same assignment to every worker as a probe request in its own conversation. Each worker "
              "replies with its understanding of the assignment and its plan.",
              {"instruction": {**STRING, "description": "The assignment, written as for execution."},
               "artifact_ids": {**STRINGS, "description": "IDs of earlier reports to include as context; [] for none."},
               "rationale": {**STRING, "description": "What the reports so far establish, what remains unresolved and "
                                                      "why this assignment addresses it."}}),
    "execute": ("Send an execution request to one worker as the next turn of its conversation.",
                {"worker_id": {**STRING, "description": "The worker's ID."},
                 "instruction": {**STRING, "description": "Your next message to the worker."},
                 "artifact_ids": {**STRINGS, "description": "IDs of other workers' reports to include as context; [] for none."},
                 "rationale": {**STRING, "description": "What the reports so far establish, what remains unresolved and "
                                                        "why this instruction and this worker address it."}}),
    "finish": ("Give the final answer and end the run.",
               {"answer": {**STRING, "description": "One value in the answer format."},
                "rationale": {**STRING, "description": "The reports that support the answer, the reading of the "
                                                       "question you chose and the limits of the evidence."}}),
}


def action_tools(available):
    """Function schemas of the available actions, in the order given."""
    return [{"type": "function", "function": {
        "name": name, "description": ACTIONS[name][0],
        "parameters": {"type": "object", "properties": ACTIONS[name][1], "required": list(ACTIONS[name][1]),
                       "additionalProperties": False}}} for name in available]
