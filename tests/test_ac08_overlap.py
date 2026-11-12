"""AC-08（改）: 重なり判定関数が、既存の作業バーと重なる作成・移動を拒否し、接する配置は受け付ける。
並行作業はサブタスクで記録し、サブタスクは3つまで（F-02）。
"""
import datetime as dt
import itertools
from dataclasses import replace

import pytest

from worklog_canvas.core.models import KIND_ONEOFF, KIND_TASK, SubItem, Task, ValidationError, Worklog
from worklog_canvas.core.overlap import (
    OVERLAP_MESSAGE, OverlapError, check_no_overlap, find_overlaps, first_overlap_in, overlaps,
)

DAY = dt.date(2026, 11, 9)


def _h(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


@pytest.mark.parametrize("a, b, expected", [
    (("10:00", "12:00"), ("10:30", "11:30"), True),   # 包含
    (("10:00", "12:00"), ("11:45", "13:00"), True),   # 15分だけ重なる
    (("10:00", "12:00"), ("09:00", "10:15"), True),
    (("10:00", "12:00"), ("10:00", "12:00"), True),   # 同じ
    (("10:00", "12:00"), ("12:00", "13:00"), False),  # 接する
    (("10:00", "12:00"), ("09:00", "10:00"), False),  # 接する
    (("10:00", "12:00"), ("13:00", "14:00"), False),
])
def test_ac08_overlaps(a, b, expected):
    sa, ea, sb, eb = _h(a[0]), _h(a[1]), _h(b[0]), _h(b[1])
    assert overlaps(sa, ea, sb, eb) is expected
    assert overlaps(sb, eb, sa, ea) is expected  # 対称


def test_ac08_find_and_check():
    existing = [("W1", _h("09:00"), _h("10:00")), ("W2", _h("10:00"), _h("12:00")),
                ("W3", _h("13:00"), _h("14:00"))]
    assert find_overlaps(_h("09:45"), _h("10:15"), existing) == ["W1", "W2"]
    assert find_overlaps(_h("12:00"), _h("13:00"), existing) == []
    check_no_overlap(_h("12:00"), _h("13:00"), existing)
    with pytest.raises(OverlapError) as e:
        check_no_overlap(_h("11:00"), _h("13:30"), existing)
    assert e.value.conflicts == ["W2", "W3"]
    assert str(e.value) == OVERLAP_MESSAGE


def test_ac08_exhaustive_against_minute_grid():
    """15分刻みの全区間の組で、分単位の素朴な判定と一致する。"""
    slots = range(600, 721, 15)
    spans = list(itertools.combinations(slots, 2))
    for (s1, e1), (s2, e2) in itertools.product(spans, spans):
        naive = bool(set(range(s1, e1)) & set(range(s2, e2)))
        assert overlaps(s1, e1, s2, e2) is naive


def test_ac08_first_overlap_in():
    assert first_overlap_in([("a", 600, 660), ("b", 660, 720)]) is None
    assert first_overlap_in([("a", 600, 720), ("b", 630, 650), ("c", 700, 760)]) == ("a", "b")


def test_ac08_repository_rejects_overlap_and_keeps_state(data_folder):
    repo = data_folder.user("fukui")
    a = repo.add_task(Task(id="", name="A"))
    w1 = repo.add_worklog(Worklog("", DAY, _h("10:00"), _h("12:00"), task_id=a.id))
    w2 = repo.add_worklog(Worklog("", DAY, _h("12:00"), _h("13:00"), kind=KIND_ONEOFF, title="接する"))
    before = [w.to_dict() for w in repo.worklogs]

    with pytest.raises(OverlapError):  # 作成
        repo.add_worklog(Worklog("", DAY, _h("11:00"), _h("11:30"), kind=KIND_ONEOFF, title="重なる"))
    with pytest.raises(OverlapError):  # 移動
        repo.update_worklog(replace(w2, start=_h("11:45"), end=_h("12:45")))
    with pytest.raises(OverlapError):  # 伸縮
        repo.update_worklog(replace(w1, end=_h("12:15")))
    assert [w.to_dict() for w in repo.worklogs] == before
    assert [w.to_dict() for w in data_folder.user("fukui").worklogs] == before

    # 別の日・自分自身の範囲内での伸縮は可
    repo.update_worklog(replace(w2, date=DAY + dt.timedelta(days=1), start=_h("11:00")))
    repo.update_worklog(replace(w1, end=_h("11:45")))


def test_ac08_subtasks_up_to_three(data_folder):
    repo = data_folder.user("fukui")
    main, b, c, d = (repo.add_task(Task(id="", name=n)) for n in "ABCD")
    subs = [SubItem(KIND_TASK, b.id), SubItem(KIND_TASK, c.id), SubItem(KIND_ONEOFF, title="打合せ")]
    w = repo.add_worklog(Worklog("", DAY, 600, 720, task_id=main.id, subs=subs))
    again = data_folder.user("fukui").get_worklog(w.id)
    assert [s.to_dict() for s in again.subs] == [
        {"種別": "タスク", "タスクid": b.id, "タイトル": ""},
        {"種別": "タスク", "タスクid": c.id, "タイトル": ""},
        {"種別": "単発作業", "タスクid": None, "タイトル": "打合せ"},
    ]
    with pytest.raises(ValidationError) as e:
        repo.update_worklog(replace(w, subs=subs + [SubItem(KIND_TASK, d.id)]))
    assert e.value.message == "サブタスクは3つまでです"
    assert len(repo.get_worklog(w.id).subs) == 3


@pytest.mark.parametrize("subs, field", [
    ([SubItem(KIND_TASK, "T-0001")], "サブタスク"),  # メインと同じタスク
    ([SubItem(KIND_TASK, "T-0002"), SubItem(KIND_TASK, "T-0002")], "サブタスク"),  # 重複
    ([SubItem(KIND_TASK, None)], "サブタスクのタスク"),
    ([SubItem(KIND_ONEOFF, title="")], "サブタスクのタイトル"),
    ([SubItem(KIND_ONEOFF, title="あ" * 51)], "サブタスクのタイトル"),
])
def test_ac08_invalid_subtasks(subs, field):
    w = Worklog("W-1", DAY, 600, 720, task_id="T-0001", subs=subs)
    with pytest.raises(ValidationError) as e:
        w.validate()
    assert e.value.field == field


def test_ac08_subtask_must_exist(data_folder):
    repo = data_folder.user("fukui")
    a = repo.add_task(Task(id="", name="A"))
    with pytest.raises(KeyError):
        repo.add_worklog(Worklog("", DAY, 600, 720, task_id=a.id, subs=[SubItem(KIND_TASK, "T-9999")]))
    assert repo.worklogs == []


def test_ac08_oneoff_main_with_task_sub():
    w = Worklog("W-1", DAY, 600, 720, kind=KIND_ONEOFF, title="製造応援", subs=[SubItem(KIND_TASK, "T-0001")])
    w.validate()
    assert w.task_ids() == {"T-0001"}
