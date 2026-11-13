"""AC-05: 時刻の15分吸着の関数が、境界値（7分→0分、8分→15分）で正しい結果を返す（F-02）。"""
import datetime as dt

import pytest

from worklog_canvas.core.timeutil import snap_minutes, snap_time


@pytest.mark.parametrize("minutes, expected", [
    (0, 0), (7, 0), (8, 15), (15, 15), (22, 15), (23, 30), (52, 45), (53, 60),
    (7.49, 0), (7.5, 15),  # 中間は切り上げ
    (12 * 60 + 7, 12 * 60), (12 * 60 + 8, 12 * 60 + 15),  # AC-04 の 12:07 付近
])
def test_ac05_snap_minutes(minutes, expected):
    assert snap_minutes(minutes) == expected


def test_ac05_boundaries_within_each_hour():
    for h in range(24):
        base = h * 60
        assert snap_minutes(base + 7) == base
        assert snap_minutes(base + 8) == base + 15


def test_ac05_snap_time():
    assert snap_time(dt.time(10, 7)) == 600
    assert snap_time(dt.time(10, 8)) == 615
    assert snap_time("23:53") == 24 * 60
