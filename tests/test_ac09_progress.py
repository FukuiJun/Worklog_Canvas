"""AC-09: 進捗率を同じ日に20→40と変更すると、進捗履歴のその日の値は40の1件だけになる（F-03）。"""
import datetime as dt

import pytest

from worklog_canvas.core.models import STATUS_DONE, Task, ValidationError

DAY = dt.date(2026, 11, 10)


def test_ac09_same_day_keeps_last_value(data_folder):
    repo = data_folder.user("fukui")
    t = repo.add_task(Task(id="", name="A"))
    repo.set_progress(t.id, 20, today=DAY)
    repo.set_progress(t.id, 40, today=DAY)

    hist = data_folder.user("fukui").get_task(t.id).history  # 保存後に読み直して確認
    same_day = [e for e in hist if e.date == DAY]
    assert len(same_day) == 1 and same_day[0].progress == 40
    assert [e.to_dict() for e in hist] == [{"日付": "2026-11-10", "進捗率": 40}]


def test_ac09_different_days_are_kept_in_date_order():
    t = Task(id="T-0001", name="A")
    t.set_progress(20, dt.date(2026, 11, 9))
    t.set_progress(40, dt.date(2026, 11, 10))
    t.set_progress(45, dt.date(2026, 11, 10))
    assert [(e.date.day, e.progress) for e in t.history] == [(9, 20), (10, 45)]
    assert t.progress == 45


@pytest.mark.parametrize("value", [-5, 101, 105, 42, 3])
def test_ac09_out_of_range_rejected(value):
    t = Task(id="T-0001", name="A")
    with pytest.raises(ValidationError):
        t.set_progress(value, DAY)
    assert t.progress == 0 and t.history == []


def test_ac09_100_needs_done_confirmation_and_sets_done_date():
    t = Task(id="T-0001", name="A", status="進行中")
    t.set_progress(100, DAY)
    assert t.needs_done_confirmation()
    t.set_status(STATUS_DONE, DAY)
    assert not t.needs_done_confirmation()
    assert t.done_date == DAY
