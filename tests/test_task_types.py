"""タスクの種類（業務・日常・定期）: 保存、集計・週報・チームでの扱い、CSV、画面での追加。"""
import datetime as dt
import os

import pytest

from worklog_canvas.core import aggregate as ag
from worklog_canvas.core import csv_import, team
from worklog_canvas.core import recurring as rc
from worklog_canvas.core import weekly_report as wr
from worklog_canvas.core.models import KIND_TASK, Task, ValidationError, Worklog
from worklog_canvas.core.repository import DataFolder

D = dt.date
WEEK = D(2026, 11, 9)


def test_type_saved_and_old_data_defaults_to_work(data_folder):
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="メール対応", task_type="日常", status="進行中"))
    again = DataFolder(data_folder.root).user("fukui")
    assert again.tasks[0].task_type == "日常" and not again.tasks[0].is_work
    assert Task.from_dict({"id": "T-0001", "タスク名": "古い"}).task_type == "業務"
    with pytest.raises(ValidationError):
        Task(id="T-1", name="x", task_type="その他").validate()


def _with_routines(sample_folder):
    repo = sample_folder.user("fukui")
    mail = repo.add_task(Task(id="", name="メール対応", task_type="日常", status="進行中"))
    meet = repo.add_task(Task(id="", name="朝会", task_type="定期", status="進行中"))
    day = D(2026, 11, 14)  # 土曜（空いている日）
    repo.add_worklog(Worklog("", day, 540, 600, task_id=mail.id))
    repo.add_worklog(Worklog("", day, 600, 630, task_id=meet.id))
    return repo, mail, meet


def test_progress_rows_and_team_only_work_tasks(sample_folder):
    repo, mail, meet = _with_routines(sample_folder)
    rows = ag.progress_rows(repo.tasks, repo.worklogs, WEEK, WEEK + dt.timedelta(days=6), D(2026, 11, 12))
    assert mail.id not in {r.task.id for r in rows} and meet.id not in {r.task.id for r in rows}
    assert all(t.is_work for t in team.in_progress_tasks(repo.tasks))
    # 時間の集計（タスク別時間・稼働時間）には入る
    s = ag.period_summary(repo.worklogs, repo.tasks, WEEK, WEEK + dt.timedelta(days=6))
    assert s.by_task[mail.id] == 60 and s.by_task[meet.id] == 30


def test_weekly_report_routines_in_separate_table(sample_folder, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    repo, mail, meet = _with_routines(sample_folder)
    rep = wr.build_report(repo.tasks, repo.worklogs, None, "福井", WEEK, D(2026, 11, 13))
    assert len(rep.rows) == 5 and all(r.task_id not in (mail.id, meet.id) for r in rep.rows)  # 業務タスクだけ
    assert [(r.task_type, r.name, r.week_main) for r in rep.routines] == [("日常", "メール対応", 60), ("定期", "朝会", 30)]
    assert rep.in_progress_count == 3  # 業務タスクだけ数える
    assert all("朝会" not in line for line in rep.next_week.splitlines())
    text = wr.report_text(rep)
    assert "■日常・定期の作業" in text and "・[日常] メール対応　今週 1.0h" in text
    ws = openpyxl.load_workbook(wr.write_xlsx(rep, tmp_path / "w.xlsx")).active
    cells = [ws.cell(r, c).value for r in range(1, ws.max_row + 1) for c in (1, 2)]
    assert "日常・定期の作業" in cells and "メール対応" in cells


def test_csv_type_column(data_folder, tmp_path):
    p = tmp_path / "t.csv"
    p.write_bytes("タスク名,種類,完了予定日\n報告書,,2026-11-20\nメール対応,日常,2026-11-20\n朝会,定期,\n".encode("utf-8"))
    r = csv_import.import_csv(p, data_folder, data_folder.user("fukui"))
    assert [(t.name, t.task_type, t.planned_end) for t in r.tasks] == [
        ("報告書", "業務", D(2026, 11, 20)), ("メール対応", "日常", None)]  # 日常は日付を持たない
    assert [n for n, _ in r.skipped] == [4]  # 定期は画面から登録


def test_deleting_recurring_task_removes_its_time_slots(data_folder):
    repo = data_folder.user("fukui")
    t = repo.add_task(Task(id="", name="朝会", task_type="定期", status="進行中"))
    repo.add_recurring(rc.RecurringItem(id="", start=540, end=570, kind=KIND_TASK, task_id=t.id, weekdays=[0],
                                        start_date=D(2026, 11, 2)))
    repo.delete_task(t.id)
    assert DataFolder(data_folder.root).user("fukui").recurring == []


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
    w = MainWindow(AppState(data_folder, repo, Settings(), today=lambda: D(2026, 11, 18)))
    w.show()
    yield w
    w.close()


def test_add_menu_has_three_types(win):
    names = [a.objectName() for a in win.task_list.add_menu.actions()]
    assert names == ["業務", "日常", "定期"]
    assert [a.text().split("　")[0] for a in win.task_list.add_menu.actions()] == ["業務タスク", "日常タスク", "定期タスク"]


def _dialog(win, kind):
    from worklog_canvas.ui.task_dialog import TaskDialog
    return TaskDialog(win.state, None, win, task_type=kind)


def test_dialog_fields_per_type(win):
    work = _dialog(win, "業務")
    assert work.windowTitle() == "業務タスクの追加"
    assert work.form.isRowVisible(work.progress) and work.recurrence_box.isHidden()
    daily = _dialog(win, "日常")
    assert daily.windowTitle() == "日常タスクの追加" and daily.status.currentText() == "進行中"
    assert not daily.form.isRowVisible(daily.progress) and not daily.form.isRowVisible(daily.deadline)
    rec = _dialog(win, "定期")
    assert not rec.recurrence_box.isHidden()


def test_save_daily_task_clears_work_fields(win):
    dlg = _dialog(win, "日常")
    dlg.name.setText("メール対応")
    dlg.progress.setValue(50)  # 隠れている欄の値は保存しない
    dlg.planned_end.set_date(D(2026, 11, 30))
    dlg._save()
    t = win.state.repo.tasks[-1]
    assert (t.task_type, t.progress, t.planned_end, t.history) == ("日常", 0, None, [])
    tab = win.task_list
    tab.refresh()
    tab.select_task(t.id)
    row = tab.table.currentRow()
    assert tab.table.item(row, 2).text() == "日常"
    from worklog_canvas.ui.task_list_tab import COLUMNS
    progress_col = COLUMNS.index("進捗率")
    assert tab.table.cellWidget(row, progress_col) is None  # スライダーなし
    assert tab.table.item(row, progress_col).text() == "—"
    tab.f_type.setCurrentText("日常")
    assert [x.id for x in tab.filtered_tasks()] == [t.id]


def test_save_recurring_task_creates_time_slot_and_edit_updates_it(win):
    dlg = _dialog(win, "定期")
    dlg.name.setText("朝会")
    f = dlg.recurrence
    f.start.set_minutes(540)
    f.end.set_minutes(570)
    for i, cb in enumerate(f.day_checks):
        cb.setChecked(i in (0, 3))
    dlg._save()
    t = win.state.repo.tasks[-1]
    [it] = win.state.repo.recurring_of(t.id)
    assert (t.task_type, it.start, it.end, it.weekdays, it.kind) == ("定期", 540, 570, [0, 3], "タスク")
    # 編集: 同じ時間帯を書き換える（増やさない）
    from worklog_canvas.ui.task_dialog import TaskDialog
    dlg2 = TaskDialog(win.state, t, win)
    assert dlg2.recurrence.start.minutes() == 540
    dlg2.recurrence.end.set_minutes(600)
    dlg2._save()
    [it2] = win.state.repo.recurring_of(t.id)
    assert (it2.id, it2.end) == (it.id, 600)
    # 種類を日常に変えたら、繰り返しの時間帯は消える
    dlg3 = TaskDialog(win.state, win.state.repo.get_task(t.id), win)
    dlg3.task_type.setCurrentIndex(dlg3.task_type.findData("日常"))
    dlg3._save()
    assert win.state.repo.recurring_of(t.id) == []


def test_recurring_validation_before_creating_task(win):
    dlg = _dialog(win, "定期")
    dlg.name.setText("朝会")
    for cb in dlg.recurrence.day_checks:
        cb.setChecked(False)
    dlg._save()
    assert dlg.err.text() == "曜日を1つ以上選んでください"
    assert all(t.name != "朝会" for t in win.state.repo.tasks)  # タスクも作らない
