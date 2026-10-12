"""CLI rejection paths must stop before any data/model/web execution."""
import subprocess
import sys
import json
import pytest
from minpilot.tools.config import REPO_ROOT


@pytest.mark.parametrize("script,args", [
    ("run_task.py", ["fresh", "--task-id", "fake", "--refiner", "baseline"]),
    ("run_task.py", ["fresh", "--task-id", "fake", "--condition", "self_review"]),
    ("run_task.py", ["fresh", "--task-id", "fake", "--refine-at", "first"]),
    ("run_batch.py", ["--tasks", "nonexistent.csv", "--refiners", "baseline"]),
])
def test_retired_flags_and_modes_rejected(script, args):
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / script), *args], capture_output=True, text=True)
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr or "invalid choice" in result.stderr


def test_old_checkpoint_cli_rejected_before_service_or_dataset(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"format": 1}))
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts/run_task.py"), "restore", "--checkpoint", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 2 and "historical checkpoint" in result.stderr
