"""作業バーの表示色（F-02）。"""
from __future__ import annotations

from typing import Mapping

from .models import KIND_ONEOFF, Task, Worklog

ONEOFF_COLOR = "#9E9E9E"  # 単発作業（灰色）
# カテゴリ未設定（またはカテゴリが categories.json に無い）タスクの色。
# 単発作業の灰色と区別でき、かつカテゴリ色と紛れにくい落ち着いた茶色。
UNCATEGORIZED_COLOR = "#8D6E63"


def task_color(task: Task | None, category_colors: Mapping[str, str]) -> str:
    if task is None or not task.category:
        return UNCATEGORIZED_COLOR
    return category_colors.get(task.category, UNCATEGORIZED_COLOR)


def worklog_color(w: Worklog, tasks_by_id: Mapping[str, Task], category_colors: Mapping[str, str]) -> str:
    """作業バーの色はメインで決める（メインが単発作業なら灰色）。"""
    if w.kind == KIND_ONEOFF:
        return ONEOFF_COLOR
    return task_color(tasks_by_id.get(w.task_id), category_colors)
