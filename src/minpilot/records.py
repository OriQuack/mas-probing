"""Run-local immutable records: worker reports, instructions and the tool results linked to reports."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from minpilot.prompts.orchestrator import report_block


class Records:
    def __init__(self, root: Path, trace):
        self.root, self.trace = root, trace
        self.artifacts: list[dict] = []
        self.tool_artifacts: list[dict] = []

    def add(self, worker_id: str, stage: str, body: str, *, status="ok", messages=()) -> dict:
        messages = list(messages)
        record = {"id": f"a{len(self.artifacts):05d}", "worker_id": worker_id, "stage": stage,
                  "title": f"{stage}: {worker_id}", "body": body, "status": status,
                  "tool_records": [copy.deepcopy(m) for m in messages if m.get("role") == "tool"]}
        calls = {call["id"]: call.get("function", {})
                 for message in messages if message.get("role") == "assistant"
                 for call in message.get("tool_calls", []) if "id" in call}
        tools = []
        for index, message in enumerate(record["tool_records"]):
            function = calls.get(message.get("tool_call_id"), {})
            tools.append({**message, "name": function.get("name", message.get("name")),
                          "arguments": copy.deepcopy(function.get("arguments")), "id": f"t{len(self.tool_artifacts) + index:05d}",
                          "parent_id": record["id"], "worker_id": worker_id, "stage": stage,
                          "title": f"Tool result: {function.get('name') or message.get('name') or message.get('tool_call_id', 'unnamed')}",
                          "body": message.get("content", ""), "report_status": status})
        record["tool_ids"] = [tool["id"] for tool in tools]
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / f"{record['id']}.json").open("x") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, indent=2))
        for tool in tools:
            with (self.root / f"{tool['id']}.json").open("x") as stream:
                stream.write(json.dumps(tool, ensure_ascii=False, indent=2))
            self.trace.event("tool_artifact", **tool)
        self.tool_artifacts.extend(tools)
        self.artifacts.append(record)
        self.trace.event("artifact", **record)
        return record

    def catalog(self):
        """Record metadata for run.json; no model reads it."""
        return [{k: a[k] for k in ("id", "worker_id", "stage", "status")}
                | {"tool_count": len(a["tool_records"]), "tool_ids": list(a["tool_ids"])}
                for a in self.artifacts]

    def read(self, ref: str):
        for record in self.artifacts:
            if record["id"] == ref:
                return copy.deepcopy({k: v for k, v in record.items() if k != "tool_records"}) | {"tool_count": len(record["tool_records"])}
        for record in self.tool_artifacts:
            if record["id"] == ref:
                return copy.deepcopy(record)
        raise ValueError(f"unknown record ID {ref!r}")

    def context(self, artifact_ids, label=lambda worker_id: worker_id):
        """Selected reports in full, for a worker request; `label` names the reporting worker as the orchestrator
        knows it."""
        if not isinstance(artifact_ids, list) or not all(isinstance(ref, str) for ref in artifact_ids):
            raise ValueError("artifact_ids must be a list of report IDs")
        reports = [self.report(ref) for ref in dict.fromkeys(artifact_ids)]
        return "\n\n".join(report_block(r["id"], label(r["worker_id"]), r["stage"], r["status"], r["body"])
                           for r in reports)

    def report(self, ref: str):
        for record in self.artifacts:
            if record["id"] == ref and record["stage"] in ("probe", "execution"):
                return record
        raise ValueError(f"unknown report ID {ref!r}; use the ID shown with a report")

    def dump(self):
        return copy.deepcopy({"artifacts": self.artifacts, "tool_artifacts": self.tool_artifacts})

    def load(self, data):
        for i, artifact in enumerate(data["artifacts"]):
            if artifact.get("id") != f"a{i:05d}":
                raise ValueError("invalid artifact IDs/order in checkpoint")
        self.artifacts = copy.deepcopy(data["artifacts"])
        self.tool_artifacts = copy.deepcopy(data["tool_artifacts"])
        expected_links = []
        for artifact in self.artifacts:
            if len(artifact["tool_ids"]) != len(artifact["tool_records"]):
                raise ValueError("invalid tool links in checkpoint")
            expected_links.extend((ref, artifact["id"]) for ref in artifact["tool_ids"])
        actual_links = [(a.get("id"), a.get("parent_id")) for a in self.tool_artifacts]
        if actual_links != [(f"t{i:05d}", parent) for i, (_, parent) in enumerate(expected_links)] or actual_links != expected_links:
            raise ValueError("invalid tool IDs/links in checkpoint")
        self.root.mkdir(parents=True, exist_ok=True)
        for a in [*self.artifacts, *self.tool_artifacts]:
            with (self.root / f"{a['id']}.json").open("x") as stream:
                stream.write(json.dumps(a, ensure_ascii=False, indent=2))
