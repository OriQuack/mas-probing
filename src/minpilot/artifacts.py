"""Experiment manifests and canonical run discovery.

Never recursively collect run.json: workspaces and rendered trace bundles can contain copied run records.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _path_migrations() -> dict[str, str]:
    record = REPO / "docs/reports/retention.json"
    return json.loads(record.read_text())["path_migrations"] if record.exists() else {}


def resolve_artifact_path(value: Path | str, migrations: dict[str, str] | None = None) -> Path:
    """Locate moved evidence without rewriting paths inside immutable historical records."""
    path = Path(value).resolve()
    if path.exists():
        return path
    key = str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)
    mapping = _path_migrations() if migrations is None else migrations
    for old, new in sorted(mapping.items(), key=lambda item: -len(item[0])):
        if key == old or key.startswith(old + "/"):
            return (REPO / (new + key[len(old):])).resolve()
    return path


def find_run_records(path: Path | str) -> list[Path]:
    """Accept a run, runs root, experiment manifest directory, or collection of experiments."""
    path = Path(path)
    if not path.is_dir():
        raise ValueError(f"run or experiment directory does not exist: {path}")
    if (path / "run.json").is_file():
        return [path / "run.json"]
    manifest = path / "manifest.json"
    if manifest.is_file():
        roots = json.loads(manifest.read_text())["run_roots"]
        records = []
        for name in roots:
            run_root = (path / name).resolve()
            if not run_root.is_relative_to(path.resolve()):
                raise ValueError(f"run root escapes experiment: {name}")
            records.extend(run_root.glob("*/*/run.json"))
        return sorted(set(records))
    direct = sorted(path.glob("*/*/run.json"))
    if direct:
        return direct
    if (path / "runs").is_dir():
        return find_run_records(path / "runs")
    records = []
    for child in sorted(path.iterdir()):
        if child.is_dir() and (child / "manifest.json").is_file():
            records.extend(find_run_records(child))
    return sorted(set(records))


def experiment_manifest(*, purpose: str, run_roots: list[str], **metadata) -> dict:
    return {"schema_version": 1, "purpose": purpose, "run_roots": run_roots, **metadata}
