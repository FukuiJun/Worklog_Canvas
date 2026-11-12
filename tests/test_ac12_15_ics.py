"""AC-12, AC-15: 予定表ファイル（.ics）の読み込み（F-05）。"""
import datetime as dt
import time
from pathlib import Path

import pytest

pytest.importorskip("icalendar")
pytest.importorskip("recurring_ical_events")
from zoneinfo import ZoneInfo  # noqa: E402

from worklog_canvas.core import ics  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data" / "sample_calendar.ics"
JST = ZoneInfo("Asia/Tokyo")
D, T = dt.date, dt.datetime


def _week(path, monday, tz=JST):
    return ics.IcsFile(path, tz=tz).week(monday)


# --- AC-12: 通常・終日・毎週の繰り返し・UTC表記の予定を、対象週の件数・日本時間の日時で得られる ---
def test_ac12_sample_week():
    r = _week(SAMPLE, D(2026, 11, 9))
    assert r.skipped == 0
    assert [(a.title, a.start, a.end, a.all_day) for a in r.appointments] == [
        ("定例会議", T(2026, 11, 9, 9, 0), T(2026, 11, 9, 9, 30), False),  # 毎週の繰り返し
        ("設計レビュー", T(2026, 11, 10, 10, 0), T(2026, 11, 10, 12, 0), False),  # 通常の予定
        ("海外拠点との電話会議", T(2026, 11, 11, 14, 0), T(2026, 11, 11, 15, 0), False),  # UTC 05:00 → 14:00
        ("部署イベント（終日）", T(2026, 11, 12), T(2026, 11, 13), True),  # 終日
        ("部品メーカー来社", T(2026, 11, 13, 13, 10), T(2026, 11, 13, 13, 50), False),
    ]


def test_ac12_recurrence_exdate_and_moved_occurrence():
    f = ics.IcsFile(SAMPLE, tz=JST)
    assert [a.start for a in f.week(D(2026, 11, 2)).appointments] == [T(2026, 11, 2, 9, 0)]
    assert f.week(D(2026, 11, 16)).appointments == []  # EXDATE で除外
    moved = f.week(D(2026, 11, 23)).appointments  # 祝日の回だけ火曜に移動（RECURRENCE-ID）
    assert [(a.title, a.start) for a in moved] == [("定例会議（祝日のため火曜に変更）", T(2026, 11, 24, 10, 0))]
    # UNTIL=2026-12-28T00:00Z（日本時間 9:00）は最後の回を含む。その次の週からは出ない
    assert [a.start for a in f.week(D(2026, 12, 28)).appointments] == [T(2026, 12, 28, 9, 0)]
    assert f.week(D(2027, 1, 4)).appointments == []


def test_ac12_utc_event_in_other_timezone():
    r = _week(SAMPLE, D(2026, 11, 9), tz=dt.timezone.utc)
    call = next(a for a in r.appointments if a.title == "海外拠点との電話会議")
    assert call.start == T(2026, 11, 11, 5, 0)


def test_all_day_and_spans():
    r = _week(SAMPLE, D(2026, 11, 9))
    allday = next(a for a in r.appointments if a.all_day)
    assert allday.days() == [D(2026, 11, 12)] and allday.span_on(D(2026, 11, 12)) is None
    a = ics.Appointment("夜勤", T(2026, 11, 10, 22, 0), T(2026, 11, 11, 2, 0), False)
    assert a.days() == [D(2026, 11, 10), D(2026, 11, 11)]
    assert a.span_on(D(2026, 11, 10)) == (22 * 60, 24 * 60) and a.span_on(D(2026, 11, 11)) == (0, 120)


def test_to_worklog_rounds_to_quarter():
    r = _week(SAMPLE, D(2026, 11, 9))
    visit = next(a for a in r.appointments if a.title == "部品メーカー来社")  # 13:10〜13:50
    w = ics.to_worklog(visit, D(2026, 11, 13))
    assert (w.start, w.end) == (13 * 60 + 15, 13 * 60 + 45)
    assert (w.kind, w.title, w.source) == ("単発作業", "部品メーカー来社", "Outlook")
    short = ics.Appointment("立ち話", T(2026, 11, 13, 10, 0), T(2026, 11, 13, 10, 5), False)
    w = ics.to_worklog(short, D(2026, 11, 13))
    assert (w.start, w.end) == (600, 615)  # 最短15分
    w.validate()


# --- AC-15: .ics ではないファイルを読み込んでも、メッセージが出るだけで終了しない ---
@pytest.mark.parametrize("content", [
    "これは予定表ではありません\nただのテキストです\n".encode("utf-8"),
    b"",
    b"\x00\x01\x02\xff\xfe",
    b"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Taro\r\nEND:VCARD\r\n",
])
def test_ac15_not_ics(tmp_path, content):
    p = tmp_path / "fake.ics"
    p.write_bytes(content)
    with pytest.raises(ics.IcsFormatError) as e:
        ics.IcsFile(p, tz=JST)
    assert str(e.value) == "予定表ファイルを読み取れませんでした"


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        ics.IcsFile(tmp_path / "none.ics")


def test_some_events_unreadable_are_skipped(tmp_path):
    text = SAMPLE.read_text("utf-8").replace(
        "END:VCALENDAR",
        "BEGIN:VEVENT\r\nUID:bad1\r\nSUMMARY:壊れた予定\r\nDTSTART:2026-99-99\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:bad2\r\nSUMMARY:開始なし\r\nEND:VEVENT\r\nEND:VCALENDAR")
    p = tmp_path / "partial.ics"
    p.write_text(text, encoding="utf-8")
    r = ics.IcsFile(p, tz=JST).week(D(2026, 11, 9))
    assert r.skipped == 2 and len(r.appointments) == 5


def test_2000_events_within_3_seconds(tmp_path):
    """仕様8章: 予定2000件のICSファイルを3秒以内に読み込む（参考の計測）。"""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//JA"]
    base = T(2026, 1, 5, 9, 0)
    for i in range(2000):
        s = base + dt.timedelta(days=i // 8, minutes=60 * (i % 8))
        lines += ["BEGIN:VEVENT", f"UID:e{i}", f"SUMMARY:予定{i}",
                  f"DTSTART:{s:%Y%m%dT%H%M%S}", f"DTEND:{s + dt.timedelta(minutes=45):%Y%m%dT%H%M%S}"]
        if i % 50 == 0:
            lines.append("RRULE:FREQ=WEEKLY;COUNT=40")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    p = tmp_path / "big.ics"
    p.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    t0 = time.perf_counter()
    f = ics.IcsFile(p, tz=JST)
    r = f.week(D(2026, 3, 2))
    elapsed = time.perf_counter() - t0
    assert r.appointments and r.skipped == 0
    assert elapsed < 3.0, f"{elapsed:.2f}秒"
