"""Canonical evidence discovery must not count copies inside workspaces or analysis bundles."""

import json

import pytest

from minpilot.artifacts import find_run_records, migrate_path, resolve_artifact_path


def record(root, relative):
    path = root / relative / "run.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    return path


def test_manifest_discovers_nested_batches_but_ignores_trace_copies(tmp_path):
    original = record(tmp_path, "base/runs/task/run")
    restored = record(tmp_path, "restore/runs/task/run")
    record(tmp_path, "base/runs/task/run/work/snapshot/task/run")
    record(tmp_path, "analysis/selected-traces/raw/task/run")
    (tmp_path / "manifest.json").write_text(json.dumps({"run_roots": ["base/runs", "restore/runs"]}))
    assert find_run_records(tmp_path) == [original, restored]
    assert find_run_records(original.parent) == [original]
    assert find_run_records(tmp_path / "base/runs") == [original]


def test_manifest_cannot_read_outside_experiment(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"run_roots": ["../outside"]}))
    with pytest.raises(ValueError, match="escapes"):
        find_run_records(tmp_path)


def test_historical_checkpoint_paths_resolve_without_rewriting_records(tmp_path):
    old = tmp_path / "old-experiment"
    new = tmp_path / "named-experiment"
    checkpoint = new / "runs/task/run/checkpoints/d0"
    checkpoint.mkdir(parents=True)
    saved = old / "runs/task/run/checkpoints/d0"
    assert resolve_artifact_path(saved, {str(old): str(new)}) == checkpoint
    assert not old.exists()


def test_stored_path_migrates_even_when_a_new_file_took_its_name(tmp_path):
    reused = tmp_path / "decisions.md"
    reused.write_text("current decisions")
    moved = tmp_path / "history/decisions.md"
    mapping = {str(reused): str(moved)}
    assert migrate_path(reused, mapping) == moved
    assert resolve_artifact_path(reused, mapping) == reused
    assert migrate_path(tmp_path / "unrelated.md", mapping) is None


def test_batch_refuses_to_append_to_frozen_evidence_before_writing(tmp_path, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/run_batch.py"
    spec = importlib.util.spec_from_file_location("batch_for_artifact_test", script)
    batch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batch)
    tasks = tmp_path / "tasks.csv"
    tasks.write_text("task_id\nexample-task\n")
    experiment = tmp_path / "frozen"
    experiment.mkdir()
    manifest = experiment / "manifest.json"
    manifest.write_text(json.dumps({"historical_records_immutable": True}))
    before = manifest.read_bytes()
    monkeypatch.setattr(sys, "argv", [str(script), "--tasks", str(tasks), "--experiment", str(experiment)])
    with pytest.raises(ValueError, match="immutable"):
        batch.main()
    assert manifest.read_bytes() == before
    assert not (experiment / "planned.csv").exists()
