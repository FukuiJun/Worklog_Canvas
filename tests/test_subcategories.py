"""サブカテゴリ、タスク画面の入力欄の整理（日付2行・日常/定期は欄を減らす）、タスク一覧の右クリック。"""
import datetime as dt
import os

import pytest

from worklog_canvas.core import csv_import
from worklog_canvas.core.models import Category, Task, ValidationError
from worklog_canvas.core.repository import CategoryInUseError, DataFolder

D = dt.date


# --- データ ---
def test_category_subs_and_task_subcategory_saved(data_folder):
    data_folder.add_category(Category("設計", "#2A78D6"))
    assert data_folder.add_subcategory("設計", "回路") is True
    assert data_folder.add_subcategory("設計", "回路") is False  # 同名は増やさない
    data_folder.add_subcategory("設計", "基板")
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="回路図", category="設計", subcategory="回路"))
    again = DataFolder(data_folder.root)
    assert again.subcategories() == {"設計": ["回路", "基板"]}
    assert again.user("fukui").tasks[0].subcategory == "回路"
    # 古いデータ（サブカテゴリの項目なし）
    assert Category.from_dict({"カテゴリ名": "a", "色": "#000000"}).subs == []
    assert Task.from_dict({"id": "T-0001", "タスク名": "x"}).subcategory == ""


def test_subcategory_needs_category():
    with pytest.raises(ValidationError):
        Task(id="T-1", name="x", subcategory="回路").validate()


def test_rename_delete_subcategory_only_when_unused(data_folder):
    data_folder.add_category(Category("設計", "#2A78D6", ["回路", "基板"]))
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="回路図", category="設計", subcategory="回路"))
    with pytest.raises(CategoryInUseError):
        data_folder.rename_subcategory("設計", "回路", "電気", repo.tasks)
    with pytest.raises(CategoryInUseError):
        data_folder.delete_subcategory("設計", "回路", repo.tasks)
    data_folder.rename_subcategory("設計", "基板", "PCB", repo.tasks)
    with pytest.raises(ValidationError):
        data_folder.rename_subcategory("設計", "PCB", "回路", [])  # 既にある名前
    data_folder.delete_subcategory("設計", "PCB", repo.tasks)
    assert data_folder.subcategories() == {"設計": ["回路"]}
    with pytest.raises(KeyError):
        data_folder.add_subcategory("ない", "x")
    # カテゴリ名を変えてもサブカテゴリは付いていく
    data_folder.add_category(Category("試験", "#EB6834", ["温度"]))
    data_folder.rename_category("試験", "評価", [])
    assert data_folder.subcategories()["評価"] == ["温度"]


def test_csv_subcategory_column_adds_missing(data_folder, tmp_path):
    p = tmp_path / "t.csv"
    p.write_bytes("タスク名,カテゴリ,サブカテゴリ\n回路図,設計,回路\n基板図,設計,基板\nメモ,,\n".encode("utf-8"))
    r = csv_import.import_csv(p, data_folder, data_folder.user("fukui"))
    assert [(t.category, t.subcategory) for t in r.tasks] == [("設計", "回路"), ("設計", "基板"), ("", "")]
    assert data_folder.subcategories() == {"設計": ["回路", "基板"]}
    assert "設計 › 回路" in r.message()


def test_daily_task_has_no_status_priority_dates():
    t = Task(id="T-1", name="メール", task_type="日常", status="完了", priority="高",
             start_date=D(2026, 11, 1), done_date=D(2026, 11, 2))
    assert t.is_open  # 日常・定期タスクは完了させない
    t.clear_work_fields()
    assert (t.status, t.priority, t.start_date, t.done_date) == ("進行中", "中", None, None)


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
    data_folder.add_category(Category("設計", "#2A78D6", ["回路", "基板"]))
    data_folder.add_category(Category("試験", "#EB6834"))
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="回路図", category="設計", subcategory="回路", status="進行中"))
    repo.add_task(Task(id="", name="基板図", category="設計", subcategory="基板"))
    repo.add_task(Task(id="", name="温度試験", category="試験"))
    w = MainWindow(AppState(data_folder, repo, Settings(), today=lambda: D(2026, 11, 18)))
    w.show()
    yield w
    w.close()


def _dialog(win, kind="業務", task=None):
    from worklog_canvas.ui.task_dialog import TaskDialog
    return TaskDialog(win.state, task, win, task_type=kind)


def _items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_dialog_subcategory_follows_category(win):
    dlg = _dialog(win)
    assert not dlg.subcategory.isEnabled() and not dlg.btn_sub.isEnabled()  # カテゴリ（なし）
    dlg.category.setCurrentIndex(dlg.category.findData("設計"))
    assert dlg.subcategory.isEnabled() and _items(dlg.subcategory) == ["（なし）", "回路", "基板"]
    dlg.subcategory.setCurrentIndex(dlg.subcategory.findData("基板"))
    dlg.category.setCurrentIndex(dlg.category.findData("試験"))  # カテゴリを変えたら選び直し
    assert _items(dlg.subcategory) == ["（なし）"] and dlg.subcategory.currentData() == ""
    dlg.category.setCurrentIndex(dlg.category.findData("設計"))
    dlg.subcategory.setCurrentIndex(dlg.subcategory.findData("回路"))
    dlg.name.setText("配線")
    dlg._save()
    t = win.state.repo.tasks[-1]
    assert (t.category, t.subcategory) == ("設計", "回路")
    # 編集で開くと選ばれている
    dlg2 = _dialog(win, task=t)
    assert dlg2.subcategory.currentData() == "回路"


def test_dialog_new_subcategory(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("部品選定", True))
    dlg = _dialog(win)
    dlg.category.setCurrentIndex(dlg.category.findData("試験"))
    dlg._new_subcategory()
    assert dlg.subcategory.currentData() == "部品選定"
    assert win.state.subcategories["試験"] == ["部品選定"]


def test_dates_in_two_rows_and_hidden_for_daily(win):
    from PySide6.QtWidgets import QLabel
    work = _dialog(win, "業務")
    assert work.dates_row1.isAncestorOf(work.start_date) and work.dates_row1.isAncestorOf(work.planned_end)
    assert work.dates_row2.isAncestorOf(work.deadline) and work.dates_row2.isAncestorOf(work.done_date)
    assert [lb.text() for lb in work.dates_row1.findChildren(QLabel)] == ["完了予定日"]
    assert work.form.labelForField(work.dates_row1).text() == "開始日"
    assert work.form.labelForField(work.dates_row2).text() == "期限"
    for w in (work.status, work.priority, work.dates_row1, work.dates_row2):
        assert work.form.isRowVisible(w)
    for kind in ("日常", "定期"):
        dlg = _dialog(win, kind)
        for w in (dlg.status, dlg.priority, dlg.dates_row1, dlg.dates_row2, dlg.progress):
            assert not dlg.form.isRowVisible(w), kind
        assert dlg.form.isRowVisible(dlg.subcategory.parentWidget())


def test_save_daily_task_drops_status_priority_dates(win):
    dlg = _dialog(win, "日常")
    dlg.name.setText("メール対応")
    dlg.priority.setCurrentText("高")
    dlg.start_date.set_date(D(2026, 11, 1))
    dlg._save()
    t = win.state.repo.tasks[-1]
    assert (t.status, t.priority, t.start_date, t.done_date) == ("進行中", "中", None, None)
    tab = win.task_list
    tab.select_task(t.id)
    from worklog_canvas.ui.task_list_tab import COLUMNS
    row = tab.table.currentRow()
    assert tab.table.item(row, COLUMNS.index("ステータス")).text() == "—"
    assert tab.table.item(row, COLUMNS.index("優先度")).text() == "—"


def test_task_list_subcategory_column_and_filter(win):
    from worklog_canvas.ui.task_list_tab import COLUMNS
    tab = win.task_list
    tab.select_task("T-0001")
    assert tab.table.item(tab.table.currentRow(), COLUMNS.index("サブカテゴリ")).text() == "回路"
    assert _items(tab.f_category) == ["すべて", "設計", "　└ 回路", "　└ 基板", "試験", "（未分類）"]
    tab.f_category.setCurrentText("設計")
    assert [t.id for t in tab.filtered_tasks()] == ["T-0001", "T-0002"]
    tab.f_category.setCurrentText("　└ 基板")
    assert [t.id for t in tab.filtered_tasks()] == ["T-0002"]
    win.state.reload_categories()  # 作り直しても選択は残る
    assert tab.f_category.currentText() == "　└ 基板"


def _row_pos(tab, task_id):
    tab.select_task(task_id)
    r = tab.table.currentRow()
    return tab.table.visualItemRect(tab.table.item(r, 1)).center()


def test_task_list_right_click_menu(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from worklog_canvas.ui import task_list_tab as tlt
    tab = win.task_list
    tab.table.clearSelection()
    menu = tab.build_context_menu(_row_pos(tab, "T-0003"))
    assert [a.objectName() for a in menu.actions() if a.objectName()] == ["edit", "duplicate", "delete"]
    assert tab.selected_task_id() == "T-0003"  # 右クリックした行が選ばれる
    opened = []

    class FakeDialog:
        def __init__(self, state, task, parent=None, initial=None, task_type=None):
            opened.append((task.id if task else None, initial.name if initial else None))
            self.saved = None

        def exec(self):
            return 0

        def setWindowTitle(self, _t):
            pass

    monkeypatch.setattr(tlt, "TaskDialog", FakeDialog)
    actions = {a.objectName(): a for a in menu.actions()}
    actions["edit"].trigger()
    actions["duplicate"].trigger()
    assert opened == [("T-0003", None), (None, "温度試験（コピー）")]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    actions["delete"].trigger()
    assert "T-0003" not in {t.id for t in win.state.repo.tasks}
    # 行のないところでは出さない
    assert tab.build_context_menu(tab.table.viewport().rect().bottomRight()) is None


def test_settings_tree_shows_and_edits_subcategories(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    from worklog_canvas.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(win.state, win)
    top = {dlg.cat_list.topLevelItem(i).data(0, 0x0100): dlg.cat_list.topLevelItem(i)
           for i in range(dlg.cat_list.topLevelItemCount())}
    design = top["設計"]
    assert [design.child(i).text(0) for i in range(design.childCount())] == ["回路　（1 件）", "基板　（1 件）"]
    # 試験の下に追加
    dlg.cat_list.setCurrentItem(top["試験"])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("温度", True))
    dlg._add_subcategory()
    assert win.state.subcategories["試験"] == ["温度"]
    assert dlg._selected() == ("試験", "温度")
    # 使っていないサブカテゴリは名前の変更・削除ができる
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("湿度", True))
    dlg._rename_category()
    assert win.state.subcategories["試験"] == ["湿度"]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._delete_category()
    assert win.state.subcategories["試験"] == []
    # 使っているサブカテゴリは削除できない
    dlg._fill_categories(("設計", "回路"))
    dlg._delete_category()
    assert "使われているため" in dlg.cat_err.text()
    assert win.state.subcategories["設計"] == ["回路", "基板"]


def test_no_estimate_field_and_actual_hours_in_task_list(win):
    """予定工数は廃止。タスク一覧には、かかった時間（メイン時間の累計）を「実績時間」として出す。"""
    from worklog_canvas.core.models import Worklog
    from worklog_canvas.ui.task_list_tab import COLUMNS
    assert "予定工数" not in COLUMNS
    dlg = _dialog(win)
    assert not hasattr(dlg, "estimate")
    repo = win.state.repo
    repo.add_worklog(Worklog("", D(2026, 11, 16), 540, 630, task_id="T-0001"))
    repo.add_worklog(Worklog("", D(2026, 11, 17), 600, 645, task_id="T-0001"))
    win.state.tasks_changed.emit()
    tab = win.task_list
    col = COLUMNS.index("実績時間")
    tab.select_task("T-0001")
    assert tab.table.item(tab.table.currentRow(), col).text() == "2.25h"
    tab.select_task("T-0003")
    assert tab.table.item(tab.table.currentRow(), col).text() == ""


def test_priority_highest(win):
    from worklog_canvas.core import timeline as tl
    dlg = _dialog(win)
    assert list(dlg.priority.buttons) == ["最高", "高", "中", "低"]
    dlg.name.setText("至急")
    dlg.priority.setCurrentText("最高")
    dlg._save()
    t = win.state.repo.tasks[-1]
    assert t.priority == "最高"
    assert DataFolder(win.state.folder.root).user("fukui").get_task(t.id).priority == "最高"
    assert [x.id for x in tl.sort_open_tasks([Task("A", "a", priority="高"), Task("B", "b", priority="最高")])] == ["B", "A"]


def test_progress_bar_and_number_are_linked(win):
    p = _dialog(win).progress
    p.setValue(40)
    assert (p.slider.value(), p.spin.value()) == (8, 40)
    p.slider.setValue(13)
    assert p.spin.value() == 65 and p.value5() == 65
    p.spin.setValue(72)  # 数値で入力（5の倍数でなくても打てる）
    assert p.slider.value() == 14 and p.value5() == 70
    p.spin.editingFinished.emit()
    assert p.spin.value() == 70


def test_progress_typed_number_is_saved(win):
    t = win.state.repo.get_task("T-0001")
    dlg = _dialog(win, task=t)
    dlg.progress.spin.setValue(35)
    dlg._save()
    assert win.state.repo.get_task("T-0001").progress == 35


def test_calendar_hover_marks_the_day_under_mouse(win):
    """カレンダーでマウスを置いた日を淡く色づける。週の始まり（日曜・月曜）はPCの設定によらず正しく日付を求める。"""
    from PySide6.QtCore import QDate, QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QCalendarWidget
    from worklog_canvas.ui.widgets import _CalendarHover
    dlg = _dialog(win)
    popup_cal = dlg.start_date.edit.calendarWidget()
    assert any(isinstance(c, _CalendarHover) for c in popup_cal.children())  # 日付欄のカレンダーに付いている
    for first_day in (Qt.Sunday, Qt.Monday):
        cal = QCalendarWidget()
        cal.setFirstDayOfWeek(first_day)
        hover = _CalendarHover(cal)
        cal.setCurrentPage(2026, 11)
        cal.resize(360, 260)
        cal.show()
        QApplication.processEvents()
        view = hover.view
        days = []
        pos_of = {}
        for r in range(view.model().rowCount()):
            for c in range(view.model().columnCount()):
                pos = view.visualRect(view.model().index(r, c)).center()
                d = hover.date_at(pos)
                if d is not None:
                    days.append(d)
                    pos_of[d.toString("yyyy-MM-dd")] = pos
        # 42日が1日ずつ続き、前の月の末と次の月の初めも正しい日付になる
        assert len(days) == 42 and all(days[k].addDays(1) == days[k + 1] for k in range(41)), first_day
        assert {"2026-10-31", "2026-11-01", "2026-11-30", "2026-12-01"} <= set(pos_of)
        pos = pos_of["2026-11-12"]
        ev = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(view.viewport().mapToGlobal(pos)),
                         Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(view.viewport(), ev)
        assert hover.hovered == QDate(2026, 11, 12)
        assert cal.dateTextFormat(QDate(2026, 11, 12)).background().color().name().upper() == "#E3F2FB"
        QApplication.sendEvent(view.viewport(), QEvent(QEvent.Leave))
        assert hover.hovered is None and cal.dateTextFormat(QDate(2026, 11, 12)).background().style() == Qt.NoBrush
        cal.close()
        cal.deleteLater()
    QApplication.processEvents()
