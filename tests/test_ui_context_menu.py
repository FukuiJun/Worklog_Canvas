"""タイムラインの右クリック: 既存タスク・一時タスク・新しいタスク・定期タスクの追加と、定期の予定の記録。"""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from worklog_canvas.core import recurring as rc  # noqa: E402
from worklog_canvas.core.models import KIND_ONEOFF, KIND_TASK, Task  # noqa: E402
from worklog_canvas.core.settings import Settings  # noqa: E402
from worklog_canvas.ui import recurring_dialog, task_dialog  # noqa: E402
from worklog_canvas.ui.app import MainWindow  # noqa: E402
from worklog_canvas.ui.state import AppState  # noqa: E402

TODAY = dt.date(2026, 11, 18)  # 水曜（11/16の週）
MON = dt.date(2026, 11, 16)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, data_folder, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOG_CANVAS_HOME", str(tmp_path / "home"))
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="治具の作成", status="進行中"))
    repo.add_task(Task(id="", name="回路図レビュー"))
    state = AppState(data_folder, repo, Settings(), today=lambda: TODAY)
    w = MainWindow(state)
    w.resize(1280, 800)
    w.show()
    w.timeline.set_mode("week")
    w.timeline.go_today()
    qapp.processEvents()
    yield w
    w.close()


def _pt(c, col, minutes):
    return QPointF(c.col_x(col) + c.col_width() / 2, c.y_of(minutes))


def _action(menu, name):
    for a in menu.actions():
        if a.objectName() == name:
            return a
    raise KeyError(name)


def test_menu_on_empty_area_lists_four_kinds(win):
    c = win.timeline.canvas
    menu = c.build_context_menu(_pt(c, 0, 10 * 60 + 5))
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts[0] == "ここに追加（11/16 10:00〜11:00）"
    assert texts[1:] == ["既存タスク", "一時タスク（単発作業）…", "新しいタスクを作って追加…", "定期タスクとして登録…"]
    existing = next(a for a in menu.actions() if a.text() == "既存タスク").menu()
    assert [a.text() for a in existing.actions()] == ["治具の作成", "回路図レビュー"]


def test_add_existing_task(win):
    c = win.timeline.canvas
    menu = c.build_context_menu(_pt(c, 0, 10 * 60))
    existing = next(a for a in menu.actions() if a.text() == "既存タスク").menu()
    existing.actions()[1].trigger()
    [w] = win.state.repo.worklogs
    assert (w.date, w.start, w.end, w.kind, w.task_id) == (MON, 600, 660, KIND_TASK, "T-0002")


def test_add_oneoff(win, monkeypatch):
    c = win.timeline.canvas
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("製造応援", True))
    _action(c.build_context_menu(_pt(c, 1, 13 * 60)), "oneoff").trigger()
    [w] = win.state.repo.worklogs
    assert (w.date, w.start, w.kind, w.title) == (MON + dt.timedelta(days=1), 780, KIND_ONEOFF, "製造応援")


def test_add_new_task_then_bar(win, monkeypatch):
    c = win.timeline.canvas

    def fake_exec(dlg):
        dlg.name.setText("新しく作ったタスク")
        dlg._save()
        return 1
    monkeypatch.setattr(task_dialog.TaskDialog, "exec", fake_exec)
    _action(c.build_context_menu(_pt(c, 2, 9 * 60)), "new_task").trigger()
    t = win.state.repo.tasks[-1]
    assert t.name == "新しく作ったタスク"
    [w] = win.state.repo.worklogs
    assert (w.task_id, w.start) == (t.id, 540)


def test_register_recurring_from_menu_then_confirm(win, monkeypatch, data_folder):
    c = win.timeline.canvas

    def fake_exec(dlg):
        assert dlg.day_checks[0].isChecked()  # 右クリックした曜日（月）が初期値
        assert dlg.start.minutes() == 540
        dlg.rb_oneoff.setChecked(True)
        dlg.title.setText("朝会")
        dlg.end.set_minutes(570)
        dlg._save()
        return 1
    monkeypatch.setattr(recurring_dialog.RecurringDialog, "exec", fake_exec)
    _action(c.build_context_menu(_pt(c, 0, 9 * 60)), "recurring").trigger()
    [it] = win.state.repo.recurring
    assert (it.pattern, it.weekdays, it.start, it.end, it.title) == (rc.WEEKLY, [0], 540, 570, "朝会")
    # 定期の予定として表示される（作業バーにはまだならない）
    assert win.state.repo.worklogs == []
    occ = c.occurrence_at(_pt(c, 0, 9 * 60 + 15))
    assert occ is not None and occ.date == MON
    _action(c.build_context_menu(_pt(c, 0, 9 * 60 + 15)), "confirm").trigger()
    [w] = win.state.repo.worklogs
    assert (w.date, w.start, w.end, w.title, w.source) == (MON, 540, 570, "朝会", "定期")
    assert c.occurrence_at(_pt(c, 0, 9 * 60 + 15)) is None  # 記録したら予定は消える（作業バーが代わりに出る）
    win._undo()
    assert win.state.repo.worklogs == [] and c.occurrence_at(_pt(c, 0, 9 * 60 + 15)) is not None


def test_confirm_all_in_view(win, monkeypatch):
    c = win.timeline.canvas
    repo = win.state.repo
    repo.add_recurring(rc.RecurringItem(id="", start=540, end=570, pattern=rc.DAILY_WEEKDAYS, kind=KIND_ONEOFF,
                                        title="朝会", start_date=dt.date(2026, 11, 1)))
    from worklog_canvas.core.models import Worklog
    win.state.editor.add(Worklog("", MON + dt.timedelta(days=2), 540, 600, kind=KIND_ONEOFF, title="別の作業"))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    assert c.confirm_all_occurrences() == 4  # 平日5日のうち、水曜は作業バーがあるので出ていない
    assert "4 件" in asked[0]
    assert sorted(w.date.day for w in repo.worklogs if w.source == "定期") == [16, 17, 19, 20]


def test_menu_on_bar_and_readonly(win):
    c = win.timeline.canvas
    c.add_task_bar("T-0001", MON, 600, 660)
    menu = c.build_context_menu(_pt(c, 0, 630))
    assert [a.objectName() for a in menu.actions()] == ["edit", "delete"]
    win.state.repo.readonly = True
    assert c.build_context_menu(_pt(c, 0, 900)) is None


def test_short_gap_offers_until_next_bar(win):
    c = win.timeline.canvas
    c.add_task_bar("T-0001", MON, 600, 660)
    c.add_task_bar("T-0002", MON, 675, 720)  # 11:00〜11:15 だけ空いている
    menu = c.build_context_menu(_pt(c, 0, 662))
    assert menu.actions()[0].text() == "ここに追加（11/16 11:00〜11:15）"
    assert _action(menu, "oneoff").isEnabled()


def test_recurring_hidden_when_viewing_other(win, sample_folder):
    repo = win.state.repo
    repo.add_recurring(rc.RecurringItem(id="", start=540, end=570, pattern=rc.DAILY_WEEKDAYS, kind=KIND_ONEOFF,
                                        title="朝会", start_date=dt.date(2026, 11, 1)))
    assert win.timeline.canvas.occurrences()
    from worklog_canvas.core.repository import DataFolder
    other = DataFolder(win.state.folder.root).user("fukui", readonly=True)
    win.state.switch_to(other)
    assert win.timeline.canvas.occurrences() == []
