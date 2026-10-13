"""Run-local immutable reports and evaluator-owned replace-all state."""
from __future__ import annotations

import copy
import json
from pathlib import Path

STATE_TYPES = ("observation", "assumption", "result", "progress")


class Memory:
    def __init__(self, root: Path, trace):
        self.root, self.trace = root, trace
        self.artifacts: list[dict] = []
        self.tool_artifacts: list[dict] = []
        self.state: list[dict] = []

    def add(self, worker_id: str, stage: str, body: str, *, status="ok", messages=(), title=None) -> dict:
        messages = list(messages)
        first = body.splitlines()[0].strip() if body else ""
        missing = not first.lower().startswith("title:") or not first[6:].strip()
        if title is not None:
            missing = not title.strip()
        else:
            title = "" if missing else first[6:].strip()
        title = f"{stage}: {worker_id}" if missing else title.strip()
        record = {"id": f"a{len(self.artifacts):05d}", "worker_id": worker_id, "stage": stage,
                  "title": title, "body": body, "status": status, "missing_title": missing,
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
        return [{k: a[k] for k in ("id", "worker_id", "stage", "title", "status")}
                | {"tool_count": len(a["tool_records"]), "tool_ids": list(a["tool_ids"])}
                for a in self.artifacts]

    def read(self, ref: str):
        for record in self.artifacts:
            if record["id"] == ref:
                return copy.deepcopy({k: v for k, v in record.items() if k != "tool_records"}) | {"tool_count": len(record["tool_records"])}
        for record in self.tool_artifacts:
            if record["id"] == ref:
                return copy.deepcopy(record)
        raise ValueError(f"unknown memory ID {ref!r}; use an ID from the catalog or a report's tool_ids")

    def validate_state(self, state):
        if not isinstance(state, list):
            raise ValueError("state must be a list")
        for row in state:
            if not isinstance(row, dict) or set(row) != {"type", "content", "status", "refs"}:
                raise ValueError("state rows require type, content, status, refs only")
            if row["type"] not in STATE_TYPES or not isinstance(row["content"], str) or not row["content"].strip():
                raise ValueError("invalid state type/content")
            statuses = ("incomplete", "complete", "blocked") if row["type"] == "progress" else ("unverified", "supported", "rejected")
            if row["status"] not in statuses or not isinstance(row["refs"], list):
                raise ValueError("invalid state status/refs")
            for ref in row["refs"]:
                if not isinstance(ref, str):
                    raise ValueError("state refs must be memory IDs")
                self.read(ref)
        return copy.deepcopy(state)

    def replace(self, state, *, evaluation, reason):
        after = self.validate_state(state)
        self.trace.event("state_replace", before=self.state, after=after,
                         evaluation=evaluation, reason=reason, updated_by="evaluator")
        self.state = after

    def context(self, artifact_ids, state_rows, snapshot=None):
        snapshot = self.state if snapshot is None else snapshot
        if not isinstance(artifact_ids, list) or not isinstance(state_rows, list):
            raise ValueError("artifact_ids/state_rows must be lists")
        selected = []
        for i in state_rows:
            if type(i) is not int or not 0 <= i < len(snapshot):
                raise ValueError(f"invalid state row {i!r}")
            selected.append({"row": i, **snapshot[i]})
        # Workers cannot query controller memory: include the evidence referenced by selected state rows.
        refs = list(dict.fromkeys([*artifact_ids, *(ref for row in selected for ref in row["refs"])]))
        records = [{k: v for k, v in self.read(ref).items() if k != "tool_records"} for ref in refs]
        return json.dumps({"state": selected, "artifacts": records}, ensure_ascii=False) if selected or records else ""

    def dump(self):
        return copy.deepcopy({"artifacts": self.artifacts, "tool_artifacts": self.tool_artifacts, "state": self.state})

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
        self.state = self.validate_state(data["state"])
        self.root.mkdir(parents=True, exist_ok=True)
        for a in [*self.artifacts, *self.tool_artifacts]:
            with (self.root / f"{a['id']}.json").open("x") as stream:
                stream.write(json.dumps(a, ensure_ascii=False, indent=2))
