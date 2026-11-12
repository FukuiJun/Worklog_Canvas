"""AC-11: サンプルデータで、日別の稼働時間とタスク別合計が手計算の値と一致する（F-04）。

期待値は scripts/make_sample_data.py の作業バーから手で計算したもの（単位: 時間）。
"""
import datetime as dt

import pytest

from worklog_canvas.core import aggregate as ag
from worklog_canvas.core.overlap import first_overlap_in

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

# 週ごとの (メイン時間のタスク別合計, 単発作業(メイン)合計, 稼働時間合計, サブ時間のタスク別合計, 単発作業(サブ)合計)
# 作業バーは重ならないので、稼働時間 = メイン時間の合計 + 単発作業(メイン)の合計
WEEKLY = {
    "fukui": {
        W1: ({"T-0001": 11.75, "T-0002": 5.0, "T-0003": 2.5, "T-0004": 4.5, "T-0006": 2.0}, 4.0, 29.75,
             {"T-0002": 1.0, "T-0003": 1.5}, 0.0),
        W2: ({"T-0001": 13.0, "T-0002": 10.25, "T-0003": 2.0, "T-0004": 3.0, "T-0005": 4.0}, 4.0, 36.25,
             {"T-0002": 1.5, "T-0003": 3.0, "T-0004": 2.0}, 3.0),
    },
    "sato": {
        W1: ({"T-0001": 9.0, "T-0002": 9.0, "T-0003": 3.0, "T-0005": 2.0, "T-0006": 2.0, "T-0007": 1.0},
             3.0, 29.0, {}, 1.0),
        W2: ({"T-0001": 9.5, "T-0002": 7.0, "T-0003": 7.0, "T-0007": 2.0, "T-0008": 5.0}, 4.0, 34.5,
             {"T-0001": 1.0, "T-0008": 2.0}, 0.0),
    },
    "suzuki": {
        W1: ({"T-0001": 7.0, "T-0002": 1.0, "T-0003": 3.0, "T-0004": 2.0, "T-0006": 3.0, "T-0007": 5.0},
             5.0, 26.0, {"T-0002": 2.0}, 0.0),
        W2: ({"T-0001": 9.0, "T-0002": 6.0, "T-0003": 2.0, "T-0004": 5.0, "T-0006": 7.0}, 3.0, 32.0,
             {"T-0002": 1.5, "T-0004": 1.0}, 1.5),
    },
}

# 福井さんの日別: (メイン時間, 単発作業(メイン), サブ時間, 単発作業(サブ))。サブタスクがある日を中心に確認
FUKUI_DAILY_BY_TASK = {
    4: ({"T-0004": 2.5, "T-0003": 2.0, "T-0002": 1.0, "T-0001": 2.0}, 0.5, {"T-0002": 1.0}, 0.0),
    6: ({"T-0002": 2.0, "T-0003": 0.5, "T-0004": 2.0, "T-0001": 2.25}, 0.5, {"T-0003": 1.5}, 0.0),
    9: ({"T-0001": 2.5, "T-0002": 3.0, "T-0004": 2.0}, 0.5, {"T-0003": 1.5}, 1.5),  # サブ2つ
    10: ({"T-0001": 3.0, "T-0005": 4.0}, 0.0, {"T-0002": 1.5, "T-0003": 1.5}, 1.5),  # サブ3つ
    12: ({"T-0002": 4.25, "T-0001": 2.0}, 0.5, {"T-0004": 2.0}, 0.0),
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
    by_task, oneoff, working, sub_by_task, sub_oneoff = WEEKLY[user][week]
    assert ag.hours(s.by_task) == by_task
    assert s.oneoff / 60 == oneoff
    assert s.working / 60 == working
    assert ag.hours(s.sub_by_task) == sub_by_task
    assert s.sub_oneoff / 60 == sub_oneoff
    assert s.working == sum(s.by_task.values()) + s.oneoff


def test_ac11_fukui_daily_by_task(sample_folder):
    repo = sample_folder.user("fukui")
    days = {d.date.day: d for d in ag.daily_summary(repo.worklogs, repo.tasks, *W1)}
    days |= {d.date.day: d for d in ag.daily_summary(repo.worklogs, repo.tasks, *W2)}
    for day, (by_task, oneoff, sub_by_task, sub_oneoff) in FUKUI_DAILY_BY_TASK.items():
        assert ag.hours(days[day].by_task) == by_task, day
        assert days[day].oneoff / 60 == oneoff, day
        assert ag.hours(days[day].sub_by_task) == sub_by_task, day
        assert days[day].sub_oneoff / 60 == sub_oneoff, day


def test_ac11_fukui_category_totals_week2(sample_folder):
    repo = sample_folder.user("fukui")
    s = ag.period_summary(repo.worklogs, repo.tasks, *W2)
    # メインのみ: 次世代基板 = T1 13.0 + T4 3.0、治具 = T2 10.25、チャージャIC = T3 2.0、文書 = T5 4.0、単発 4.0
    assert ag.hours(s.by_category) == {"次世代基板": 16.0, "治具": 10.25, "チャージャIC": 2.0,
                                       "文書": 4.0, "単発作業": 4.0}
    assert sum(s.by_category.values()) == s.working  # 割合の合計は100%
    assert abs(sum(r for _, _, r in s.category_share()) - 1.0) < 1e-9
    ranking = s.task_ranking()
    assert ranking[:2] == [("T-0001", 13 * 60), ("T-0002", 615)]


def test_sample_data_shape(sample_folder):
    """仕様10章: 3名分、タスク8件、2週間分、並行作業（サブタスク）と単発作業を含み、作業バーは重ならない。"""
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
        assert all(w.task_ids() <= task_ids for w in repo.worklogs)
        assert any(w.subs for w in repo.worklogs)
        for w in repo.worklogs:
            w.validate()
        for d in dates:
            assert first_overlap_in([(w.id, w.start, w.end) for w in repo.worklogs_on(d)]) is None, (u, d)
    fukui = sample_folder.user("fukui")
    assert max(len(w.subs) for w in fukui.worklogs) == 3
    assert any(s.kind == "単発作業" for w in fukui.worklogs for s in w.subs)
    assert len(sample_folder.load_categories()) == 5
