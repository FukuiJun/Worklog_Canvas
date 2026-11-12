"""M3: 進捗率の入力（F-03）と集計画面（F-04）の自動確認（offscreen）。"""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from worklog_canvas.core.settings import Settings  # noqa: E402
from worklog_canvas.ui.app import MainWindow  # noqa: E402
from worklog_canvas.ui.state import AppState  # noqa: E402
from worklog_canvas.ui.task_list_tab import COLUMNS, ProgressSlider  # noqa: E402

TODAY = dt.date(2026, 11, 12)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, sample_folder):
    state = AppState(sample_folder, sample_folder.user("fukui"), Settings(), today=lambda: TODAY)
    w = MainWindow(state)
    w.resize(1280, 900)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def _slider(tab, task_id) -> ProgressSlider:
    for r in range(tab.table.rowCount()):
        w = tab.table.cellWidget(r, len(COLUMNS) - 1)
        if w.task_id == task_id:
            return w
    raise KeyError(task_id)


def test_f03_slider_records_history_and_overwrites_same_day(win, qapp, monkeypatch):
    tab = win.task_list
    win.tabs.setCurrentWidget(tab)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    _slider(tab, "T-0007").slider.setValue(4)  # 20%（キー操作と同じ: つまみを持たずに変更）
    qapp.processEvents()
    _slider(tab, "T-0007").slider.setValue(8)  # 同じ日に40%へ
    qapp.processEvents()
    t = win.state.repo.get_task("T-0007")
    assert t.progress == 40
    assert [e.to_dict() for e in t.history] == [{"日付": "2026-11-12", "進捗率": 40}]
    again = win.state.folder.user("fukui").get_task("T-0007")  # 保存済み
    assert again.progress == 40
    assert _slider(tab, "T-0007").label.text() == "40%"


def test_f03_100_percent_asks_to_complete(win, qapp, monkeypatch):
    tab = win.task_list
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    _slider(tab, "T-0004").slider.setValue(20)
    qapp.processEvents()
    t = win.state.repo.get_task("T-0004")
    assert asked and "完了" in asked[0]
    assert (t.progress, t.status, t.done_date) == (100, "完了", TODAY)


def test_f03_slider_stays_with_its_task_after_sorting(win, qapp):
    tab = win.task_list
    tab.table.sortByColumn(len(COLUMNS) - 1, Qt.DescendingOrder)
    qapp.processEvents()
    for r in range(tab.table.rowCount()):
        tid = tab.table.item(r, 0).data(Qt.UserRole + 1)
        w = tab.table.cellWidget(r, len(COLUMNS) - 1)
        assert w.task_id == tid
        assert w.value() == win.state.repo.get_task(tid).progress
    values = [tab.table.cellWidget(r, len(COLUMNS) - 1).value() for r in range(tab.table.rowCount())]
    assert values == sorted(values, reverse=True)


def test_f03_readonly_disables_slider(win):
    win.state.repo.readonly = True
    win.state.tasks_changed.emit()
    assert not _slider(win.task_list, "T-0001").slider.isEnabled()


def test_f04_week_summary_matches_sample(win, qapp):
    win.tabs.setCurrentWidget(win.summary)
    page = win.summary.summary
    page.go_today()
    qapp.processEvents()
    assert page.period() == (dt.date(2026, 11, 9), dt.date(2026, 11, 15))
    assert "稼働時間 36.25h" in page.summary_line.text()
    assert not page.empty_label.isVisibleTo(page)
    # 週のタスク別時間（降順、単発作業は1本）
    rows = [(name, m / 60) for name, m, _, _ in page.task_chart.rows]
    assert rows[0] == ("次世代基板：マイコンのバッテリ読み取り精度の検証・評価", 13.0)
    assert ("単発作業", 4.0) in rows
    assert [m for _, m in rows] == sorted((m for _, m in rows), reverse=True)
    # 日別の積み上げ（稼働時間＝棒の高さ）
    assert [s.working / 60 for s in page.daily.stacks] == [8.0, 7.0, 7.5, 6.75, 7.0, 0, 0]
    # カテゴリ別（割合の合計100%）
    t = page.cat_table
    cats = {t.item(r, 0).text(): (t.item(r, 1).text(), t.item(r, 2).text()) for r in range(t.rowCount())}
    assert cats["次世代基板"] == ("16.0h", "44.1%")
    assert cats["合計"] == ("36.25h", "100.0%")


def test_f04_progress_table(win, qapp):
    page = win.summary.summary
    win.tabs.setCurrentWidget(win.summary)
    page.go_today()
    qapp.processEvents()
    t = page.progress_table
    rows = {t.item(r, 0).text(): r for r in range(t.rowCount())}
    r = rows["次世代基板：マイコンのバッテリ読み取り精度の検証・評価"]
    assert t.item(r, 4).text() == "24.75h / 16h（超過）"
    assert t.item(r, 4).foreground().color().name().upper() == "#C62828"
    assert t.item(r, 7).text() == "あと 8 日"
    assert t.cellWidget(r, 3).value == 40
    r = rows["IC微小電流測定用の治具作成（INA226＋Arduinoのプログラム）"]
    assert t.item(r, 5).text() == "2.5h"  # サブ時間の累計
    assert "チャージャIC：10時間充電停止の確認" in rows  # 完了だが期間内に作業バーあり
    assert "試作基板の部品手配" not in rows  # 完了で期間内に作業バーなし


def test_f04_empty_period_and_navigation(win, qapp):
    page = win.summary.summary
    win.tabs.setCurrentWidget(win.summary)
    page.go_today()
    page.step(1)
    qapp.processEvents()
    assert page.empty_label.isVisibleTo(page) and page.empty_label.text() == "記録がありません"
    assert not page.period_box.isVisibleTo(page)
    assert page.progress_table.rowCount() == 6  # 進捗は期間に関係なく未完了タスクを表示
    page.set_mode("day")
    page.anchor = dt.date(2026, 11, 10)
    page.refresh()
    assert "稼働時間 7.0h" in page.summary_line.text()
    page.set_mode("custom")
    page.start_edit.setDate(page.start_edit.date().addDays(-7))
    assert page.period() == (dt.date(2026, 11, 2), dt.date(2026, 11, 15))
    assert "稼働時間 66.0h" in page.summary_line.text()


def test_f04_refreshes_when_bars_change(win, qapp):
    page = win.summary.summary
    win.tabs.setCurrentWidget(win.summary)
    page.go_today()
    qapp.processEvents()
    w = win.state.repo.worklogs_on(dt.date(2026, 11, 13))[0]
    win.state.editor.delete(w.id)
    win.state.worklogs_changed.emit()
    assert "稼働時間 33.25h" in page.summary_line.text()
