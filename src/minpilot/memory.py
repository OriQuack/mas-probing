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
        self.state: list[dict] = []

    def add(self, worker_id: str, stage: str, body: str, *, status="ok", messages=(), title=None) -> dict:
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
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / f"{record['id']}.json").open("x") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, indent=2))
        self.artifacts.append(record)
        self.trace.event("artifact", **record)
        return record

    def catalog(self):
        return [{k: a[k] for k in ("id", "worker_id", "stage", "title", "status")}
                | {"tool_count": len(a["tool_records"])}
                for a in self.artifacts]

    def read(self, ref: str):
        parts = ref.split("/")
        a = next((a for a in self.artifacts if a["id"] == parts[0]), None)
        if a is None:
            raise ValueError(f"unknown artifact {ref!r}")
        if len(parts) == 1:
            return copy.deepcopy({k: v for k, v in a.items() if k != "tool_records"}) | {"tool_count": len(a["tool_records"])}
        if len(parts) == 3 and parts[1] == "tool" and parts[2].isdigit():
            i = int(parts[2])
            if i < len(a["tool_records"]):
                return copy.deepcopy({"ref": ref, "worker_id": a["worker_id"], "stage": a["stage"],
                                      "report_status": a["status"], **a["tool_records"][i]})
        raise ValueError(f"unknown tool reference {ref!r}")

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
                if not isinstance(ref, str) or "/" in ref:
                    raise ValueError("state refs must be artifact IDs")
                self.read(ref)
        return copy.deepcopy(state)

    def replace(self, state, *, evaluation, decision):
        after = self.validate_state(state)
        self.trace.event("state_replace", before=self.state, after=after,
                         evaluation=evaluation, decision=decision)
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
        # Workers cannot query controller memory: include the source reports of selected state rows.
        refs = list(dict.fromkeys([*artifact_ids, *(ref for row in selected for ref in row["refs"])]))
        records = [{k: v for k, v in self.read(ref).items() if k != "tool_records"} for ref in refs]
        return json.dumps({"state": selected, "artifacts": records}, ensure_ascii=False) if selected or records else ""

    def dump(self):
        return copy.deepcopy({"artifacts": self.artifacts, "state": self.state})

    def load(self, data):
        for i, artifact in enumerate(data["artifacts"]):
            if artifact.get("id") != f"a{i:05d}":
                raise ValueError("invalid artifact IDs/order in checkpoint")
        self.artifacts = copy.deepcopy(data["artifacts"])
        self.state = self.validate_state(data["state"])
        self.root.mkdir(parents=True, exist_ok=True)
        for a in self.artifacts:
            with (self.root / f"{a['id']}.json").open("x") as stream:
                stream.write(json.dumps(a, ensure_ascii=False, indent=2))
