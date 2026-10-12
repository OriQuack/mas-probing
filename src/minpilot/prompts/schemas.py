"""Portable flat JSON contracts, with semantic checks in the harness."""
STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
STRINGS = {"type": "array", "items": STRING}
STATE = {"type": "array", "items": {"type": "object", "properties": {
    "type": {"type": "string", "enum": ["observation", "assumption", "result", "progress"]},
    "content": STRING, "status": {"type": "string", "enum": ["unverified", "supported", "rejected", "incomplete", "complete", "blocked"]},
    "refs": STRINGS}, "required": ["type", "content", "status", "refs"]}}


def decision_schema(stage):
    common = {"action": STRING, "refs": STRINGS, "rationale": STRING}
    if stage.startswith("evaluator"):
        fields = {"title": STRING, "state": STATE, "changes": STRING, "requires_decision": BOOLEAN}
    elif stage == "refiner":
        fields = {"reconsider": BOOLEAN, "instruction": STRING, "context_notes": STRING}
    else:
        fields = {"worker_id": STRING, "instruction": STRING, "answer": STRING,
                  "artifact_ids": STRINGS, "state_rows": {"type": "array", "items": {"type": "integer"}},
                  "accept_state": BOOLEAN, "state_reason": STRING, "refine": BOOLEAN, "changes": STRING}
    return {"type": "object", "properties": {**common, **fields}, "required": ["action"]}
