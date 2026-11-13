"""AC-10（改）: 10:00〜12:00にメイン=タスクA、サブ=タスクBで記録したデータで、
タスクAのメイン時間=2.0h、タスクBのサブ時間=2.0h（Bのメイン時間は0h）、稼働時間=2.0hになる（F-04）。
"""
import datetime as dt

from worklog_canvas.core import aggregate as ag
from worklog_canvas.core.models import KIND_ONEOFF, KIND_TASK, SubItem, Task, Worklog

DAY = dt.date(2026, 11, 9)


def test_ac10_main_and_sub(data_folder):
    repo = data_folder.user("fukui")
    a = repo.add_task(Task(id="", name="タスクA", category="治具"))
    b = repo.add_task(Task(id="", name="タスクB", category="次世代基板"))
    repo.add_worklog(Worklog("", DAY, 600, 720, task_id=a.id, subs=[SubItem(KIND_TASK, b.id)]))

    repo = data_folder.user("fukui")  # 保存したデータで集計
    s = ag.period_summary(repo.worklogs, repo.tasks, DAY, DAY)
    assert ag.hours(s.by_task) == {a.id: 2.0}
    assert ag.hours(s.sub_by_task) == {b.id: 2.0}
    assert s.working / 60 == 2.0
    # カテゴリ別はメインだけ → 割合の合計は100%
    assert s.by_category == {"治具": 120}
    assert s.category_share() == [("治具", 120, 1.0)]

    day = ag.daily_summary(repo.worklogs, repo.tasks, DAY, DAY)[0]
    assert (day.working, day.by_task, day.sub_by_task) == (120, {a.id: 120}, {b.id: 120})
    assert ag.task_actual_minutes(repo.worklogs, a.id) == 120
    assert ag.task_actual_minutes(repo.worklogs, b.id) == 0
    assert ag.task_sub_minutes(repo.worklogs, b.id) == 120
    assert ag.task_sub_minutes(repo.worklogs, a.id) == 0


def test_ac10_multiple_subs_each_get_full_time():
    ws = [Worklog("W-1", DAY, 600, 690, task_id="T-0001",
                  subs=[SubItem(KIND_TASK, "T-0002"), SubItem(KIND_TASK, "T-0003"),
                        SubItem(KIND_ONEOFF, title="打合せ")])]
    s = ag.period_summary(ws, [], DAY, DAY)
    assert s.by_task == {"T-0001": 90}
    assert s.sub_by_task == {"T-0002": 90, "T-0003": 90}
    assert s.sub_oneoff == 90 and s.oneoff == 0 and s.working == 90


def test_ac10_working_equals_sum_of_mains():
    ws = [Worklog("W-1", DAY, 540, 600, kind=KIND_ONEOFF, title="朝会"),
          Worklog("W-2", DAY, 600, 720, task_id="T-0001", subs=[SubItem(KIND_TASK, "T-0002")]),
          Worklog("W-3", DAY, 780, 840, task_id="T-0002")]
    s = ag.period_summary(ws, [], DAY, DAY)
    assert s.working == sum(s.by_task.values()) + s.oneoff == 240
    assert s.task_ranking() == [("T-0001", 120), ("T-0002", 60), ("単発作業", 60)]


def test_ac10_union_variants():
    assert ag.union_minutes([]) == 0
    assert ag.union_minutes([(600, 720), (630, 690)]) == 120
    assert ag.union_minutes([(600, 660), (660, 720)]) == 120
    assert ag.union_minutes([(600, 660), (690, 720)]) == 90
    assert ag.union_minutes([(600, 700), (650, 750), (740, 800)]) == 200


def test_ac10_empty_period():
    ws = [Worklog("W-1", DAY, 600, 690, kind=KIND_ONEOFF, title="製造応援")]
    empty = ag.period_summary(ws, [], DAY + dt.timedelta(days=1), DAY + dt.timedelta(days=7))
    assert empty.is_empty
