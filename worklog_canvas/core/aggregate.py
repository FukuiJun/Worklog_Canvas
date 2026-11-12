"""集計（F-04）。時間はすべて「分」の整数で計算し、表示時に時間へ換算する。

- タスク別時間（メイン時間）: そのタスクがメインの作業バーの長さの合計。
- サブ時間: そのタスクがサブタスクになっている作業バーの長さの合計。メイン時間とは別に集計する。
- 稼働時間: その日に作業バーが1つ以上ある時間帯の長さ（重なりは1回だけ数える）。
  作業バーは重ならないので、メイン時間と単発作業（メイン）の合計に一致する。
- カテゴリ別時間と割合はメインだけで数える（割合の合計は100%）。

例: 10:00〜12:00 にメイン=タスクA、サブ=タスクB
    → タスクAのメイン時間 2.0h、タスクBのサブ時間 2.0h、稼働時間 2.0h
"""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from . import timeutil as tu
from .models import KIND_ONEOFF, KIND_TASK, Task, Worklog

ONEOFF_LABEL = "単発作業"
UNCATEGORIZED_LABEL = "（未分類）"


def _in_period(w: Worklog, start: _dt.date | None, end: _dt.date | None) -> bool:
    return (start is None or w.date >= start) and (end is None or w.date <= end)


def filter_period(worklogs: Iterable[Worklog], start: _dt.date | None = None,
                  end: _dt.date | None = None) -> list[Worklog]:
    return [w for w in worklogs if _in_period(w, start, end)]


def union_minutes(intervals: Iterable[tuple[int, int]]) -> int:
    """区間の和集合の長さ（重なりは1回だけ数える）。"""
    total = 0
    cur_s = cur_e = None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def working_minutes(worklogs: Iterable[Worklog]) -> int:
    """稼働時間（分）。複数日にまたがる場合は日ごとに数えて合計する。"""
    by_day: dict[_dt.date, list[tuple[int, int]]] = defaultdict(list)
    for w in worklogs:
        by_day[w.date].append((w.start, w.end))
    return sum(union_minutes(iv) for iv in by_day.values())


def minutes_by_task(worklogs: Iterable[Worklog]) -> dict[str, int]:
    """タスクid → 合計分。単発作業は含まない。"""
    out: dict[str, int] = defaultdict(int)
    for w in worklogs:
        if w.kind == KIND_TASK:
            out[w.task_id] += w.duration
    return dict(out)


def oneoff_minutes(worklogs: Iterable[Worklog]) -> int:
    """メインが単発作業の作業バーの合計分。"""
    return sum(w.duration for w in worklogs if w.kind == KIND_ONEOFF)


def sub_minutes_by_task(worklogs: Iterable[Worklog]) -> dict[str, int]:
    """タスクid → サブ時間（分）。作業バーの全時間を計上する。"""
    out: dict[str, int] = defaultdict(int)
    for w in worklogs:
        for sub in w.subs:
            if sub.kind == KIND_TASK:
                out[sub.task_id] += w.duration
    return dict(out)


def sub_oneoff_minutes(worklogs: Iterable[Worklog]) -> int:
    """サブタスクとして記録した単発作業の合計分（サブ1件ごとに作業バーの全時間）。"""
    return sum(w.duration for w in worklogs for sub in w.subs if sub.kind == KIND_ONEOFF)


def minutes_by_category(worklogs: Iterable[Worklog], tasks: Iterable[Task]) -> dict[str, int]:
    """カテゴリ名 → 合計分（メインのみ）。単発作業は「単発作業」、カテゴリ未設定は「（未分類）」。"""
    cat = {t.id: (t.category or UNCATEGORIZED_LABEL) for t in tasks}
    out: dict[str, int] = defaultdict(int)
    for w in worklogs:
        if w.kind == KIND_ONEOFF:
            out[ONEOFF_LABEL] += w.duration
        else:
            out[cat.get(w.task_id, UNCATEGORIZED_LABEL)] += w.duration
    return dict(out)


@dataclass
class DaySummary:
    date: _dt.date
    working: int = 0  # 稼働時間（分）
    by_task: dict[str, int] = field(default_factory=dict)  # タスクid → メイン時間（分）
    oneoff: int = 0  # 単発作業（メイン）の合計（分）
    by_category: dict[str, int] = field(default_factory=dict)
    sub_by_task: dict[str, int] = field(default_factory=dict)  # タスクid → サブ時間（分）
    sub_oneoff: int = 0  # 単発作業（サブ）の合計（分）

    @property
    def is_empty(self) -> bool:
        return self.working == 0


def daily_summary(worklogs: Iterable[Worklog], tasks: Iterable[Task],
                  start: _dt.date, end: _dt.date) -> list[DaySummary]:
    """start〜end の各日について集計する（作業バーが無い日も 0 で含める）。"""
    tasks = list(tasks)
    by_day: dict[_dt.date, list[Worklog]] = defaultdict(list)
    for w in filter_period(worklogs, start, end):
        by_day[w.date].append(w)
    out = []
    for d in tu.date_range(start, end):
        ws = by_day.get(d, [])
        out.append(DaySummary(
            date=d,
            working=working_minutes(ws),
            by_task=minutes_by_task(ws),
            oneoff=oneoff_minutes(ws),
            by_category=minutes_by_category(ws, tasks),
            sub_by_task=sub_minutes_by_task(ws),
            sub_oneoff=sub_oneoff_minutes(ws),
        ))
    return out


@dataclass
class PeriodSummary:
    start: _dt.date
    end: _dt.date
    working: int
    by_task: dict[str, int]
    oneoff: int
    by_category: dict[str, int]
    count: int  # 作業バー件数
    sub_by_task: dict[str, int] = field(default_factory=dict)
    sub_oneoff: int = 0

    @property
    def is_empty(self) -> bool:
        """対象期間に作業バーが0件（F-04「記録がありません」）。"""
        return self.count == 0

    def task_ranking(self) -> list[tuple[str, int]]:
        """週別の横棒グラフ用: (タスクid または「単発作業」, メイン時間の分) を降順で。"""
        rows = list(self.by_task.items())
        if self.oneoff:
            rows.append((ONEOFF_LABEL, self.oneoff))
        return sorted(rows, key=lambda x: (-x[1], x[0]))

    def category_share(self) -> list[tuple[str, int, float]]:
        """(カテゴリ, 分, 割合) を分の降順で。割合はカテゴリ合計に対する比率。"""
        total = sum(self.by_category.values())
        rows = sorted(self.by_category.items(), key=lambda x: (-x[1], x[0]))
        return [(k, v, (v / total if total else 0.0)) for k, v in rows]


def period_summary(worklogs: Iterable[Worklog], tasks: Iterable[Task],
                   start: _dt.date, end: _dt.date) -> PeriodSummary:
    ws = filter_period(worklogs, start, end)
    return PeriodSummary(
        start=start,
        end=end,
        working=working_minutes(ws),
        by_task=minutes_by_task(ws),
        oneoff=oneoff_minutes(ws),
        by_category=minutes_by_category(ws, list(tasks)),
        count=len(ws),
        sub_by_task=sub_minutes_by_task(ws),
        sub_oneoff=sub_oneoff_minutes(ws),
    )


def task_actual_minutes(worklogs: Iterable[Worklog], task_id: str, until: _dt.date | None = None) -> int:
    """タスクの実績時間（メイン時間の累計）。予定工数との比較に使う。until を指定するとその日まで。"""
    return sum(w.duration for w in worklogs
               if w.kind == KIND_TASK and w.task_id == task_id and (until is None or w.date <= until))


def task_sub_minutes(worklogs: Iterable[Worklog], task_id: str, until: _dt.date | None = None) -> int:
    """タスクのサブ時間の累計。"""
    return sum(w.duration for w in worklogs
               if (until is None or w.date <= until)
               and any(s.kind == KIND_TASK and s.task_id == task_id for s in w.subs))


def progress_on(task: Task, day: _dt.date) -> int:
    """day 終了時点の進捗率（履歴から求める）。履歴が無ければ 0。"""
    value = 0
    for e in sorted(task.history, key=lambda e: e.date):
        if e.date <= day:
            value = e.progress
        else:
            break
    return value


def remaining_days(task: Task, today: _dt.date) -> int | None:
    """完了予定日までの残り日数（当日なら0、過ぎていれば負）。未設定なら None。"""
    if task.planned_end is None:
        return None
    return (task.planned_end - today).days


def hours(minutes_map: Mapping[str, int]) -> dict[str, float]:
    return {k: v / 60 for k, v in minutes_map.items()}
