"""M5（画面）: 個別閲覧（AC-19）、チーム一覧（AC-20）、未保存の表示と再試行、終了時の警告、設定、起動時の異常系。"""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from worklog_canvas.core import backup, storage  # noqa: E402
from worklog_canvas.core import timeline as tl  # noqa: E402
from worklog_canvas.core.models import Task, Worklog  # noqa: E402
from worklog_canvas.core.repository import DataFolder  # noqa: E402
from worklog_canvas.core.settings import Settings  # noqa: E402
from worklog_canvas.ui import app as app_mod  # noqa: E402
from worklog_canvas.ui.app import MainWindow, check_folder, load_own  # noqa: E402
from worklog_canvas.ui.settings_dialog import SettingsDialog  # noqa: E402
from worklog_canvas.ui.state import AppState  # noqa: E402
from worklog_canvas.ui.timeline_view import TASK_MIME  # noqa: E402

TODAY = dt.date(2026, 11, 12)


def h(t):
    a, b = t.split(":")
    return int(a) * 60 + int(b)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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
    w.state.own_repo.pending.clear()
    w.close()


def _mouse(c, kind, pos, buttons=Qt.LeftButton):
    QApplication.sendEvent(c, QMouseEvent(kind, pos, c.mapToGlobal(pos), Qt.LeftButton, buttons, Qt.NoModifier))


def _drag(c, a, b):
    _mouse(c, QEvent.MouseButtonPress, a)
    _mouse(c, QEvent.MouseMove, QPointF(a.x(), (a.y() + b.y()) / 2))
    _mouse(c, QEvent.MouseMove, b)
    _mouse(c, QEvent.MouseButtonRelease, b, Qt.NoButton)


def _pt(c, col, minutes):
    return QPointF(c.col_x(col) + c.col_width() / 2, c.y_of(minutes))


# --- AC-19: 個別閲覧中は作業バーの作成・移動・削除ができない ---
def test_ac19_view_mode_blocks_bar_editing(win, sample_folder):
    assert win.view_user("sato")
    st = win.state
    assert st.viewing_other and st.readonly and win.banner.text() == "閲覧モード：佐藤"
    assert win.user_combo.currentData() == "sato"
    c = win.timeline.canvas
    before = [w.to_dict() for w in st.repo.worklogs]
    _drag(c, _pt(c, 3, h("18:00")), _pt(c, 3, h("19:00")))  # 空き時間に作成
    _drag(c, _pt(c, 3, h("09:30")), _pt(c, 3, h("18:30")))  # 移動
    _drag(c, _pt(c, 0, h("12:00")) - QPointF(0, 2), _pt(c, 0, h("13:00")))  # 伸縮
    _mouse(c, QEvent.MouseButtonPress, _pt(c, 3, h("09:30")))
    _mouse(c, QEvent.MouseButtonRelease, _pt(c, 3, h("09:30")), Qt.NoButton)
    QTest.keyClick(c, Qt.Key_Delete)  # 削除
    md = QMimeData()
    md.setData(TASK_MIME, b"T-0001")
    enter = QDragEnterEvent(_pt(c, 3, h("18:30")).toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    c.dragEnterEvent(enter)
    assert not enter.isAccepted()  # タスク一覧パネルからのドロップも受け付けない
    c.drop_task("T-0001", TODAY, tl.DropCreate(h("18:00"), h("19:00")))  # 直接呼んでも書き込まない
    assert "閲覧モード" in win.message.text()
    win._undo()
    assert [w.to_dict() for w in st.repo.worklogs] == before
    assert [w.to_dict() for w in sample_folder.user("sato").worklogs] == before  # ファイルも変わらない
    # タスク一覧・週報の入力も無効
    assert not win.task_list.btn_add.isEnabled() and not win.task_list.btn_csv.isEnabled()
    assert win.summary.report.reflection.isReadOnly()
    assert not win.btn_settings.isEnabled()


def test_switch_back_to_self_and_notes_do_not_leak(win, sample_folder):
    report = win.summary.report
    report.set_week(dt.date(2026, 11, 2))
    assert report.reflection.toPlainText() == "治具の精度確認に想定より時間がかかった"  # 福井さんのメモ
    win.view_user("sato")
    assert report.reflection.toPlainText() == ""  # 佐藤さんのメモ（なし）
    win.view_user("fukui")
    assert not win.state.readonly and win.banner.isHidden()
    assert report.reflection.toPlainText() == "治具の精度確認に想定より時間がかかった"
    assert sample_folder.user("fukui").get_weekly_note(dt.date(2026, 11, 2)).reflection == \
        "治具の精度確認に想定より時間がかかった"


def test_view_unreadable_member_shows_message(win, sample_folder, monkeypatch):
    (sample_folder.users_dir / "suzuki" / "worklogs.json").write_text("{", encoding="utf-8")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    assert not win.view_user("suzuki")
    assert "読み込めませんでした" in shown[0] and not win.state.viewing_other


# --- AC-20: 3名分のサンプルデータで、チーム一覧に3列のタイムラインと各自の進行中タスク ---
def test_ac20_team_three_columns_and_in_progress(win, qapp):
    win.tabs.setCurrentWidget(win.team)
    win.team.set_day(TODAY)
    qapp.processEvents()
    days = win.team.canvas.days
    assert [d.member.display_name for d in days] == ["福井", "佐藤", "鈴木"]
    assert all(d.worklogs for d in days)
    t = win.team.table
    rows = [(t.item(r, 0).text(), t.item(r, 1).text()) for r in range(t.rowCount())]
    assert {m for m, _ in rows} == {"福井", "佐藤", "鈴木"}
    assert ("鈴木", "顧客向け技術資料の確認") in rows
    assert sum(1 for m, _ in rows if m == "福井") == 3


def test_team_unreadable_member_column(win, sample_folder, qapp):
    (sample_folder.users_dir / "sato" / "tasks.json").write_text("{", encoding="utf-8")
    win.tabs.setCurrentWidget(win.team)
    win.team.reload()
    days = win.team.canvas.days
    assert not days[1].member.ok and days[0].member.ok and days[2].member.ok
    t = win.team.table
    assert any(t.item(r, 1).text() == "読み込めませんでした" for r in range(t.rowCount()))


def test_team_reload_picks_up_changes(win, sample_folder):
    win.tabs.setCurrentWidget(win.team)
    win.team.set_day(dt.date(2026, 11, 16))
    assert win.team.canvas.days[1].worklogs == []
    other = sample_folder.user("sato")
    other.add_worklog(Worklog("", dt.date(2026, 11, 16), 600, 660, kind="単発作業", title="会議"))
    assert win.team.canvas.days[1].worklogs == []  # 自動では更新しない
    win.btn_refresh.click()
    assert len(win.team.canvas.days[1].worklogs) == 1


# --- 9章: 保存の失敗 → 「未保存」、30秒ごとの再試行、終了時の警告 ---
def test_unsaved_indicator_retry_and_close_warning(win, monkeypatch):
    real_replace = storage.os.replace
    monkeypatch.setattr(storage.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("切断")))
    win.state.own_repo.add_task(Task(id="", name="切断中"))
    assert win.unsaved_label.isVisible() and win.unsaved_label.text() == "未保存"
    assert win._retry_timer.isActive() and win._retry_timer.interval() == 30_000
    asked = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert asked and "保存できていない変更" in asked[0] and not ev.isAccepted()
    monkeypatch.setattr(storage.os, "replace", real_replace)
    win._retry_timer.timeout.emit()  # 30秒後の再試行
    assert not win.unsaved_label.isVisible() and not win._retry_timer.isActive()
    assert DataFolder(win.state.folder.root).user("fukui").tasks[-1].name == "切断中"


# --- 設定 ---
def test_settings_display_name_and_view_range(win, sample_folder):
    dlg = SettingsDialog(win.state, win)
    dlg.display_name.setText("福井J")
    dlg.start_hour.setCurrentIndex(dlg.start_hour.findData(7 * 60))
    dlg.end_hour.setCurrentIndex(dlg.end_hour.findData(22 * 60))
    dlg._save()
    assert win.timeline.canvas.view_start == 420 and win.timeline.canvas.view_end == 1320
    assert sample_folder.user("fukui").profile.display_name == "福井J"
    assert Settings.load().view_start == "07:00"


def test_settings_category_in_use_cannot_be_deleted(win, monkeypatch):
    dlg = SettingsDialog(win.state, win)
    for i in range(dlg.cat_list.count()):
        if dlg.cat_list.item(i).data(Qt.UserRole) == "治具":
            dlg.cat_list.setCurrentRow(i)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._delete_category()
    assert "使われているため" in dlg.cat_err.text()
    assert "治具" in win.state.folder.category_colors()


# --- 起動時の異常系 ---
def test_check_folder(tmp_path):
    assert check_folder(str(tmp_path)) is None
    assert check_folder(str(tmp_path / "ない")) == "フォルダが見つかりません"


def test_load_own_restores_broken_json_from_backup(sample_folder):
    backup.make_daily_backup(sample_folder, "fukui", dt.date(2026, 11, 11))
    path = sample_folder.users_dir / "fukui" / "tasks.json"
    path.write_text("壊れた", encoding="utf-8")
    asked = []
    repo = load_own(sample_folder, "fukui", readonly=False, ask=lambda *a: asked.append(a) or True)
    assert len(repo.tasks) == 8
    assert asked[0][0] == "tasks.json" and asked[0][1] == dt.date(2026, 11, 11)
    assert any(p.name.startswith("tasks.json.broken_") for p in path.parent.iterdir())


def test_load_own_declined_restore_starts_empty(sample_folder):
    backup.make_daily_backup(sample_folder, "fukui", dt.date(2026, 11, 11))
    (sample_folder.users_dir / "fukui" / "weekly_notes.json").write_text("{", encoding="utf-8")
    repo = load_own(sample_folder, "fukui", readonly=False, ask=lambda *a: False)
    assert repo.weekly_notes == [] and len(repo.tasks) == 8


def test_connect_folder_retry_then_quit(tmp_path, monkeypatch):
    clicks = iter(["再試行", "終了"])

    class FakeBox:
        Warning = AcceptRole = ActionRole = RejectRole = 0

        def __init__(self, *a):
            self.buttons = {}

        def addButton(self, text, role):
            self.buttons[text] = object()
            return self.buttons[text]

        def setDefaultButton(self, b):
            pass

        def exec(self):
            self.choice = next(clicks)

        def clickedButton(self):
            return self.buttons[self.choice]

    monkeypatch.setattr(app_mod, "QMessageBox", FakeBox)
    assert app_mod.connect_folder(Settings(), str(tmp_path / "ない")) is None


def test_broken_categories_restored_at_startup(sample_folder):
    backup.make_daily_backup(sample_folder, "fukui", dt.date(2026, 11, 11))
    sample_folder.categories_path.write_text("{", encoding="utf-8")
    load_own(sample_folder, "fukui", readonly=False, ask=lambda *a: True)
    assert "治具" in sample_folder.category_colors()


def test_broken_categories_during_use_keeps_colors(win, sample_folder):
    before = dict(win.state.category_colors)
    sample_folder.categories_path.write_text("{", encoding="utf-8")
    win.btn_refresh.click()
    assert win.state.category_colors == before
