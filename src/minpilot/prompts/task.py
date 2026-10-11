"""Task prompts: complete message bodies live beside their input preparation."""

from __future__ import annotations


def original_task_text(question: str, attachment: str | None, reference_date: str | None = None) -> str:
    """The task as every model sees it. `reference_date` (YYYY-MM-DD) is fixed when a run starts and kept by its
    checkpoints, so every condition restored from one sees the same date."""
    text = question if not attachment else f"{question}\n\nAttached file: {attachment}"
    if reference_date:
        text += f"""

Run date: {reference_date} (the day this run takes place). The task may have been written earlier: do not take the run date as the task's time reference, and do not filter data or choose sources by it; take the time frame from the task itself."""
    return text
