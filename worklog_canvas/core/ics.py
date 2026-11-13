"""予定表ファイル（.ics）の読み込み（仕様 5.3、F-05）。

- 件名（SUMMARY）、開始（DTSTART）、終了（DTEND）、終日かどうかを取り出す。
- 繰り返し予定（RRULE、EXDATE）は、表示中の週の分に展開する。
- 日時はPCのタイムゾーン（日本時間）に変換する。タイムゾーンのない日時はPCの時刻として扱う。
- ファイル全体が読めなければ IcsFormatError。一部の予定が読めなければ、その予定を飛ばして件数を返す。
- 予定の件名は個人の予定なので、ログには出さない。
"""
from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import timeutil as tu
from .models import KIND_ONEOFF, ONEOFF_TITLE_MAX, SOURCE_OUTLOOK, Worklog

FORMAT_ERROR_MESSAGE = "予定表ファイルを読み取れませんでした"
NOT_FOUND_MESSAGE = "予定表ファイルが見つかりません"
EMPTY_WEEK_MESSAGE = "この週の予定はファイルにありません"
UNTITLED = "（件名なし）"


class IcsFormatError(ValueError):
    def __init__(self, detail: str = ""):
        super().__init__(FORMAT_ERROR_MESSAGE)
        self.detail = detail


@dataclass(frozen=True)
class Appointment:
    """予定（予定バー）。start/end はPCの時刻（タイムゾーンなし）。終日の予定は date の範囲（end は含まない）。"""
    title: str
    start: _dt.datetime
    end: _dt.datetime
    all_day: bool

    def days(self) -> list[_dt.date]:
        """予定がかかる日（終了は含まない）。"""
        if self.all_day:
            last = self.end.date() - _dt.timedelta(days=1)
        else:
            last = (self.end - _dt.timedelta(microseconds=1)).date()
        return tu.date_range(self.start.date(), max(last, self.start.date()))

    def span_on(self, day: _dt.date) -> tuple[int, int] | None:
        """その日の中での時間帯（分）。終日の予定は None。"""
        if self.all_day:
            return None
        day_start = _dt.datetime.combine(day, _dt.time(0))
        s = max(self.start, day_start)
        e = min(self.end, day_start + _dt.timedelta(days=1))
        if e <= s:
            return None
        to_min = lambda t: int((t - day_start).total_seconds() // 60)  # noqa: E731
        return to_min(s), to_min(e)


@dataclass
class WeekAppointments:
    appointments: list[Appointment]
    skipped: int  # 読み飛ばした予定の件数


def local_tz() -> _dt.tzinfo:
    return _dt.datetime.now().astimezone().tzinfo


class IcsFile:
    """読み込んだ予定表ファイル。週を切り替えたときは、同じ内容から展開し直す。"""

    def __init__(self, path: str | os.PathLike, tz: _dt.tzinfo | None = None):
        self.path = Path(path)
        self.tz = tz or local_tz()
        raw = self.path.read_bytes()  # 見つからなければ FileNotFoundError
        self.mtime = self.path.stat().st_mtime
        self._parse(raw)

    def _parse(self, raw: bytes) -> None:
        import icalendar
        try:
            cal = icalendar.Calendar.from_ical(raw)
        except Exception as e:  # noqa: BLE001  ライブラリは様々な例外を投げる
            raise IcsFormatError(type(e).__name__) from e
        if getattr(cal, "name", "") != "VCALENDAR":
            raise IcsFormatError("VCALENDAR がありません")
        self._timezones = [c for c in cal.subcomponents if c.name == "VTIMEZONE"]
        self.bad_events = 0
        groups: dict[str, list] = {}
        for i, ev in enumerate(c for c in cal.subcomponents if c.name == "VEVENT"):
            if not self._valid(ev):
                self.bad_events += 1
                continue
            uid = str(ev.get("UID") or f"__no_uid_{i}")
            groups.setdefault(uid, []).append(ev)
        self._groups = groups
        self._calendar = self._make_calendar(ev for g in groups.values() for ev in g)

    @staticmethod
    def _valid(ev) -> bool:
        if ev.errors:
            return False
        try:
            start = ev.decoded("DTSTART")
            if "DTEND" in ev:
                ev.decoded("DTEND")
            if "DURATION" in ev:
                ev.decoded("DURATION")
            if "RRULE" in ev:
                ev.get("RRULE").to_ical()
        except (KeyError, ValueError, TypeError, AttributeError):
            return False
        return isinstance(start, (_dt.date, _dt.datetime))

    def _make_calendar(self, events: Iterable):
        import icalendar
        cal = icalendar.Calendar()
        cal.add("PRODID", "-//Worklog Canvas//JA")
        cal.add("VERSION", "2.0")
        for tz in self._timezones:
            cal.add_component(tz)
        for ev in events:
            cal.add_component(ev)
        return cal

    def week(self, week_start: _dt.date) -> WeekAppointments:
        """表示中の週（月〜日）にかかる予定。繰り返しは展開済み。"""
        start = week_start
        end = week_start + _dt.timedelta(days=7)
        skipped = self.bad_events
        try:
            occurrences = list(self._between(self._calendar, start, end))
        except Exception:  # noqa: BLE001  どの予定が原因か分からないので、UIDごとに展開し直す
            occurrences = []
            for events in self._groups.values():
                try:
                    occurrences += list(self._between(self._make_calendar(events), start, end))
                except Exception:  # noqa: BLE001
                    skipped += 1
        out = []
        for occ in occurrences:
            try:
                a = self._to_appointment(occ)
            except (KeyError, ValueError, TypeError, AttributeError):
                skipped += 1
                continue
            if a is not None and a.start.date() < end and (a.end.date() >= start):
                out.append(a)
        out.sort(key=lambda a: (a.start, a.end, a.title))
        return WeekAppointments(out, skipped)

    @staticmethod
    def _between(cal, start: _dt.date, end: _dt.date):
        import recurring_ical_events
        return recurring_ical_events.of(cal).between(start, end)

    def _local(self, value) -> _dt.datetime:
        if isinstance(value, _dt.datetime):
            if value.tzinfo is None:  # タイムゾーンのない日時はPCの時刻
                return value
            return value.astimezone(self.tz).replace(tzinfo=None)
        return _dt.datetime.combine(value, _dt.time(0))

    def _to_appointment(self, ev) -> Appointment | None:
        start = ev.decoded("DTSTART")
        all_day = not isinstance(start, _dt.datetime)
        if "DTEND" in ev:
            end = ev.decoded("DTEND")
        elif "DURATION" in ev:
            end = start + ev.decoded("DURATION")
        else:
            end = start + _dt.timedelta(days=1) if all_day else start
        title = str(ev.get("SUMMARY") or "").strip() or UNTITLED
        s, e = self._local(start), self._local(end)
        if e < s:
            return None
        if all_day and e <= s:
            e = s + _dt.timedelta(days=1)
        return Appointment(title, s, e, all_day)


def to_worklog(a: Appointment, day: _dt.date) -> Worklog:
    """予定バーを作業バーにする（F-05）。15分刻みでない時刻は最も近い15分に丸める。

    初期値は 種別=単発作業、タイトル=件名、取込元=Outlook。
    """
    span = a.span_on(day)
    if span is None:
        raise ValueError("終日の予定は作業バーにできません")
    s = tu.snap_minutes(span[0])
    e = tu.snap_minutes(span[1])
    s = min(max(s, 0), tu.DAY_MINUTES - tu.MIN_DURATION_MINUTES)
    e = min(max(e, s + tu.MIN_DURATION_MINUTES), tu.DAY_MINUTES)
    return Worklog("", day, s, e, kind=KIND_ONEOFF, title=a.title[:ONEOFF_TITLE_MAX], source=SOURCE_OUTLOOK)
