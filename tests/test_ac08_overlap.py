"""AC-08: 重なりの列割り当て関数が、2〜4件の重なりで互いに重ならない列番号を返し、5件目を拒否する（F-02）。"""
import datetime as dt
import itertools

import pytest

from worklog_canvas.core.layout import (
    TOO_MANY_OVERLAPS_MESSAGE, TooManyOverlapsError, assign_columns, max_overlap,
)
from worklog_canvas.core.models import KIND_ONEOFF, Worklog


def _h(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def _items(*spans):
    return [(i, _h(s), _h(e)) for i, (s, e) in enumerate(spans)]


def _assert_valid(items, placements):
    assert set(placements) == {k for k, _, _ in items}
    for (k1, s1, e1), (k2, s2, e2) in itertools.combinations(items, 2):
        if s1 < e2 and s2 < e1:  # 重なっている
            p1, p2 = placements[k1], placements[k2]
            assert p1.column != p2.column
            assert p1.columns == p2.columns  # 同じグループは同じ列数で等分
    for p in placements.values():
        assert 0 <= p.column < p.columns <= 4


@pytest.mark.parametrize("n", [2, 3, 4])
def test_ac08_n_overlaps_get_distinct_columns(n):
    spans = [("10:00", "12:00"), ("10:30", "11:30"), ("10:45", "11:15"), ("11:00", "11:45")][:n]
    items = _items(*spans)
    placements = assign_columns(items)
    _assert_valid(items, placements)
    assert sorted(p.column for p in placements.values()) == list(range(n))
    assert all(p.columns == n for p in placements.values())


def test_ac08_fifth_overlap_is_rejected():
    items = _items(("10:00", "12:00"), ("10:30", "11:30"), ("10:45", "11:15"),
                   ("11:00", "11:45"), ("11:00", "11:15"))
    with pytest.raises(TooManyOverlapsError) as e:
        assign_columns(items)
    assert str(e.value) == TOO_MANY_OVERLAPS_MESSAGE == "同じ時間帯に記録できるのは4つまでです"
    assert e.value.depth == 5


def test_ac08_five_bars_without_5_way_overlap_are_ok():
    # 5件が1つのグループだが、同時に重なるのは最大3件 → 受け付ける
    items = _items(("09:00", "10:00"), ("09:30", "11:00"), ("09:45", "10:15"),
                   ("10:00", "11:30"), ("10:30", "12:00"))
    assert max_overlap((s, e) for _, s, e in items) == 3
    placements = assign_columns(items)
    _assert_valid(items, placements)
    assert max(p.columns for p in placements.values()) == 3


def test_ac08_touching_bars_do_not_overlap():
    items = _items(("10:00", "12:00"), ("12:00", "13:00"))
    placements = assign_columns(items)
    assert all(p.column == 0 and p.columns == 1 for p in placements.values())


def test_ac08_separate_groups_have_their_own_column_count():
    items = _items(("09:00", "10:00"), ("09:00", "10:00"), ("13:00", "14:00"))
    p = assign_columns(items)
    assert p[0].columns == p[1].columns == 2
    assert p[2] == type(p[2])(0, 1)


def test_ac08_exhaustive_small_cases():
    """15分刻み 10:00〜11:00 の全区間から4件を選ぶ全組合せで、常に正しく割り当てられる。"""
    slots = [600 + 15 * i for i in range(5)]
    spans = [(s, e) for s, e in itertools.combinations(slots, 2)]
    for combo in itertools.combinations_with_replacement(spans, 4):
        items = [(i, s, e) for i, (s, e) in enumerate(combo)]
        _assert_valid(items, assign_columns(items))


def test_ac08_repository_rejects_fifth_and_keeps_state(data_folder):
    repo = data_folder.user("fukui")
    day = dt.date(2026, 11, 9)
    for i in range(4):
        repo.add_worklog(Worklog("", day, 600, 720, kind=KIND_ONEOFF, title=f"作業{i}"))
    before = [w.to_dict() for w in repo.worklogs]
    with pytest.raises(TooManyOverlapsError):
        repo.add_worklog(Worklog("", day, 660, 690, kind=KIND_ONEOFF, title="5件目"))
    assert [w.to_dict() for w in repo.worklogs] == before
    # 別の時間帯なら記録できる
    repo.add_worklog(Worklog("", day, 720, 780, kind=KIND_ONEOFF, title="昼過ぎ"))

    # 移動で5件目になる場合も拒否して元のまま
    from dataclasses import replace
    last = repo.worklogs[-1]
    with pytest.raises(TooManyOverlapsError):
        repo.update_worklog(replace(last, start=690, end=750))
    assert repo.get_worklog(last.id).start == 720
    assert data_folder.user("fukui").get_worklog(last.id).start == 720
