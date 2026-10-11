"""Structured response contracts; prompt wording lives in the role modules."""

DECISIONS = ("clarify", "needs_verification", "defer_to_execution", "not_relevant")

ORCHESTRATOR_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string", "description": "Briefly state what is established, what remains unresolved, "
                                                       "and why this action is appropriate now."},
        "action": {"type": "string", "enum": ["delegate", "finish"]},
        "worker_id": {"type": "string"},
        "context": {"type": "string", "description": "Information from earlier reports that the worker needs, with "
                                                    "source and verification status; empty if none."},
        "instruction": {"type": "string"},
        "answer": {"type": "string", "description": "Only the final answer, in the required format."},
    },
    "required": ["rationale", "action"],
}

ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "target": {"type": "string", "description": "The phrase of the instruction at issue, or what it omits."},
            "impact": {"type": "string", "description": "Why it can lead to an incorrect result or an incomplete "
                                                        "subtask."},
            "evidence": {"type": "string", "description": "What shows it: the original task's text, answer ids, "
                                                          "reported observations with their source."},
            "decision": {"type": "string", "enum": list(DECISIONS)},
            "resolution": {"type": "string", "description": "The change or check it needs."},
        }, "required": ["id", "target", "impact", "evidence", "decision", "resolution"]}},
        "followups": {"type": "array", "items": {"type": "object", "properties": {
            "response_id": {"type": "string"}, "question": {"type": "string"}},
            "required": ["response_id", "question"]}},
        "verifications": {"type": "array", "items": {"type": "object", "properties": {
            "issue_id": {"type": "string"}, "worker_id": {"type": "string"}, "instruction": {"type": "string"}},
            "required": ["issue_id", "worker_id", "instruction"]}},
    },
    "required": ["issues", "followups", "verifications"],
}

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "instruction": {"type": "string"},
        "context_additions": {"type": "string", "description": "Facts the executor needs that the task and context "
                                                              "do not contain, with source and verification status; "
                                                              "empty if none."},
        "changes": {"type": "array", "items": {"type": "string"}},
        "unchanged": {"type": "boolean"},
    },
    "required": ["instruction", "context_additions", "changes", "unchanged"],
}
