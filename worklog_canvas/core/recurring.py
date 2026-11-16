"""定期タスク（決まった時間の作業の繰り返し、F-09）。

例: 毎週月曜 9:00〜9:30 の朝会。登録しておくと、該当する日のタイムラインに「定期の予定」として
淡く表示する。作業バー（実績）にはならず、利用者が確定したときだけ作業バーとして記録する
（休んだ日に実績が勝手に残らないように）。

繰り返し方:
- 平日毎日: 月〜金
- 毎週: 選んだ曜日
- 隔週: 選んだ曜日を2週に1回（開始日の週から数える）
- 毎月: 選んだ日にち（その月にない日は月末。例: 31日 → 2月は28日か29日）
"""
from __future__ import annotations

import calendar
import datetime as _dt
from dataclasses import dataclass, field
from typing import Iterable

from . import timeutil as tu
from .models import (
    KIND_ONEOFF, KIND_TASK, ONEOFF_TITLE_MAX, SOURCE_RECURRING, ValidationError, Worklog,
    _validate_item,
)

DAILY_WEEKDAYS = "平日毎日"
WEEKLY = "毎週"
BIWEEKLY = "隔週"
MONTHLY = "毎月"
PATTERNS = (DAILY_WEEKDAYS, WEEKLY, BIWEEKLY, MONTHLY)
WEEKDAY_NAMES = "月火水木金土日"


@dataclass
class RecurringItem:
    id: str
    start: int  # 0:00 からの経過分
    end: int
    pattern: str = WEEKLY
    kind: str = KIND_TASK
    task_id: str | None = None
    title: str = ""
    weekdays: list[int] = field(default_factory=list)  # 0=月 … 6=日（毎週・隔週）
    month_day: int = 1  # 毎月の日にち（1〜31）
    start_date: _dt.date = field(default_factory=_dt.date.today)
    end_date: _dt.date | None = None
    memo: str = ""

    @property
    def duration(self) -> int:
        return self.end - self.start

    def validate(self) -> None:
        if self.start % tu.SNAP_MINUTES or self.end % tu.SNAP_MINUTES:
            raise ValidationError("時刻", "時刻は15分刻みで指定してください")
        if not (0 <= self.start < self.end <= tu.DAY_MINUTES):
            raise ValidationError("時刻", "終了時刻は開始時刻より後にしてください")
        _validate_item(self.kind, self.task_id, self.title, "")
        if self.pattern not in PATTERNS:
            raise ValidationError("繰り返し", f"繰り返しの指定が不正です: {self.pattern}")
        if self.pattern in (WEEKLY, BIWEEKLY):
            if not self.weekdays:
                raise ValidationError("曜日", "曜日を1つ以上選んでください")
            if any(not (0 <= d <= 6) for d in self.weekdays):
                raise ValidationError("曜日", "曜日の指定が不正です")
        if self.pattern == MONTHLY and not (1 <= self.month_day <= 31):
            raise ValidationError("日にち", "日にちは1〜31で指定してください")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValidationError("終了日", "終了日は開始日より後にしてください")

    def occurs_on(self, day: _dt.date) -> bool:
        if day < self.start_date or (self.end_date is not None and day > self.end_date):
            return False
        if self.pattern == DAILY_WEEKDAYS:
            return day.weekday() < 5
        if self.pattern == WEEKLY:
            return day.weekday() in self.weekdays
        if self.pattern == BIWEEKLY:
            weeks = (tu.week_start(day) - tu.week_start(self.start_date)).days // 7
            return day.weekday() in self.weekdays and weeks % 2 == 0
        if self.pattern == MONTHLY:
            last = calendar.monthrange(day.year, day.month)[1]
            return day.day == min(self.month_day, last)
        return False

    def describe(self) -> str:
        """一覧に出す説明（例: 毎週 月・木 9:00〜9:30）。"""
        time = f"{tu.format_hhmm(self.start)}〜{tu.format_hhmm(self.end)}"
        if self.pattern in (WEEKLY, BIWEEKLY):
            days = "・".join(WEEKDAY_NAMES[d] for d in sorted(self.weekdays))
            return f"{self.pattern} {days} {time}"
        if self.pattern == MONTHLY:
            return f"毎月 {self.month_day}日 {time}"
        return f"{self.pattern} {time}"

    def to_worklog(self, day: _dt.date) -> Worklog:
        """その日の作業バーにする（取込元=定期）。"""
        return Worklog("", day, self.start, self.end, kind=self.kind,
                       task_id=self.task_id if self.kind == KIND_TASK else None,
                       title=self.title if self.kind == KIND_ONEOFF else "",
                       memo=self.memo, source=SOURCE_RECURRING)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "種別": self.kind,
            "タスクid": self.task_id if self.kind == KIND_TASK else None,
            "タイトル": self.title if self.kind == KIND_ONEOFF else "",
            "開始時刻": tu.format_hhmm(self.start),
            "終了時刻": tu.format_hhmm(self.end),
            "繰り返し": self.pattern,
            "曜日": sorted(self.weekdays),
            "日にち": self.month_day,
            "開始日": self.start_date.isoformat(),
            "終了日": tu.format_date(self.end_date),
            "メモ": self.memo,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RecurringItem":
        return cls(
            id=d["id"],
            start=tu.parse_hhmm(d["開始時刻"]),
            end=tu.parse_hhmm(d["終了時刻"]),
            pattern=d.get("繰り返し", WEEKLY),
            kind=d.get("種別", KIND_TASK),
            task_id=d.get("タスクid"),
            title=d.get("タイトル") or "",
            weekdays=[int(x) for x in d.get("曜日", [])],
            month_day=int(d.get("日にち", 1)),
            start_date=_dt.date.fromisoformat(d["開始日"]),
            end_date=tu.parse_date(d.get("終了日")),
            memo=d.get("メモ") or "",
        )


@dataclass(frozen=True)
class Occurrence:
    """ある日の定期の予定。"""
    item: RecurringItem
    date: _dt.date

    @property
    def start(self) -> int:
        return self.item.start

    @property
    def end(self) -> int:
        return self.item.end


def occurrences(items: Iterable[RecurringItem], dates: Iterable[_dt.date],
                worklogs: Iterable[Worklog] = ()) -> list[Occurrence]:
    """dates の各日の定期の予定。その時間帯に作業バーが既にある回は出さない（記録済み、または別の作業）。"""
    by_day: dict[_dt.date, list[Worklog]] = {}
    for w in worklogs:
        by_day.setdefault(w.date, []).append(w)
    out = []
    for d in dates:
        bars = by_day.get(d, [])
        for it in items:
            if it.occurs_on(d) and not any(w.start < it.end and it.start < w.end for w in bars):
                out.append(Occurrence(it, d))
    out.sort(key=lambda o: (o.date, o.start, o.item.id))
    return out


def convert_task_to_oneoff(items: Iterable[RecurringItem], task_id: str, task_name: str) -> int:
    """タスクを削除したとき、それを使う定期タスクを単発作業に変える（作業バーと同じ扱い）。"""
    n = 0
    for it in items:
        if it.kind == KIND_TASK and it.task_id == task_id:
            it.kind, it.task_id, it.title = KIND_ONEOFF, None, task_name[:ONEOFF_TITLE_MAX]
            n += 1
    return n

