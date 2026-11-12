"""時刻・日付の変換と15分吸着（F-02）。

時刻は内部では「0:00 からの経過分（int）」で扱い、JSONには "HH:MM" で保存する。
"""
from __future__ import annotations

import datetime as _dt
import math

SNAP_MINUTES = 15
MIN_DURATION_MINUTES = 15
DAY_MINUTES = 24 * 60


def snap_minutes(minutes: float, step: int = SNAP_MINUTES) -> int:
    """分を最も近い step 分に吸着する。ちょうど中間（7.5分など）は切り上げる。

    >>> snap_minutes(7), snap_minutes(8)
    (0, 15)
    """
    return int(math.floor(minutes / step + 0.5)) * step


def snap_time(t: _dt.time | str, step: int = SNAP_MINUTES) -> int:
    """時刻を吸着して経過分で返す。"""
    if isinstance(t, str):
        m = parse_hhmm(t)
    else:
        m = t.hour * 60 + t.minute + t.second / 60
    return snap_minutes(m, step)


def parse_hhmm(text: str) -> int:
    """"HH:MM" を経過分に変換する。"24:00" は 1440 として受け付ける。"""
    try:
        hh, mm = text.split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError) as e:
        raise ValueError(f"時刻の形式が不正です: {text!r}") from e
    if not (0 <= m < 60) or not (0 <= h <= 24) or (h == 24 and m != 0):
        raise ValueError(f"時刻の範囲が不正です: {text!r}")
    return h * 60 + m


def format_hhmm(minutes: int) -> str:
    if not (0 <= minutes <= DAY_MINUTES):
        raise ValueError(f"時刻の範囲が不正です: {minutes}")
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_date(text: str | None) -> _dt.date | None:
    if text in (None, ""):
        return None
    return _dt.date.fromisoformat(text)


def format_date(d: _dt.date | None) -> str | None:
    return d.isoformat() if d is not None else None


def week_start(d: _dt.date) -> _dt.date:
    """d を含む週の月曜日（Q-05: 月曜始まり）。"""
    return d - _dt.timedelta(days=d.weekday())


def date_range(start: _dt.date, end: _dt.date) -> list[_dt.date]:
    """start〜end（両端を含む）の日付リスト。"""
    n = (end - start).days
    return [start + _dt.timedelta(days=i) for i in range(n + 1)]


def minutes_to_hours(minutes: int) -> float:
    return minutes / 60


def format_hours(minutes: int) -> str:
    """表示用の所要時間（例: 2.0h, 1.25h）。"""
    h = minutes / 60
    text = f"{h:.2f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    return f"{text}h"
