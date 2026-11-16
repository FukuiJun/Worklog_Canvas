"""定期タスク（F-09）: 繰り返しの判定、予定の表示、作業バーへの確定、保存。"""
import datetime as dt
from dataclasses import replace

import pytest

from worklog_canvas.core import recurring as rc
from worklog_canvas.core.models import KIND_ONEOFF, KIND_TASK, Task, ValidationError, Worklog
from worklog_canvas.core.repository import DataFolder

D = dt.date
MON = D(2026, 11, 16)


def item(**kw):
    base = dict(id="R-0001", start=540, end=570, pattern=rc.WEEKLY, kind=KIND_ONEOFF, title="朝会",
                weekdays=[0], start_date=D(2026, 11, 2))
    base.update(kw)
    return rc.RecurringItem(**base)


def days(it, start, n):
    return [d for d in (start + dt.timedelta(days=i) for i in range(n)) if it.occurs_on(d)]


def test_daily_weekdays():
    it = item(pattern=rc.DAILY_WEEKDAYS, weekdays=[])
    assert [d.day for d in days(it, MON, 7)] == [16, 17, 18, 19, 20]


def test_weekly_selected_days():
    it = item(weekdays=[0, 3])  # 月・木
    assert [d.day for d in days(it, MON, 14)] == [16, 19, 23, 26]


def test_biweekly_counts_from_start_week():
    it = item(pattern=rc.BIWEEKLY, weekdays=[0], start_date=D(2026, 11, 4))  # 11/2 の週から数える
    assert days(it, D(2026, 11, 2), 35) == [D(2026, 11, 16), D(2026, 11, 30)]  # 11/2 は開始日前


def test_monthly_and_month_end():
    it = item(pattern=rc.MONTHLY, month_day=31, weekdays=[], start_date=D(2026, 1, 1))
    hits = days(it, D(2026, 1, 1), 120)
    assert hits == [D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)]


def test_start_and_end_date():
    it = item(weekdays=[0], start_date=MON, end_date=MON + dt.timedelta(days=7))
    assert days(it, MON - dt.timedelta(days=7), 28) == [MON, MON + dt.timedelta(days=7)]


@pytest.mark.parametrize("kw, field", [
    (dict(weekdays=[]), "曜日"),
    (dict(start=545), "時刻"),
    (dict(end=540), "時刻"),
    (dict(pattern="毎年"), "繰り返し"),
    (dict(pattern=rc.MONTHLY, month_day=0), "日にち"),
    (dict(title=""), "タイトル"),
    (dict(end_date=D(2026, 11, 1)), "終了日"),
])
def test_validation(kw, field):
    with pytest.raises(ValidationError) as e:
        item(**kw).validate()
    assert e.value.field == field


def test_occurrences_hide_when_a_bar_exists():
    it = item(weekdays=[0, 1])
    bars = [Worklog("W-1", MON, 540, 600, kind=KIND_ONEOFF, title="朝会")]  # 月曜は記録済み
    occ = rc.occurrences([it], [MON, MON + dt.timedelta(days=1)], bars)
    assert [o.date for o in occ] == [MON + dt.timedelta(days=1)]


def test_to_worklog():
    w = item().to_worklog(MON)
    assert (w.date, w.start, w.end, w.kind, w.title, w.source) == (MON, 540, 570, KIND_ONEOFF, "朝会", "定期")
    w.validate()


def test_repository_add_update_delete_and_reload(data_folder):
    repo = data_folder.user("fukui")
    t = repo.add_task(Task(id="", name="定例の準備"))
    a = repo.add_recurring(item(kind=KIND_TASK, task_id=t.id, title=""))
    b = repo.add_recurring(item(pattern=rc.MONTHLY, month_day=25, weekdays=[]))
    assert [a.id, b.id] == ["R-0001", "R-0002"]
    repo.update_recurring(replace(a, end=600))
    again = DataFolder(data_folder.root).user("fukui")
    assert [(r.id, r.end, r.task_id) for r in again.recurring] == [("R-0001", 600, t.id), ("R-0002", 570, None)]
    again.delete_recurring("R-0001")
    assert [r.id for r in DataFolder(data_folder.root).user("fukui").recurring] == ["R-0002"]
    c = again.add_recurring(item())
    assert c.id == "R-0003"  # 番号は再利用しない
    with pytest.raises(KeyError):
        again.add_recurring(item(kind=KIND_TASK, task_id="T-9999", title=""))


def test_deleting_task_turns_recurring_into_oneoff(data_folder):
    repo = data_folder.user("fukui")
    t = repo.add_task(Task(id="", name="週次ミーティング"))
    repo.add_recurring(item(kind=KIND_TASK, task_id=t.id, title=""))
    repo.delete_task(t.id)
    r = DataFolder(data_folder.root).user("fukui").recurring[0]
    assert (r.kind, r.task_id, r.title) == (KIND_ONEOFF, None, "週次ミーティング")


def test_describe():
    assert item(weekdays=[3, 0]).describe() == "毎週 月・木 09:00〜09:30"
    assert item(pattern=rc.MONTHLY, month_day=25).describe() == "毎月 25日 09:00〜09:30"
    assert item(pattern=rc.DAILY_WEEKDAYS).describe() == "平日毎日 09:00〜09:30"
