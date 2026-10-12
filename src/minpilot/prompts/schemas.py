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
        fields = {"title": STRING, "state": STATE, "changes": STRING}
    elif stage == "refiner":
        fields = {"can_refine": BOOLEAN, "instruction": STRING, "context_notes": STRING}
    else:
        fields = {"worker_id": STRING, "instruction": STRING, "answer": STRING,
                  "artifact_ids": STRINGS, "state_rows": {"type": "array", "items": {"type": "integer"}},
                  "instruction_id": STRING}
    return {"type": "object", "properties": {k: {**v, "type": [v["type"], "null"]} if k != "action" else v for k, v in {**common, **fields}.items()}, "required": ["action"]}
