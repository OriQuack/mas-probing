"""GAIA task loading and the pilot's pre-registered scope rule.

This module never exposes ground truth: `Final answer` and `Annotator Metadata` are dropped on load.
Scoring code reads answers separately (see eval/), so nothing built from `GaiaTask` can leak them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

GAIA_ROOT = Path.home() / "data2/datasets/GAIA/2023"
HIDDEN_COLUMNS = ("Final answer", "Annotator Metadata")

# Scope rule (pre-registered in the previous pilot; data/splits/task_scope.csv): exclude audio/video tasks, judged
# only from observable inputs (attachment extension, question text), never from Annotator Metadata. min_pilot has
# no audio/video tools either, so the rule and the splits carry over unchanged.
AV_EXTENSIONS = frozenset({"mp3", "wav", "m4a", "flac", "ogg", "mp4", "mov", "avi", "mkv", "webm"})
VIDEO_QUESTION_RE = re.compile(r"youtube|youtu\.be|\bvideos?\b(?!\s*games?)", re.IGNORECASE)


# GAIA's answer rules (from the GAIA paper's system prompt). The harness passes them to the orchestrator: they belong
# to the benchmark, not to the framework (a port to another benchmark passes that benchmark's rules).
ANSWER_FORMAT = (
    "The final answer should be a number OR as few words as possible OR a comma separated list of numbers and/or "
    "strings. If you are asked for a number, don't use commas to write your number, nor units such as $ or "
    "percent sign unless specified otherwise. If you are asked for a string, don't use articles nor abbreviations "
    "(e.g. for cities), and write digits in plain text unless specified otherwise. If you are asked for a comma "
    "separated list, apply the above rules depending on whether each element is a number or a string.")


@dataclass(frozen=True)
class GaiaTask:
    task_id: str
    level: int
    question: str
    file_name: str | None
    file_path: Path | None

    @property
    def file_ext(self) -> str | None:
        return Path(self.file_name).suffix.lstrip(".").lower() if self.file_name else None


def load_tasks(split: str = "validation", root: Path = GAIA_ROOT) -> list[GaiaTask]:
    df = pd.read_parquet(root / split / "metadata.parquet").drop(columns=list(HIDDEN_COLUMNS))
    tasks = []
    for row in df.itertuples(index=False):
        file_name = row.file_name or None
        tasks.append(
            GaiaTask(
                task_id=row.task_id,
                level=int(row.Level),
                question=row.Question,
                file_name=file_name,
                file_path=root / split / file_name if file_name else None,
            )
        )
    return tasks


def exclusion_reason(task: GaiaTask) -> str | None:
    """Return why a task is out of pilot scope, or None if it is in scope."""
    if task.file_ext in AV_EXTENSIONS:
        return f"av_attachment:{task.file_ext}"
    if m := VIDEO_QUESTION_RE.search(task.question):
        return f"video_question:{m.group(0).lower()}"
    return None


def load_task(task_id: str, split: str = "validation", root: Path = GAIA_ROOT) -> GaiaTask:
    for t in load_tasks(split, root):
        if t.task_id == task_id:
            return t
    raise KeyError(f"task {task_id} not in GAIA {split}")
