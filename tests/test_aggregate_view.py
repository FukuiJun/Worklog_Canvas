"""集計画面（F-04）用の集計: 期間、日別の積み上げ、タスクごとの進捗。"""
import datetime as dt

from worklog_canvas.core import aggregate as ag
from worklog_canvas.core.models import KIND_ONEOFF, KIND_TASK, SubItem, Task, Worklog

D = dt.date


def test_period_range():
    a = D(2026, 11, 12)
    assert ag.period_range("day", a) == (a, a)
    assert ag.period_range("week", a) == (D(2026, 11, 9), D(2026, 11, 15))
    assert ag.period_range("custom", a, D(2026, 11, 20), D(2026, 11, 1)) == (D(2026, 11, 1), D(2026, 11, 20))


def test_daily_stacks_order_and_totals(sample_folder):
    repo = sample_folder.user("fukui")
    cats = [c.name for c in sample_folder.load_categories()]
    stacks = ag.daily_stacks(repo.worklogs, repo.tasks, D(2026, 11, 9), D(2026, 11, 15), cats)
    assert [s.date.day for s in stacks] == [9, 10, 11, 12, 13, 14, 15]
    mon = stacks[0]
    # 11/9: 次世代基板(T1 2.5, T4 2.0) → 治具(T2 3.0) → 単発作業 0.5
    assert [(s.key, s.category, s.minutes / 60) for s in mon.segments] == [
        ("T-0001", "次世代基板", 2.5), ("T-0004", "次世代基板", 2.0), ("T-0002", "治具", 3.0),
        ("単発作業", "単発作業", 0.5)]
    for s in stacks:
        assert sum(x.minutes for x in s.segments) == s.working  # 積み上げの高さ＝稼働時間
    assert stacks[-1].segments == [] and stacks[-1].working == 0


def test_category_order_appends_unknown_and_fixed_tail():
    tasks = [Task("T-1", "a", category="新規"), Task("T-2", "b")]
    assert ag.category_order(tasks, ["治具"]) == ["治具", "新規", "（未分類）", "単発作業"]


def test_progress_rows(sample_folder):
    repo = sample_folder.user("fukui")
    rows = ag.progress_rows(repo.tasks, repo.worklogs, D(2026, 11, 9), D(2026, 11, 15), D(2026, 11, 12))
    ids = [r.task.id for r in rows]
    # 未完了6件 + 期間内に作業バーがある完了タスク T-0003（T-0006 は前週だけなので出ない）
    assert ids == ["T-0004", "T-0001", "T-0002", "T-0007", "T-0008", "T-0005", "T-0003"]
    r1 = rows[ids.index("T-0001")]
    assert (r1.actual / 60, r1.sub / 60, r1.period_main / 60, r1.remaining_days) == (24.75, 0, 13.0, 8)
    assert r1.over_estimate  # 24.75h > 予定工数 16h
    r2 = rows[ids.index("T-0002")]
    assert (r2.actual / 60, r2.sub / 60, r2.period_sub / 60) == (15.25, 2.5, 1.5)
    assert r2.over_estimate  # 15.25h > 12h
    assert rows[ids.index("T-0004")].remaining_days == 1
    assert rows[ids.index("T-0005")].remaining_days is None


def test_over_estimate_boundary():
    t = Task("T-1", "a", estimate_hours=2.0)
    w = [Worklog("W-1", D(2026, 11, 9), 600, 720, task_id="T-1")]
    [row] = ag.progress_rows([t], w, D(2026, 11, 9), D(2026, 11, 9), D(2026, 11, 9))
    assert not row.over_estimate  # ちょうどは超過ではない
    w.append(Worklog("W-2", D(2026, 11, 9), 720, 735, task_id="T-1"))
    [row] = ag.progress_rows([t], w, D(2026, 11, 9), D(2026, 11, 9), D(2026, 11, 9))
    assert row.over_estimate


def test_sub_only_task_appears_in_period():
    done = Task("T-2", "done", status="完了")
    w = [Worklog("W-1", D(2026, 11, 9), 600, 720, task_id="T-1", subs=[SubItem(KIND_TASK, "T-2")])]
    rows = ag.progress_rows([Task("T-1", "a"), done], w, D(2026, 11, 9), D(2026, 11, 9), D(2026, 11, 9))
    assert [r.task.id for r in rows] == ["T-1", "T-2"]


def test_nice_ticks():
    assert ag.nice_ticks(7.5) == [0, 2, 4, 6, 8]
    assert ag.nice_ticks(2) == [0, 0.5, 1, 1.5, 2]
    assert ag.nice_ticks(36.25) == [0, 10, 20, 30, 40]
    assert ag.nice_ticks(0) == [0, 1]
