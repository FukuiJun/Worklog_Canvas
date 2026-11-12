"""AC-11: サンプルデータで、日別の稼働時間とタスク別合計が手計算の値と一致する（F-04）。

期待値は scripts/make_sample_data.py の作業バーから手で計算したもの（単位: 時間）。
"""
import datetime as dt

import pytest

from worklog_canvas.core import aggregate as ag
from worklog_canvas.core.layout import check_overlap_limit

W1 = (dt.date(2026, 11, 2), dt.date(2026, 11, 8))
W2 = (dt.date(2026, 11, 9), dt.date(2026, 11, 15))

# 日別の稼働時間（重なりは1回）。11/3 は祝日で記録なし、土日もなし。
DAILY_WORKING = {
    "fukui": {2: 7.5, 3: 0, 4: 8.0, 5: 7.0, 6: 7.25, 7: 0, 8: 0,
              9: 8.0, 10: 7.0, 11: 7.5, 12: 6.75, 13: 7.0, 14: 0, 15: 0},
    "sato": {2: 7.0, 3: 0, 4: 7.0, 5: 8.0, 6: 7.0, 7: 0, 8: 0,
             9: 7.0, 10: 7.5, 11: 7.0, 12: 7.0, 13: 6.0, 14: 0, 15: 0},
    "suzuki": {2: 7.0, 3: 0, 4: 6.0, 5: 7.0, 6: 6.0, 7: 0, 8: 0,
               9: 7.0, 10: 7.0, 11: 7.0, 12: 6.0, 13: 5.0, 14: 0, 15: 0},
}

# 週ごとのタスク別合計（並行作業は各タスクに全時間）、単発作業の合計、稼働時間の合計
WEEKLY = {
    "fukui": {
        W1: ({"T-0001": 11.75, "T-0002": 6.0, "T-0003": 4.0, "T-0004": 4.5, "T-0006": 2.0}, 4.0, 29.75),
        W2: ({"T-0001": 13.0, "T-0002": 11.25, "T-0003": 3.5, "T-0004": 5.0, "T-0005": 4.0}, 6.0, 36.25),
    },
    "sato": {
        W1: ({"T-0001": 9.0, "T-0002": 9.0, "T-0003": 3.0, "T-0005": 2.0, "T-0006": 2.0, "T-0007": 1.0}, 4.0, 29.0),
        W2: ({"T-0001": 10.5, "T-0002": 7.0, "T-0003": 7.0, "T-0007": 2.0, "T-0008": 7.0}, 4.0, 34.5),
    },
    "suzuki": {
        W1: ({"T-0001": 7.0, "T-0002": 3.0, "T-0003": 3.0, "T-0004": 2.0, "T-0006": 3.0, "T-0007": 5.0}, 5.0, 26.0),
        W2: ({"T-0001": 9.0, "T-0002": 7.0, "T-0003": 2.0, "T-0004": 6.0, "T-0006": 7.0}, 4.0, 32.0),
    },
}

# 福井さんの日別・タスク別（並行作業がある日を中心に確認）
FUKUI_DAILY_BY_TASK = {
    4: ({"T-0004": 2.5, "T-0003": 2.0, "T-0002": 2.0, "T-0001": 2.0}, 0.5),  # 14-15時 T3/T2 並行
    6: ({"T-0002": 2.0, "T-0003": 2.0, "T-0004": 2.0, "T-0001": 2.25}, 0.5),  # 10-11:30 並行
    9: ({"T-0001": 2.5, "T-0002": 3.0, "T-0003": 1.0, "T-0004": 2.0}, 1.5),  # 3件重なり
    10: ({"T-0001": 3.0, "T-0002": 1.0, "T-0003": 0.5, "T-0005": 4.0}, 1.0),  # 4件重なり
    12: ({"T-0002": 4.25, "T-0001": 2.0, "T-0004": 2.0}, 0.5),  # 13-15時 完全並行
}


@pytest.mark.parametrize("user", ["fukui", "sato", "suzuki"])
def test_ac11_daily_working_hours(sample_folder, user):
    repo = sample_folder.user(user)
    days = ag.daily_summary(repo.worklogs, repo.tasks, W1[0], W2[1])
    assert {d.date.day: d.working / 60 for d in days} == DAILY_WORKING[user]


@pytest.mark.parametrize("user", ["fukui", "sato", "suzuki"])
@pytest.mark.parametrize("week", [W1, W2], ids=["week1", "week2"])
def test_ac11_weekly_task_totals(sample_folder, user, week):
    repo = sample_folder.user(user)
    s = ag.period_summary(repo.worklogs, repo.tasks, *week)
    by_task, oneoff, working = WEEKLY[user][week]
    assert ag.hours(s.by_task) == by_task
    assert s.oneoff / 60 == oneoff
    assert s.working / 60 == working


def test_ac11_fukui_daily_by_task(sample_folder):
    repo = sample_folder.user("fukui")
    days = {d.date.day: d for d in ag.daily_summary(repo.worklogs, repo.tasks, *W1)}
    days |= {d.date.day: d for d in ag.daily_summary(repo.worklogs, repo.tasks, *W2)}
    for day, (by_task, oneoff) in FUKUI_DAILY_BY_TASK.items():
        assert ag.hours(days[day].by_task) == by_task, day
        assert days[day].oneoff / 60 == oneoff, day


def test_ac11_fukui_category_totals_week2(sample_folder):
    repo = sample_folder.user("fukui")
    s = ag.period_summary(repo.worklogs, repo.tasks, *W2)
    # 次世代基板 = T1 13.0 + T4 5.0、治具 = T2 11.25、チャージャIC = T3 3.5、文書 = T5 4.0、単発 6.0
    assert ag.hours(s.by_category) == {"次世代基板": 18.0, "治具": 11.25, "チャージャIC": 3.5,
                                       "文書": 4.0, "単発作業": 6.0}
    ranking = s.task_ranking()
    assert ranking[0] == ("T-0001", 13 * 60) and ranking[1] == ("T-0002", 675)


def test_sample_data_shape(sample_folder):
    """仕様10章: 3名分、タスク8件、2週間分、並行作業と単発作業を含み、4件を超える重なりがない。"""
    users = sample_folder.list_usernames()
    assert users == ["fukui", "sato", "suzuki"]
    assert {sample_folder.user(u).profile.display_name for u in users} == {"福井", "佐藤", "鈴木"}
    for u in users:
        repo = sample_folder.user(u)
        assert len(repo.tasks) == 8
        dates = {w.date for w in repo.worklogs}
        assert min(dates) == W1[0] and max(dates) == dt.date(2026, 11, 13)
        assert any(w.kind == "単発作業" for w in repo.worklogs)
        task_ids = {t.id for t in repo.tasks}
        assert all(w.task_id in task_ids for w in repo.worklogs if w.kind == "タスク")
        has_parallel = False
        for d in dates:
            spans = [(w.start, w.end) for w in repo.worklogs_on(d)]
            check_overlap_limit(spans)
            has_parallel |= ag.union_minutes(spans) < sum(e - s for s, e in spans)
        assert has_parallel
    assert len(sample_folder.load_categories()) == 5
