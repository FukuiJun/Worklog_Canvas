"""作業バーの表示色（F-02）。"""
from __future__ import annotations

from typing import Mapping

from .models import KIND_ONEOFF, Task, Worklog

ONEOFF_COLOR = "#9E9E9E"  # 単発作業（灰色）
# カテゴリ未設定（またはカテゴリが categories.json に無い）タスクの色。
# 単発作業の灰色・既定のカテゴリ色8色のいずれとも、色覚の違いを含めて見分けられる濃い茶色
# （色の検証スクリプトで確認済み）。
UNCATEGORIZED_COLOR = "#6D4C41"

# 新しいカテゴリに提案する色（この順に、まだ使われていない色を選ぶ）。
# 隣り合う色が色覚の違いがあっても見分けられることを検証済みの8色。
CATEGORY_PALETTE = ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#E34948"]


def next_category_color(used: set[str]) -> str:
    used_upper = {c.upper() for c in used}
    for c in CATEGORY_PALETTE:
        if c not in used_upper:
            return c
    return CATEGORY_PALETTE[len(used) % len(CATEGORY_PALETTE)]


def task_color(task: Task | None, category_colors: Mapping[str, str]) -> str:
    if task is None or not task.category:
        return UNCATEGORIZED_COLOR
    return category_colors.get(task.category, UNCATEGORIZED_COLOR)


def worklog_color(w: Worklog, tasks_by_id: Mapping[str, Task], category_colors: Mapping[str, str]) -> str:
    """作業バーの色はメインで決める（メインが単発作業なら灰色）。"""
    if w.kind == KIND_ONEOFF:
        return ONEOFF_COLOR
    return task_color(tasks_by_id.get(w.task_id), category_colors)
