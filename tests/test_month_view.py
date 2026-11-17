"""タイムラインの月表示。"""
import datetime as dt
import os

import pytest

from worklog_canvas.core import recurring as rc
from worklog_canvas.core import timeline as tl
from worklog_canvas.core.models import KIND_ONEOFF, Task, Worklog

D = dt.date


def test_month_dates_cover_whole_weeks():
    dates = tl.month_dates(D(2026, 11, 17))
    assert dates[0] == D(2026, 10, 26) and dates[-1] == D(2026, 12, 6)  # 月曜始まり、6週
    assert len(dates) == 42 and dates[0].weekday() == 0
    assert len(tl.month_dates(D(2021, 2, 10))) == 28  # 2021年2月は1日が月曜で4週ちょうど
    assert tl.visible_dates(D(2026, 11, 17), "month") == dates


def test_step_month():
    assert tl.step_anchor(D(2026, 11, 17), "month", 1) == D(2026, 12, 1)
    assert tl.step_anchor(D(2026, 1, 31), "month", -1) == D(2025, 12, 1)
    assert tl.add_months(D(2026, 1, 31), 1) == D(2026, 2, 28)


# --- 画面 ---
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def win(data_folder, tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    from worklog_canvas.core.settings import Settings
    from worklog_canvas.ui.app import MainWindow
    from worklog_canvas.ui.state import AppState
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("WORKLOG_CANVAS_HOME", str(tmp_path / "home"))
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="基板の評価", status="進行中"))
    for start in (600, 660, 720, 780, 840):  # 11/17 に5本
        repo.add_worklog(Worklog("", D(2026, 11, 17), start, start + 45, task_id="T-0001"))
    repo.add_worklog(Worklog("", D(2026, 11, 18), 540, 600, kind=KIND_ONEOFF, title="製造応援"))
    repo.add_recurring(rc.RecurringItem(id="", start=510, end=540, pattern=rc.DAILY_WEEKDAYS, kind=KIND_ONEOFF,
                                        title="朝会", start_date=D(2026, 11, 16)))
    w = MainWindow(AppState(data_folder, repo, Settings(), today=lambda: D(2026, 11, 17)))
    w.resize(1400, 900)
    w.show()
    yield w
    w.close()


def test_switch_to_month_and_back_by_clicking_a_day(win):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    t = win.timeline
    t.btn_month.click()
    assert t.mode == "month" and t.btn_month.isChecked()
    assert t.pages.currentWidget() is t.month_view
    assert t.period_label.text() == "2026年11月"
    mv = t.month_view
    mv.repaint()
    i = mv.dates.index(D(2026, 11, 18))
    QTest.mouseClick(mv, Qt.LeftButton, pos=mv.cell_rect(i).center().toPoint())
    assert (t.mode, t.anchor) == ("day", D(2026, 11, 18))
    assert t.pages.currentWidget() is not mv and t.canvas.dates == [D(2026, 11, 18)]
    assert mv.date_at(QPointF(5, 5)) is None  # 曜日の見出し


def test_month_navigation(win):
    t = win.timeline
    t.set_mode("month")
    t.step(1)
    assert t.period_label.text() == "2026年12月" and t.month_view.month == D(2026, 12, 1)
    t.go_today()
    assert t.month_view.month == D(2026, 11, 1)


def test_chips_order_hours_and_more(win):
    t = win.timeline
    t.set_mode("month")
    mv = t.month_view
    chips = mv.chips_for(D(2026, 11, 18))
    assert [(c.kind, c.text) for c in chips] == [("recurring", "8:30 朝会"), ("worklog", "9:00 製造応援")]
    assert mv.day_minutes(D(2026, 11, 17)) == 225
    many = mv.chips_for(D(2026, 11, 17))
    assert len(many) == 6  # 朝会 + 作業バー5本
    from PySide6.QtGui import QFontMetrics
    mv._build_layout(QFontMetrics(mv.font()))
    _d, _cell, rows = next(x for x in mv._layout if x[0] == D(2026, 11, 17))
    shown = [c for _r, c, _n in rows if c is not None]
    rest = [n for _r, c, n in rows if c is None]
    assert rest and len(shown) + rest[0] == 6  # 入りきらない分は「+n」


def test_viewing_other_hides_recurring(win, monkeypatch):
    t = win.timeline
    t.set_mode("month")
    monkeypatch.setattr(type(win.state), "viewing_other", property(lambda s: True))
    assert all(c.kind == "worklog" for c in t.month_view.chips_for(D(2026, 11, 18)))
