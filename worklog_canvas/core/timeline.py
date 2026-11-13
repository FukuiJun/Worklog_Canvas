"""タイムライン操作の計算（F-02）。画面の座標計算とは分け、分単位で扱う。"""
from __future__ import annotations

import copy
import datetime as _dt
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

from . import timeutil as tu
from .models import (
    KIND_ONEOFF, KIND_TASK, PRIORITIES, STATUS_IN_PROGRESS, STATUS_NOT_STARTED, STATUS_ON_HOLD,
    SubItem, Task, Worklog,
)

DROP_DEFAULT_MINUTES = 60
MIN = tu.MIN_DURATION_MINUTES


def floor15(minutes: float) -> int:
    return int(minutes // tu.SNAP_MINUTES) * tu.SNAP_MINUTES


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


# --- ドラッグでの作成・伸縮・移動 -------------------------------------------
def create_range(a: float, b: float) -> tuple[int, int] | None:
    """ドラッグの始点・終点（分）から作業バーの範囲を求める。15分未満なら None。"""
    s, e = sorted((tu.snap_minutes(a), tu.snap_minutes(b)))
    s, e = clamp(s, 0, tu.DAY_MINUTES), clamp(e, 0, tu.DAY_MINUTES)
    if e - s < MIN:
        return None
    return s, e


def resized_top(w: Worklog, minutes: float) -> Worklog:
    start = clamp(tu.snap_minutes(minutes), 0, w.end - MIN)
    return replace(w, start=start, subs=copy.deepcopy(w.subs))


def resized_bottom(w: Worklog, minutes: float) -> Worklog:
    end = clamp(tu.snap_minutes(minutes), w.start + MIN, tu.DAY_MINUTES)
    return replace(w, end=end, subs=copy.deepcopy(w.subs))


def moved(w: Worklog, date: _dt.date, start_minutes: float) -> Worklog:
    """長さを保ったまま移動する。start_minutes は移動先の開始時刻（吸着前）。"""
    d = w.duration
    start = clamp(tu.snap_minutes(start_minutes), 0, tu.DAY_MINUTES - d)
    return replace(w, date=date, start=start, end=start + d, subs=copy.deepcopy(w.subs))


# --- タスク一覧パネルからのドロップ ----------------------------------------
@dataclass(frozen=True)
class DropOnBar:
    worklog_id: str


@dataclass(frozen=True)
class DropCreate:
    start: int
    end: int


def bar_at(worklogs: Iterable[Worklog], minutes: float) -> Worklog | None:
    for w in worklogs:
        if w.start <= minutes < w.end:
            return w
    return None


def resolve_drop(day_worklogs: Sequence[Worklog], minutes: float,
                 default: int = DROP_DEFAULT_MINUTES) -> DropOnBar | DropCreate | None:
    """ドロップ位置（分、吸着前）から動作を決める。

    - 既存の作業バーの上 → そのバーのサブタスクに追加（Q-11）
    - 空き領域 → ドロップ位置から default 分。後ろのバーまで足りなければその手前まで（Q-12）
    - 15分未満しか空いていなければ None
    """
    hit = bar_at(day_worklogs, minutes)
    if hit is not None:
        return DropOnBar(hit.id)
    start = tu.snap_minutes(minutes)
    if start >= tu.DAY_MINUTES or bar_at(day_worklogs, start) is not None or \
            any(minutes < w.start <= start for w in day_worklogs):
        start = floor15(minutes)  # 吸着で次のバーに入る場合は手前に寄せる
    start = clamp(start, 0, tu.DAY_MINUTES - MIN)
    limit = min([w.start for w in day_worklogs if w.start >= start] + [tu.DAY_MINUTES])
    end = min(start + default, limit)
    if end - start < MIN:
        return None
    return DropCreate(start, end)


def with_sub(w: Worklog, sub: SubItem) -> Worklog:
    """サブタスクを追加した作業バー（検証は呼び出し側で validate する）。"""
    return replace(w, subs=copy.deepcopy(w.subs) + [copy.deepcopy(sub)])


# --- 入力ポップアップの候補 ------------------------------------------------
_STATUS_ORDER = {STATUS_IN_PROGRESS: 0, STATUS_NOT_STARTED: 1, STATUS_ON_HOLD: 2}


def sort_open_tasks(tasks: Iterable[Task]) -> list[Task]:
    """未完了タスクを 進行中→未着手→保留、優先度 高→中→低、id 順で並べる。"""
    return sorted((t for t in tasks if t.is_open),
                  key=lambda t: (_STATUS_ORDER.get(t.status, 9), PRIORITIES.index(t.priority), t.id))


def filter_tasks(tasks: Iterable[Task], text: str) -> list[Task]:
    """タスク名（またはカテゴリ名）に入力文字を含むものに絞り込む。大文字小文字・前後の空白は無視。"""
    q = text.strip().casefold()
    if not q:
        return list(tasks)
    return [t for t in tasks if q in t.name.casefold() or q in t.category.casefold()]


# --- 表示 ------------------------------------------------------------------
def item_label(kind: str, task_id: str | None, title: str, tasks_by_id: dict[str, Task]) -> str:
    if kind == KIND_ONEOFF:
        return title
    t = tasks_by_id.get(task_id)
    return t.name if t else f"（不明なタスク {task_id}）"


def main_label(w: Worklog, tasks_by_id: dict[str, Task]) -> str:
    return item_label(w.kind, w.task_id, w.title, tasks_by_id)


def sub_labels(w: Worklog, tasks_by_id: dict[str, Task]) -> list[str]:
    return [item_label(s.kind, s.task_id, s.title, tasks_by_id) for s in w.subs]


def visible_dates(anchor: _dt.date, mode: str) -> list[_dt.date]:
    """mode="day" なら anchor の1日、"week" なら anchor を含む月〜日。"""
    if mode == "day":
        return [anchor]
    start = tu.week_start(anchor)
    return tu.date_range(start, start + _dt.timedelta(days=6))


def step_anchor(anchor: _dt.date, mode: str, direction: int) -> _dt.date:
    return anchor + _dt.timedelta(days=direction * (1 if mode == "day" else 7))
