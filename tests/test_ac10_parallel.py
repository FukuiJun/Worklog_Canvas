"""AC-10: 10:00〜12:00にタスクAとBを並行で記録したデータで、タスクA=2.0h、タスクB=2.0h、稼働時間=2.0h（F-04）。"""
import datetime as dt

from worklog_canvas.core import aggregate as ag
from worklog_canvas.core.models import KIND_ONEOFF, Task, Worklog

DAY = dt.date(2026, 11, 9)


def test_ac10_parallel_work(data_folder):
    repo = data_folder.user("fukui")
    a = repo.add_task(Task(id="", name="タスクA", category="治具"))
    b = repo.add_task(Task(id="", name="タスクB", category="次世代基板"))
    repo.add_worklog(Worklog("", DAY, 600, 720, task_id=a.id))
    repo.add_worklog(Worklog("", DAY, 600, 720, task_id=b.id))

    repo = data_folder.user("fukui")  # 保存したデータで集計
    s = ag.period_summary(repo.worklogs, repo.tasks, DAY, DAY)
    assert ag.hours(s.by_task) == {a.id: 2.0, b.id: 2.0}
    assert s.working / 60 == 2.0
    day = ag.daily_summary(repo.worklogs, repo.tasks, DAY, DAY)[0]
    assert day.working == 120 and day.by_task == {a.id: 120, b.id: 120}
    assert s.by_category == {"治具": 120, "次世代基板": 120}


def test_ac10_union_variants():
    assert ag.union_minutes([]) == 0
    assert ag.union_minutes([(600, 720), (630, 690)]) == 120  # 包含
    assert ag.union_minutes([(600, 660), (660, 720)]) == 120  # 接する
    assert ag.union_minutes([(600, 660), (690, 720)]) == 90  # 離れている
    assert ag.union_minutes([(600, 700), (650, 750), (740, 800)]) == 200  # 連鎖


def test_ac10_oneoff_and_empty_period():
    ws = [Worklog("W-1", DAY, 600, 690, kind=KIND_ONEOFF, title="製造応援")]
    s = ag.period_summary(ws, [], DAY, DAY)
    assert s.oneoff == 90 and s.by_task == {} and s.working == 90
    assert s.task_ranking() == [("単発作業", 90)]
    empty = ag.period_summary(ws, [], DAY + dt.timedelta(days=1), DAY + dt.timedelta(days=7))
    assert empty.is_empty
