"""Run records: immutable reports and linked tool results, and context assembled from report IDs (offline)."""
import json
import pytest
from minpilot.records import Records
from minpilot.runtime.trace import Trace


def test_context_contains_selected_reports_in_full(tmp_path):
    records = Records(tmp_path / "artifacts", Trace(None))
    records.add("orchestrator", "instruction", "Count orders.")
    first = records.add("gen_luna", "execution", "FULL REPORT", status="tool_limit")
    second = records.add("gen_haiku", "probe", "plan: read")
    text = records.context([first["id"], second["id"], first["id"]], label={"gen_luna": "worker_1", "gen_haiku": "worker_2"}.get)
    assert text == ("Report a00001 from worker_1 (execution request, status tool_limit):\nFULL REPORT\n\n"
                    "Report a00002 from worker_2 (probe request, status ok):\nplan: read")
    assert records.context([]) == ""
    for invalid in [["a00000"], ["t00000"], ["missing"], "a00001", [1]]:
        with pytest.raises(ValueError):
            records.context(invalid)


def test_artifacts_cannot_be_overwritten_and_invalid_ids_cannot_restore(tmp_path):
    records = Records(tmp_path / "artifacts", Trace(None))
    records.add("worker", "execution", "ORIGINAL")
    other = Records(tmp_path / "artifacts", Trace(None))
    with pytest.raises(FileExistsError):
        other.add("worker", "execution", "REPLACEMENT")
    assert "ORIGINAL" in (tmp_path / "artifacts/a00000.json").read_text()
    with pytest.raises(ValueError, match="invalid artifact"):
        records.load({"artifacts": [{"id": "../../escape"}], "tool_artifacts": []})


def test_tool_records_link_to_reports_and_restore(tmp_path):
    records = Records(tmp_path / "original", Trace(None))
    report = records.add("worker", "execution", "Partial finding", status="tool_limit",
                         messages=[{"role": "tool", "tool_call_id": "call-1", "content": "SOURCE TEXT"}])
    tool_id = report["tool_ids"][0]
    assert records.catalog()[0]["tool_ids"] == [tool_id]
    assert "SOURCE TEXT" not in json.dumps(records.catalog())
    tool = records.read(tool_id)
    assert tool["body"] == "SOURCE TEXT" and tool["parent_id"] == report["id"]
    assert tool["report_status"] == "tool_limit" and tool["tool_call_id"] == "call-1"
    tool["body"] = "MUTATED"
    assert records.read(tool_id)["body"] == "SOURCE TEXT"
    restored = Records(tmp_path / "restored", Trace(None))
    restored.load(records.dump())
    assert restored.dump() == records.dump()
    next_report = restored.add("other", "probe", "Plan", messages=[{"role": "tool", "content": "NEXT SOURCE"}])
    assert next_report["tool_ids"] == ["t00001"]
    with pytest.raises(ValueError, match="unknown record ID"):
        restored.read(f"{report['id']}/tool/0")
    invalid = records.dump()
    invalid["tool_artifacts"][0]["parent_id"] = "a99999"
    with pytest.raises(ValueError, match="invalid tool IDs/links"):
        Records(tmp_path / "invalid", Trace(None)).load(invalid)


def test_tool_record_preserves_call_arguments_and_original_result(tmp_path):
    records = Records(tmp_path / "artifacts", Trace(None))
    arguments = '{"code": "print(sum([2, 4, 6]))"}'
    report = records.add("worker", "execution", "12", messages=[
        {"role": "assistant", "tool_calls": [{"id": "call-1", "function": {
            "name": "run_python", "arguments": arguments}}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "12"},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "image payload"}}]},
    ])
    record = records.read(report["tool_ids"][0])
    assert record["name"] == "run_python" and record["arguments"] == arguments
    assert record["body"] == "12" and record["content"] == "12"
    assert "image payload" not in json.dumps(record)
    restored = Records(tmp_path / "restored", Trace(None))
    restored.load(records.dump())
    assert restored.read(record["id"]) == record
