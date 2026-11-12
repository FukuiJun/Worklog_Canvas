"""作業バーの色: カテゴリ色、単発作業は灰色、カテゴリ未設定は茶色（F-02）。"""
import datetime as dt

from worklog_canvas.core.colors import ONEOFF_COLOR, UNCATEGORIZED_COLOR, worklog_color
from worklog_canvas.core.models import KIND_ONEOFF, SubItem, Task, Worklog

DAY = dt.date(2026, 11, 9)
COLORS = {"治具": "#F28E2B"}
TASKS = {"T-0001": Task("T-0001", "A", category="治具"), "T-0002": Task("T-0002", "B"),
         "T-0003": Task("T-0003", "C", category="消えたカテゴリ")}


def test_colors():
    assert worklog_color(Worklog("W", DAY, 600, 660, task_id="T-0001"), TASKS, COLORS) == "#F28E2B"
    assert worklog_color(Worklog("W", DAY, 600, 660, task_id="T-0002"), TASKS, COLORS) == UNCATEGORIZED_COLOR
    assert worklog_color(Worklog("W", DAY, 600, 660, task_id="T-0003"), TASKS, COLORS) == UNCATEGORIZED_COLOR
    oneoff = Worklog("W", DAY, 600, 660, kind=KIND_ONEOFF, title="会議", subs=[SubItem(task_id="T-0001")])
    assert worklog_color(oneoff, TASKS, COLORS) == ONEOFF_COLOR  # 色はメインで決める
    assert UNCATEGORIZED_COLOR != ONEOFF_COLOR
