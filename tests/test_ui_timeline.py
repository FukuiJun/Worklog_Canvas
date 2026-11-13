"""画面の自動確認（offscreen）。AC-03/04/06/07 は手動確認が正式だが、同じ操作をイベントで再現して確かめる。"""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from worklog_canvas.core import timeline as tl  # noqa: E402
from worklog_canvas.core.colors import ONEOFF_COLOR  # noqa: E402
from worklog_canvas.core.models import KIND_ONEOFF, KIND_TASK, Task, Worklog  # noqa: E402
from worklog_canvas.core.settings import Settings  # noqa: E402
from worklog_canvas.ui.app import MainWindow  # noqa: E402
from worklog_canvas.ui.entry_popup import EntryPopup  # noqa: E402
from worklog_canvas.ui.state import AppState  # noqa: E402

MONDAY = dt.date(2026, 11, 16)
TODAY = dt.date(2026, 11, 18)  # 水曜


def h(text):
    a, b = text.split(":")
    return int(a) * 60 + int(b)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, data_folder):
    repo = data_folder.user("fukui")
    data_folder.add_category(__import__("worklog_canvas.core.models", fromlist=["Category"]).Category("治具", "#F28E2B"))
    repo.add_task(Task(id="", name="治具の作成", category="治具", status="進行中"))
    repo.add_task(Task(id="", name="回路図レビュー"))
    state = AppState(data_folder, repo, Settings(), today=lambda: TODAY)
    w = MainWindow(state)
    w.resize(1280, 760)
    w.show()
    w.timeline.set_mode("week")
    w.timeline.go_today()
    qapp.processEvents()
    yield w
    w.close()


def _pt(canvas, col, minutes):
    return QPointF(canvas.col_x(col) + canvas.col_width() / 2, canvas.y_of(minutes))


def _mouse(canvas, kind, pos, buttons=Qt.LeftButton):
    ev = QMouseEvent(kind, pos, canvas.mapToGlobal(pos), Qt.LeftButton, buttons, Qt.NoModifier)
    QApplication.sendEvent(canvas, ev)


def drag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    mid = QPointF(a.x(), (a.y() + b.y()) / 2)
    _mouse(canvas, QEvent.MouseMove, mid)
    _mouse(canvas, QEvent.MouseMove, b)
    _mouse(canvas, QEvent.MouseButtonRelease, b, Qt.NoButton)


def with_popup(action):
    """作成ドラッグの後に開く入力ポップアップを操作する。"""
    def run():
        popups = [w for w in QApplication.topLevelWidgets() if isinstance(w, EntryPopup) and w.isVisible()]
        assert popups, "入力ポップアップが開いていない"
        action(popups[0])
    QTimer.singleShot(0, run)


def test_ac03_drag_creates_2h_bar_and_assigns_task(win):
    c = win.timeline.canvas
    with_popup(lambda p: (QTest.keyClick(p.edit, Qt.Key_Down), QTest.keyClick(p.list, Qt.Key_Return)))
    drag(c, _pt(c, 0, h("10:00")), _pt(c, 0, h("12:00")))
    [w] = win.state.repo.worklogs
    assert (w.date, w.start, w.end, w.duration) == (MONDAY, h("10:00"), h("12:00"), 120)
    assert w.kind == KIND_TASK and w.task_id == "T-0001"  # 先頭の候補（進行中のタスク）
    assert win.state.worklog_color(w) == "#F28E2B"


def test_ac04_resize_bottom_to_1207_snaps(win):
    repo, c = win.state.repo, win.timeline.canvas
    w = win.state.editor.add(Worklog("", MONDAY, h("10:00"), h("12:00"), task_id="T-0001"))
    drag(c, _pt(c, 0, h("12:00")) - QPointF(0, 2), _pt(c, 0, h("12:07")))
    assert repo.get_worklog(w.id).end in (h("12:00"), h("12:15"))
    drag(c, _pt(c, 0, h("12:00")) - QPointF(0, 2), _pt(c, 0, h("12:09")))
    assert repo.get_worklog(w.id).end == h("12:15")


def test_ac06_typed_title_creates_gray_oneoff(win):
    c = win.timeline.canvas
    with_popup(lambda p: (p.edit.insert("製造応援"), QTest.keyClick(p.edit, Qt.Key_Return)))
    drag(c, _pt(c, 1, h("13:00")), _pt(c, 1, h("15:00")))
    [w] = win.state.repo.worklogs
    assert (w.kind, w.title, w.date) == (KIND_ONEOFF, "製造応援", MONDAY + dt.timedelta(days=1))
    assert win.state.worklog_color(w) == ONEOFF_COLOR


def test_popup_esc_cancels(win):
    c = win.timeline.canvas
    with_popup(lambda p: QTest.keyClick(p.edit, Qt.Key_Escape))
    drag(c, _pt(c, 0, h("10:00")), _pt(c, 0, h("11:00")))
    assert win.state.repo.worklogs == []


def test_popup_filter_then_click_candidate(win):
    c = win.timeline.canvas

    def act(p):
        p.edit.insert("回路")
        assert p.list.count() == 1
        p.list.itemClicked.emit(p.list.item(0))
    with_popup(act)
    drag(c, _pt(c, 0, h("10:00")), _pt(c, 0, h("11:00")))
    assert win.state.repo.worklogs[0].task_id == "T-0002"


def test_ac07_drop_task_on_bar_adds_subtask(win):
    c = win.timeline.canvas
    w = win.state.editor.add(Worklog("", MONDAY, h("10:00"), h("12:00"), task_id="T-0001"))
    date, res = c._drop_info(_pt(c, 0, h("11:00")))
    assert res == tl.DropOnBar(w.id)
    c.drop_task("T-0002", date, res)
    got = win.state.repo.get_worklog(w.id)
    assert [s.task_id for s in got.subs] == ["T-0002"]
    assert tl.sub_labels(got, win.state.tasks_by_id()) == ["回路図レビュー"]
    c.drop_task("T-0001", date, res)  # メインと同じタスクは拒否
    assert len(win.state.repo.get_worklog(w.id).subs) == 1
    assert "同じタスク" in win.message.text()


def test_drop_on_empty_creates_one_hour(win):
    c = win.timeline.canvas
    win.state.editor.add(Worklog("", MONDAY, h("10:30"), h("12:00"), kind=KIND_ONEOFF, title="会議"))
    date, res = c._drop_info(_pt(c, 0, h("09:00")))
    c.drop_task("T-0002", date, res)
    date, res = c._drop_info(_pt(c, 0, h("12:00")))
    c.drop_task("T-0002", date, res)
    spans = [(w.start, w.end) for w in win.state.repo.worklogs_on(MONDAY)]
    assert spans == [(h("09:00"), h("10:00")), (h("10:30"), h("12:00")), (h("12:00"), h("13:00"))]


def test_q13_drag_over_existing_bar_is_rejected(win):
    c = win.timeline.canvas
    win.state.editor.add(Worklog("", MONDAY, h("11:00"), h("12:00"), kind=KIND_ONEOFF, title="会議"))
    drag(c, _pt(c, 0, h("10:00")), _pt(c, 0, h("11:30")))  # ポップアップは開かない
    assert len(win.state.repo.worklogs) == 1
    assert "すでに作業バー" in win.message.text()


def test_move_across_days_and_overlap_rejected(win):
    repo, c = win.state.repo, win.timeline.canvas
    a = win.state.editor.add(Worklog("", MONDAY, h("10:00"), h("11:00"), kind=KIND_ONEOFF, title="a"))
    b = win.state.editor.add(Worklog("", MONDAY + dt.timedelta(days=2), h("10:00"), h("11:00"),
                                     kind=KIND_ONEOFF, title="b"))
    drag(c, _pt(c, 0, h("10:30")), _pt(c, 1, h("14:30")))  # 火曜 14:00〜15:00 へ
    got = repo.get_worklog(a.id)
    assert (got.date, got.start, got.end) == (MONDAY + dt.timedelta(days=1), h("14:00"), h("15:00"))
    drag(c, _pt(c, 1, h("14:30")), _pt(c, 2, h("10:45")))  # 水曜の b に重なる → 戻す
    got = repo.get_worklog(a.id)
    assert (got.date, got.start) == (MONDAY + dt.timedelta(days=1), h("14:00"))
    assert repo.get_worklog(b.id).start == h("10:00")


def test_delete_key_and_ctrl_z(win, qapp):
    c = win.timeline.canvas
    w = win.state.editor.add(Worklog("", MONDAY, h("10:00"), h("11:00"), kind=KIND_ONEOFF, title="a"))
    _mouse(c, QEvent.MouseButtonPress, _pt(c, 0, h("10:30")))
    _mouse(c, QEvent.MouseButtonRelease, _pt(c, 0, h("10:30")), Qt.NoButton)
    assert c.selected_id == w.id
    QTest.keyClick(c, Qt.Key_Delete)
    assert win.state.repo.worklogs == []
    win._undo()
    assert win.state.repo.get_worklog(w.id).title == "a"
    assert "元に戻しました" in win.message.text()


def test_readonly_blocks_editing(win):
    c = win.timeline.canvas
    w = win.state.editor.add(Worklog("", MONDAY, h("10:00"), h("11:00"), kind=KIND_ONEOFF, title="a"))
    win.state.repo.readonly = True
    drag(c, _pt(c, 0, h("10:30")), _pt(c, 0, h("13:30")))
    drag(c, _pt(c, 0, h("14:00")), _pt(c, 0, h("15:00")))
    QTest.keyClick(c, Qt.Key_Delete)
    assert [(x.id, x.start) for x in win.state.repo.worklogs] == [(w.id, h("10:00"))]


def test_footer_shows_working_hours(win):
    win.state.editor.add(Worklog("", MONDAY, h("10:00"), h("12:00"), task_id="T-0001"))
    win.state.worklogs_changed.emit()
    texts = [t for t, _ in win.timeline.footer.texts()]
    assert texts[0] == "稼働 2.0h" and texts[1] == "—"
    assert win.windowTitle() == "Worklog Canvas"
    assert (win.minimumWidth(), win.minimumHeight()) == (1280, 720)


# --- タスク一覧画面 ---
def test_task_dialog_rejects_empty_name(win):
    from worklog_canvas.ui.task_dialog import TaskDialog
    dlg = TaskDialog(win.state, None, win)
    dlg.name.setText("   ")
    dlg._save()
    assert not dlg.name_err.isHidden() and dlg.name_err.text() == "タスク名を入力してください"
    assert len(win.state.repo.tasks) == 2
    dlg.name.setText("新しいタスク")
    dlg.status.setCurrentText("完了")
    assert dlg.done_date.date() == TODAY  # 完了日の自動入力
    dlg._save()
    t = win.state.repo.tasks[-1]
    assert (t.name, t.status, t.done_date) == ("新しいタスク", "完了", TODAY)


def test_task_delete_converts_bars(win, monkeypatch):
    tab = win.task_list
    win.state.editor.add(Worklog("", MONDAY, h("10:00"), h("11:00"), task_id="T-0001"))
    tab.select_task("T-0001")
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    tab.delete_selected()
    assert "1 件の作業バー" in asked[0]
    [w] = win.state.repo.worklogs
    assert (w.kind, w.title) == (KIND_ONEOFF, "治具の作成")
    assert not win.state.editor.can_undo


def test_task_list_overdue_colors_and_filters(win):
    repo = win.state.repo
    repo.add_task(Task(id="", name="遅れ", planned_end=dt.date(2026, 11, 1), deadline=dt.date(2026, 11, 2)))
    repo.add_task(Task(id="", name="完了済み", status="完了", deadline=dt.date(2026, 11, 2)))
    win.state.tasks_changed.emit()
    tab = win.task_list
    tab.select_task("T-0003")
    row = tab.table.currentRow()
    assert tab.table.item(row, 6).foreground().color().name().upper() == "#E67E22"
    assert tab.table.item(row, 7).foreground().color().name().upper() == "#D32F2F"
    tab.select_task("T-0004")
    row = tab.table.currentRow()
    assert tab.table.item(row, 7).foreground().color().name().upper() != "#D32F2F"  # 完了は色を付けない
    tab.f_status.setCurrentText("未完了")
    assert {t.id for t in tab.filtered_tasks()} == {"T-0001", "T-0002", "T-0003"}
    tab.f_status.setCurrentText("すべて")
    tab.f_category.setCurrentText("治具")
    assert [t.id for t in tab.filtered_tasks()] == ["T-0001"]
    tab.f_category.setCurrentText("（未分類）")
    assert "T-0001" not in {t.id for t in tab.filtered_tasks()}
