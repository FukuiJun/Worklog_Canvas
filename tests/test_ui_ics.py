"""M6（画面）: 予定表ファイルの取り込み（AC-13, 14, 15 の自動確認。AC-13 は実環境の手動確認が正式）。"""
import datetime as dt
import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("icalendar")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from worklog_canvas.core.settings import Settings  # noqa: E402
from worklog_canvas.ui.app import MainWindow  # noqa: E402
from worklog_canvas.ui.state import AppState  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data" / "sample_calendar.ics"
TODAY = dt.date(2026, 11, 12)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def jst(monkeypatch):
    """テストはPCのタイムゾーンを日本時間に固定する。"""
    from zoneinfo import ZoneInfo
    from worklog_canvas.core import ics
    monkeypatch.setattr(ics, "local_tz", lambda: ZoneInfo("Asia/Tokyo"))


@pytest.fixture
def win(qapp, sample_folder, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOG_CANVAS_HOME", str(tmp_path / "home"))
    state = AppState(sample_folder, sample_folder.user("fukui"), Settings(), today=lambda: TODAY)
    w = MainWindow(state)
    w.resize(1280, 800)
    w.show()
    w.timeline.go_today()
    qapp.processEvents()
    yield w
    w.close()


def _ics_copy(tmp_path) -> str:
    p = tmp_path / "予定表.ics"
    shutil.copy(SAMPLE, p)
    return str(p)


def test_ac13_appointment_bar_at_same_position(win, tmp_path):
    tab = win.timeline
    assert tab.load_ics(_ics_copy(tmp_path))
    c = tab.canvas
    rects = {(a.title, d): r for a, d, r in c.appointment_rects()}
    r = rects[("設計レビュー", dt.date(2026, 11, 10))]  # Outlook上 10:00〜12:00
    assert r.top() == pytest.approx(c.y_of(600)) and r.bottom() == pytest.approx(c.y_of(720))
    assert r.left() == pytest.approx(c.col_x(1) + 1)  # 火曜の列
    # UTC表記の予定は日本時間 14:00〜15:00 の位置
    r = rects[("海外拠点との電話会議", dt.date(2026, 11, 11))]
    assert r.top() == pytest.approx(c.y_of(14 * 60))
    # 終日の予定は列の上部（見出し）に件名だけ
    assert [a.title for a in c.all_day_on(dt.date(2026, 11, 12))] == ["部署イベント（終日）"]
    assert tab.header.height() > tab.header.BASE
    assert ("部署イベント（終日）", dt.date(2026, 11, 12)) not in rects


def test_ac14_convert_to_worklog(win, tmp_path):
    tab = win.timeline
    tab.load_ics(_ics_copy(tmp_path))
    c = tab.canvas
    # サンプルでは 11/13 13:00〜14:00 に「会議」の作業バーがあるので、まだ記録していない状態にする
    meeting = next(w for w in win.state.repo.worklogs_on(dt.date(2026, 11, 13)) if w.title == "会議")
    win.state.editor.delete(meeting.id)
    hit = c.appointment_at(QPointF(c.col_x(4) + 20, c.y_of(13 * 60 + 30)))  # 金曜 13:10〜13:50
    assert hit and hit[0].title == "部品メーカー来社"
    assert c.convert_appointment(*hit)
    w = win.state.repo.worklogs[-1]
    assert (w.date, w.start, w.end) == (dt.date(2026, 11, 13), 13 * 60 + 15, 13 * 60 + 45)
    assert (w.kind, w.title, w.source) == ("単発作業", "部品メーカー来社", "Outlook")
    # 既存の作業バーと重なる予定は作業バーにできない（F-02 の異常時と同じ）
    review = next(a for a, d, _ in c.appointment_rects() if a.title == "設計レビュー")
    n = len(win.state.repo.worklogs)
    assert not c.convert_appointment(review, dt.date(2026, 11, 10))
    assert len(win.state.repo.worklogs) == n and "すでに作業バー" in win.message.text()
    # 予定バーは保存しない（worklogs.json には作業バーにしたものだけ）
    saved = win.state.folder.user("fukui").worklogs
    assert sum(1 for x in saved if x.source == "Outlook") == 1


def test_ac15_not_ics_shows_message_only(win, tmp_path, monkeypatch):
    tab = win.timeline
    tab.load_ics(_ics_copy(tmp_path))
    before = list(tab.canvas.appointments)
    fake = tmp_path / "メモ.ics"
    fake.write_text("ただのテキスト\n", encoding="utf-8")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    assert not tab.load_ics(str(fake))
    assert shown == ["予定表ファイルを読み取れませんでした"]
    assert tab.canvas.appointments == before  # 予定バーは変更しない
    assert win.state.settings.ics_path != str(fake)
    assert win.isVisible()  # 終了しない


def test_week_switch_uses_same_file_and_messages(win, tmp_path):
    tab = win.timeline
    path = _ics_copy(tmp_path)
    tab.load_ics(path)
    assert win.state.settings.ics_path == path
    tab.step(1)  # 11/16の週: EXDATEで定例なし
    assert tab.canvas.appointments == []
    assert win.message.text() == "この週の予定はファイルにありません"
    tab.step(1)
    assert [a.title for a in tab.canvas.appointments] == ["定例会議（祝日のため火曜に変更）"]
    Path(path).unlink()  # 週の切り替えは読み込み済みの内容から
    tab.step(-2)
    assert len(tab.canvas.appointments) == 5
    tab.reload_ics()  # 「再読み込み」は同じパスを読み直す → 見つからない
    assert tab.canvas.appointments == []


def test_saved_path_missing_at_startup(qapp, sample_folder, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOG_CANVAS_HOME", str(tmp_path / "home"))
    st = Settings(ics_path=str(tmp_path / "消えた.ics"))
    state = AppState(sample_folder, sample_folder.user("fukui"), st, today=lambda: TODAY)
    w = MainWindow(state)
    w.show()
    qapp.processEvents()
    assert w.timeline.canvas.appointments == []
    assert w.message.text() == "予定表ファイルが見つかりません"
    w.close()


def test_drop_ics_file_on_timeline(win, tmp_path):
    c = win.timeline.canvas
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(_ics_copy(tmp_path))])
    ev = QDropEvent(QPointF(200, 200), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    c.dropEvent(ev)
    assert len(c.appointments) == 5


def test_skipped_events_message(win, tmp_path):
    text = SAMPLE.read_bytes().decode("utf-8").replace(
        "END:VCALENDAR", "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:2026-99-99\r\nEND:VEVENT\r\nEND:VCALENDAR")
    p = tmp_path / "partial.ics"
    p.write_bytes(text.encode("utf-8"))  # 改行（\r\n）を Windows で変換させない
    assert win.timeline.load_ics(str(p))
    assert win.message.text() == "1件の予定を読み飛ばしました"
    assert len(win.timeline.canvas.appointments) == 5


def test_appointments_hidden_when_viewing_other(win, tmp_path):
    win.timeline.load_ics(_ics_copy(tmp_path))
    win.view_user("sato")
    assert win.timeline.canvas.appointment_rects() == []
    win.view_user("fukui")
    assert win.timeline.canvas.appointment_rects()
