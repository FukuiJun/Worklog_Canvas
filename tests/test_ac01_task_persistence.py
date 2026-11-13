"""AC-01: タスクを追加・編集・削除し、再起動後も同じ内容が表示される（F-01, F-07）。"""
import datetime as dt
from dataclasses import replace

import pytest

from worklog_canvas.core.models import KIND_ONEOFF, KIND_TASK, SubItem, Task, ValidationError, Worklog
from worklog_canvas.core.repository import DataFolder


def _restart(folder: DataFolder, user="fukui"):
    """「再起動」= 新しいインスタンスでファイルから読み直す。"""
    return DataFolder(folder.root).user(user)


def test_ac01_add_edit_delete_survive_restart(data_folder):
    repo = data_folder.user("fukui")
    a = repo.add_task(Task(id="", name="タスクA", category="治具", priority="高",
                           planned_end=dt.date(2026, 11, 20), deadline=dt.date(2026, 11, 30),
                           estimate_hours=16.0, memo="1行目\n2行目"))
    b = repo.add_task(Task(id="", name="タスクB"))
    c = repo.add_task(Task(id="", name="タスクC"))
    assert [a.id, b.id, c.id] == ["T-0001", "T-0002", "T-0003"]

    # 編集
    b2 = replace(b, name="タスクB（改）", status="進行中", start_date=dt.date(2026, 11, 2))
    repo.update_task(b2)
    # 削除
    repo.delete_task(c.id)

    expected = [t.to_dict() for t in repo.tasks]
    again = _restart(data_folder)
    assert [t.to_dict() for t in again.tasks] == expected
    assert [t.name for t in again.tasks] == ["タスクA", "タスクB（改）"]
    assert again.get_task("T-0001").memo == "1行目\n2行目"
    assert again.get_task("T-0001").estimate_hours == 16.0

    # 削除済みの番号は再利用しない
    d = again.add_task(Task(id="", name="タスクD"))
    assert d.id == "T-0004"


def test_ac01_files_are_utf8_without_bom_and_lf(data_folder):
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="日本語のタスク"))
    raw = repo.path("tasks.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert "日本語のタスク".encode("utf-8") in raw


@pytest.mark.parametrize("name", ["", "   ", "あ" * 101])
def test_ac01_invalid_task_name_is_not_saved(data_folder, name):
    repo = data_folder.user("fukui")
    with pytest.raises(ValidationError) as e:
        repo.add_task(Task(id="", name=name))
    assert e.value.field == "タスク名"
    assert not repo.path("tasks.json").exists()
    assert _restart(data_folder).tasks == []


def test_ac01_delete_task_converts_worklogs_to_oneoff(data_folder):
    repo = data_folder.user("fukui")
    t = repo.add_task(Task(id="", name="消すタスク"))
    other = repo.add_task(Task(id="", name="残すタスク"))
    w1 = repo.add_worklog(Worklog("", dt.date(2026, 11, 9), 600, 720, task_id=t.id))
    w2 = repo.add_worklog(Worklog("", dt.date(2026, 11, 9), 780, 840, task_id=other.id))

    assert [w.id for w in repo.linked_worklogs(t.id)] == [w1.id]
    assert repo.delete_task(t.id) == 1

    again = _restart(data_folder)
    conv = again.get_worklog(w1.id)
    assert conv.kind == KIND_ONEOFF and conv.title == "消すタスク" and conv.task_id is None
    assert again.get_worklog(w2.id).kind == KIND_TASK
    assert [x.id for x in again.tasks] == [other.id]


def test_ac01_delete_task_converts_subtasks_to_oneoff(data_folder):
    repo = data_folder.user("fukui")
    main = repo.add_task(Task(id="", name="メイン"))
    gone = repo.add_task(Task(id="", name="サブで使っていたタスク"))
    w = repo.add_worklog(Worklog("", dt.date(2026, 11, 9), 600, 720, task_id=main.id,
                                 subs=[SubItem(KIND_TASK, gone.id)]))
    assert [x.id for x in repo.linked_worklogs(gone.id)] == [w.id]
    assert repo.delete_task(gone.id) == 1

    conv = _restart(data_folder).get_worklog(w.id)
    assert conv.kind == KIND_TASK and conv.task_id == main.id
    assert [s.to_dict() for s in conv.subs] == [
        {"種別": "単発作業", "タスクid": None, "タイトル": "サブで使っていたタスク"}]
