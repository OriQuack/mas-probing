"""GAIA's official answer scorer (leaderboard `scorer.py`), without
logging side effects. Scoring is a separate step from running: ground truth never enters a run directory."""

from __future__ import annotations

import re
import string


def _is_float(x) -> bool:
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def normalize_number_str(number_str: str) -> float:
    for char in ["$", "%", ","]:
        number_str = number_str.replace(char, "")
    try:
        return float(number_str)
    except ValueError:
        return float("inf")


def split_string(s: str, char_list: list[str] | None = None) -> list[str]:
    char_list = char_list or [",", ";"]
    return re.split(f"[{''.join(char_list)}]", s)


def normalize_str(input_str: str, remove_punct: bool = True) -> str:
    no_spaces = re.sub(r"\s", "", input_str)
    if remove_punct:
        return no_spaces.lower().translate(str.maketrans("", "", string.punctuation))
    return no_spaces.lower()


def question_scorer(model_answer: str | None, ground_truth: str) -> bool:
    if model_answer is None:
        return False
    model_answer = str(model_answer)
    if _is_float(ground_truth):
        return normalize_number_str(model_answer) == float(ground_truth)
    if any(char in ground_truth for char in [",", ";"]):
        gt_elems, ma_elems = split_string(ground_truth), split_string(model_answer)
        if len(gt_elems) != len(ma_elems):
            return False
        for ma, gt in zip(ma_elems, gt_elems):
            if _is_float(gt):
                if normalize_number_str(ma) != float(gt):
                    return False
            elif normalize_str(ma, remove_punct=False) != normalize_str(gt, remove_punct=False):
                return False
        return True
    return normalize_str(model_answer) == normalize_str(ground_truth)
