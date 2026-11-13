"""exe の動作確認（WorklogCanvas.exe --self-test）。

一時フォルダにデータを作り、同梱した部品（画面、Excel出力、予定表ファイルの読み込み、タイムゾーン）を
一通り動かして終了する。結果は %APPDATA%/WorklogCanvas/selftest.txt に書き、成功なら終了コード 0。
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import traceback
from pathlib import Path

ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Worklog Canvas selftest//JA\r
BEGIN:VTIMEZONE\r
TZID:Tokyo Standard Time\r
BEGIN:STANDARD\r
DTSTART:16010101T000000\r
TZOFFSETFROM:+0900\r
TZOFFSETTO:+0900\r
END:STANDARD\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
UID:a\r
SUMMARY:定例\r
DTSTART;TZID=Tokyo Standard Time:20261102T090000\r
DTEND;TZID=Tokyo Standard Time:20261102T093000\r
RRULE:FREQ=WEEKLY;COUNT=4\r
EXDATE;TZID=Tokyo Standard Time:20261109T090000\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:b\r
SUMMARY:UTC\r
DTSTART:20261110T010000Z\r
DTEND:20261110T020000Z\r
END:VEVENT\r
END:VCALENDAR\r
"""


def run() -> int:
    from .core import settings as st
    lines = []

    def step(name, fn):
        fn()
        lines.append(f"OK  {name}")

    code = 0
    try:
        with tempfile.TemporaryDirectory(prefix="wc_selftest_") as tmp:
            tmp = Path(tmp)

            def core():
                from zoneinfo import ZoneInfo
                from .core import ics, weekly_report
                from .core.models import Task, Worklog
                from .core.repository import DataFolder
                folder = DataFolder(tmp / "data")
                repo = folder.user("selftest")
                t = repo.add_task(Task(id="", name="動作確認", category="", status="進行中"))
                repo.add_worklog(Worklog("", dt.date(2026, 11, 10), 600, 720, task_id=t.id))
                rep = weekly_report.build_report(repo.tasks, repo.worklogs, None, "確認", dt.date(2026, 11, 9),
                                                 dt.date(2026, 11, 13))
                weekly_report.write_xlsx(rep, tmp / rep.filename)
                assert (tmp / rep.filename).stat().st_size > 0
                (tmp / "a.ics").write_text(ICS, encoding="utf-8")
                f = ics.IcsFile(tmp / "a.ics", tz=ZoneInfo("Asia/Tokyo"))
                week = f.week(dt.date(2026, 11, 9))
                assert [(a.title, a.start.hour) for a in week.appointments] == [("UTC", 10)], week
                assert len(f.week(dt.date(2026, 11, 16)).appointments) == 1

            def gui():
                from PySide6.QtWidgets import QApplication
                from .core.repository import DataFolder
                from .core.settings import Settings
                from .ui.app import MainWindow, _apply_font
                from .ui.state import AppState
                app = QApplication.instance() or QApplication(sys.argv[:1])
                _apply_font(app)
                folder = DataFolder(tmp / "data")
                win = MainWindow(AppState(folder, folder.user("selftest"), Settings()))
                win.show()
                for i in range(win.tabs.count()):
                    win.tabs.setCurrentIndex(i)
                    app.processEvents()
                win.grab()
                win.close()

            step("データ処理・Excel出力・予定表ファイル・タイムゾーン", core)
            step("画面", gui)
    except Exception:  # noqa: BLE001
        lines.append("NG\n" + traceback.format_exc())
        code = 1
    from . import __version__
    text = (f"Worklog Canvas {__version__} 動作確認: " + ("成功" if code == 0 else "失敗") + "\n"
            + "\n".join(lines) + "\n")
    try:
        out = st.app_dir()
        out.mkdir(parents=True, exist_ok=True)
        (out / "selftest.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout is not None:
        try:
            sys.stdout.write(text)
        except (OSError, UnicodeEncodeError):
            pass
    return code
