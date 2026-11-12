"""タイムライン操作の計算（F-02、Q-11〜Q-13）と取り消し。"""
import datetime as dt

import pytest

from worklog_canvas.core import timeline as tl
from worklog_canvas.core.models import KIND_ONEOFF, KIND_TASK, SubItem, Task, Worklog
from worklog_canvas.core.overlap import OverlapError
from worklog_canvas.core.undo import WorklogEditor

DAY = dt.date(2026, 11, 16)


def h(text):
    a, b = text.split(":")
    return int(a) * 60 + int(b)


def W(i, s, e, **kw):
    return Worklog(f"W-{i}", DAY, h(s), h(e), kind=kw.pop("kind", KIND_ONEOFF), title=kw.pop("title", "x"), **kw)


def test_create_range_snaps_and_sorts():
    assert tl.create_range(h("10:03"), h("11:58")) == (h("10:00"), h("12:00"))
    assert tl.create_range(h("12:00"), h("10:00")) == (h("10:00"), h("12:00"))  # 上へドラッグ
    assert tl.create_range(h("10:00"), h("10:07")) is None  # 15分未満


def test_resize_ac04_snaps_to_quarter():
    w = W(1, "10:00", "12:00")
    assert tl.resized_bottom(w, h("12:07")).end == h("12:00")
    assert tl.resized_bottom(w, h("12:08")).end == h("12:15")
    assert tl.resized_bottom(w, h("09:00")).end == h("10:15")  # 最短15分
    assert tl.resized_top(w, h("09:52")).start == h("09:45")
    assert tl.resized_top(w, h("13:00")).start == h("11:45")
    assert w.end == h("12:00")  # 元は変えない


def test_move_keeps_duration_and_changes_day():
    w = W(1, "10:00", "12:00", subs=[SubItem(KIND_ONEOFF, title="a")])
    m = tl.moved(w, DAY + dt.timedelta(days=2), h("13:08"))
    assert (m.date, m.start, m.end) == (DAY + dt.timedelta(days=2), h("13:15"), h("15:15"))
    assert tl.moved(w, DAY, h("23:30")).end == 24 * 60
    m.subs.append(SubItem(KIND_ONEOFF, title="b"))
    assert len(w.subs) == 1  # サブタスクの一覧は共有しない


def test_drop_q11_on_bar_adds_sub():
    bars = [W(1, "10:00", "12:00")]
    assert tl.resolve_drop(bars, h("11:00")) == tl.DropOnBar("W-1")
    assert tl.resolve_drop(bars, h("10:00")) == tl.DropOnBar("W-1")


def test_drop_q12_one_hour_or_until_next_bar():
    bars = [W(1, "10:00", "12:00"), W(2, "13:30", "14:00")]
    assert tl.resolve_drop(bars, h("08:10")) == tl.DropCreate(h("08:15"), h("09:15"))
    assert tl.resolve_drop(bars, h("12:00")) == tl.DropCreate(h("12:00"), h("13:00"))
    assert tl.resolve_drop(bars, h("12:50")) == tl.DropCreate(h("12:45"), h("13:30"))  # 手前まで
    assert tl.resolve_drop(bars, h("09:55")) == tl.DropCreate(h("09:45"), h("10:00"))  # 吸着で入らないよう手前へ
    assert tl.resolve_drop([W(1, "10:00", "12:00"), W(2, "12:10", "13:00")], h("12:05")) is None  # 15分未満
    assert tl.resolve_drop([], h("23:40")) == tl.DropCreate(h("23:45"), 24 * 60)


def test_popup_candidates():
    tasks = [Task("T-0001", "治具作成", category="治具", status="保留"),
             Task("T-0002", "マイコン評価", status="進行中", priority="低"),
             Task("T-0003", "完了したもの", status="完了"),
             Task("T-0004", "回路図レビュー", priority="高")]
    open_ = tl.sort_open_tasks(tasks)
    assert [t.id for t in open_] == ["T-0002", "T-0004", "T-0001"]
    assert [t.id for t in tl.filter_tasks(open_, " 治具 ")] == ["T-0001"]
    assert [t.id for t in tl.filter_tasks(open_, "")] == ["T-0002", "T-0004", "T-0001"]
    assert tl.filter_tasks(open_, "製造応援") == []


def test_visible_dates():
    assert tl.visible_dates(dt.date(2026, 11, 12), "day") == [dt.date(2026, 11, 12)]
    week = tl.visible_dates(dt.date(2026, 11, 12), "week")
    assert week[0] == dt.date(2026, 11, 9) and week[-1] == dt.date(2026, 11, 15)
    assert tl.step_anchor(dt.date(2026, 11, 12), "week", -1) == dt.date(2026, 11, 5)


def test_labels():
    tasks = {"T-0001": Task("T-0001", "A")}
    w = Worklog("W-1", DAY, 600, 720, task_id="T-0001",
                subs=[SubItem(KIND_ONEOFF, title="会議"), SubItem(KIND_TASK, "T-0404")])
    assert tl.main_label(w, tasks) == "A"
    assert tl.sub_labels(w, tasks) == ["会議", "（不明なタスク T-0404）"]


# --- 取り消し（Ctrl+Z） ---
def test_undo_add_update_delete(data_folder):
    repo = data_folder.user("fukui")
    t = repo.add_task(Task(id="", name="A"))
    ed = WorklogEditor(repo)
    a = ed.add(Worklog("", DAY, 600, 720, task_id=t.id))
    from dataclasses import replace
    ed.update(replace(a, end=780), "伸縮")
    ed.delete(a.id)
    assert repo.worklogs == []
    assert ed.undo() == "削除"
    assert repo.get_worklog(a.id).end == 780
    assert ed.undo() == "伸縮"
    assert repo.get_worklog(a.id).end == 720
    assert ed.undo() == "作成"
    assert repo.worklogs == [] and ed.undo() is None
    assert data_folder.user("fukui").worklogs == []  # 保存もされている


def test_undo_failed_operation_is_not_recorded(data_folder):
    repo = data_folder.user("fukui")
    ed = WorklogEditor(repo)
    ed.add(Worklog("", DAY, 600, 720, kind=KIND_ONEOFF, title="a"))
    with pytest.raises(OverlapError):
        ed.add(Worklog("", DAY, 660, 690, kind=KIND_ONEOFF, title="b"))
    assert len(ed) == 1


def test_undo_keeps_last_20(data_folder):
    repo = data_folder.user("fukui")
    ed = WorklogEditor(repo)
    for i in range(25):
        ed.add(Worklog("", DAY, i * 30, i * 30 + 15, kind=KIND_ONEOFF, title=f"{i}"))
    assert len(ed) == 20
    for _ in range(20):
        ed.undo()
    assert len(repo.worklogs) == 5 and ed.undo() is None


def test_undo_does_not_alias_repository_objects(data_folder):
    repo = data_folder.user("fukui")
    ed = WorklogEditor(repo)
    w = ed.add(Worklog("", DAY, 600, 720, kind=KIND_ONEOFF, title="a"))
    repo.get_worklog(w.id).title = "書き換え"  # 画面側が誤って直接書き換えても
    ed.undo()
    assert repo.worklogs == []
