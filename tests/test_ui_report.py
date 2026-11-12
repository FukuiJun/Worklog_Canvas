"""M4: 週報画面と CSV 取り込みボタンの自動確認（offscreen）。"""
import datetime as dt
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
openpyxl = pytest.importorskip("openpyxl")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from worklog_canvas.core import weekly_report as wr  # noqa: E402
from worklog_canvas.core.settings import Settings  # noqa: E402
from worklog_canvas.ui.app import MainWindow  # noqa: E402
from worklog_canvas.ui.state import AppState  # noqa: E402

TODAY = dt.date(2026, 11, 13)
DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, sample_folder, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOG_CANVAS_HOME", str(tmp_path / "home"))
    state = AppState(sample_folder, sample_folder.user("fukui"), Settings(), today=lambda: TODAY)
    w = MainWindow(state)
    w.resize(1280, 900)
    w.show()
    w.tabs.setCurrentWidget(w.summary)
    w.summary.setCurrentWidget(w.summary.report)
    qapp.processEvents()
    yield w
    w.close()


def test_report_page_preview_and_note_saved(win, qapp):
    page = win.summary.report
    assert page.week == dt.date(2026, 11, 9)
    assert "対象週：2026/11/09〜11/15" == page.week_label.text()
    text = page.preview.toPlainText()
    assert "チャージャIC：10時間充電停止の確認" in text and "36.25h" in text
    page.reflection.setPlainText("治具の精度確認に想定より時間がかかった")
    page.save_note()
    saved = win.state.folder.user("fukui").get_weekly_note(dt.date(2026, 11, 9))
    assert saved.reflection == "治具の精度確認に想定より時間がかかった"
    assert "治具の精度確認に想定より時間がかかった" in page.preview.toPlainText()


def test_note_is_limited_to_400_chars_and_saved_on_week_change(win):
    page = win.summary.report
    page.next_week.setPlainText("あ" * 450)
    assert len(page.next_week.toPlainText()) == 400
    assert page.next_week_count.text() == "400 / 400"
    page.set_week(dt.date(2026, 11, 16))  # 週を切り替えると前の週のメモを保存
    assert win.state.repo.get_weekly_note(dt.date(2026, 11, 9)).next_week == "あ" * 400
    assert page.next_week.toPlainText() == ""
    assert wr.EMPTY_MESSAGE in page.preview.toPlainText()


def test_empty_week_does_not_save(win, monkeypatch, tmp_path):
    page = win.summary.report
    page.set_week(dt.date(2026, 11, 16))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    page.save_excel()
    page.copy_text()
    assert shown == [wr.EMPTY_MESSAGE, wr.EMPTY_MESSAGE]


def test_write_and_copy(win, tmp_path):
    page = win.summary.report
    rep = page.build()
    out = tmp_path / "out" / rep.filename
    assert page.write(rep, out)
    ws = openpyxl.load_workbook(out).active
    assert ws["A1"].value == "週報"
    assert win.state.settings.report_dir == str(out.parent)
    page.copy_text()
    assert QGuiApplication.clipboard().text().startswith("■タスク実績（2026/11/09〜11/15）")


def test_locked_file_shows_message(win, tmp_path, monkeypatch):
    page = win.summary.report
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(wr.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError(13, "locked")))
    assert not page.write(page.build(), tmp_path / "x.xlsx")
    assert shown == ["ファイルを閉じてから再度実行してください"]


def test_csv_button_imports_and_reports(win, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    before = len(win.state.repo.tasks)
    win.task_list.import_csv(str(DATA / "sample_tasks_sjis.csv"))
    assert len(win.state.repo.tasks) == before + 3
    assert shown[0].startswith("3件のタスクを追加しました。")
    assert win.task_list.table.rowCount() == before + 3
