"""並行作業（作業バーの重なり）の列割り当て（F-02）。

- 区間は半開区間 [start, end) として扱う。10:00〜12:00 と 12:00〜13:00 は重ならない。
- 互いに（直接・間接に）重なる作業バーの集まりを「グループ」とし、
  グループ内で列番号を割り当てる。表示では日の列幅をグループの列数で等分する。
- 同じ時刻に重なる作業バーは最大4つまで（MAX_OVERLAP）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable, Sequence

MAX_OVERLAP = 4
TOO_MANY_OVERLAPS_MESSAGE = "同じ時間帯に記録できるのは4つまでです"


class TooManyOverlapsError(ValueError):
    def __init__(self, depth: int):
        super().__init__(TOO_MANY_OVERLAPS_MESSAGE)
        self.depth = depth


@dataclass(frozen=True)
class Placement:
    column: int  # 0始まりの列番号
    columns: int  # その作業バーが属するグループの列数


def max_overlap(intervals: Iterable[tuple[int, int]]) -> int:
    """同じ時刻に重なっている区間数の最大値。"""
    events: list[tuple[int, int]] = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    # 同時刻では終了(-1)を先に処理する（半開区間）
    events.sort(key=lambda x: (x[0], x[1]))
    depth = best = 0
    for _, delta in events:
        depth += delta
        best = max(best, depth)
    return best


def check_overlap_limit(intervals: Iterable[tuple[int, int]], limit: int = MAX_OVERLAP) -> None:
    depth = max_overlap(intervals)
    if depth > limit:
        raise TooManyOverlapsError(depth)


def assign_columns(
    items: Sequence[tuple[Hashable, int, int]], limit: int = MAX_OVERLAP
) -> dict[Hashable, Placement]:
    """(キー, 開始分, 終了分) の並びに列を割り当てる。

    開始順に、空いている最小の列へ入れる（区間グラフの貪欲彩色なので、
    使う列数は同時に重なる最大数と一致し、limit 以下に収まる）。
    同時に limit を超えて重なる場合は TooManyOverlapsError。
    """
    check_overlap_limit(((s, e) for _, s, e in items), limit)

    order = sorted(items, key=lambda x: (x[1], x[2]))
    result: dict[Hashable, Placement] = {}
    group: list[tuple[Hashable, int]] = []  # (key, column)
    column_end: list[int] = []  # 列ごとの、現在入っている区間の終了分
    group_end = None

    def flush() -> None:
        n = len(column_end)
        for key, col in group:
            result[key] = Placement(col, n)

    for key, s, e in order:
        if group_end is not None and s >= group_end:
            flush()
            group.clear()
            column_end.clear()
            group_end = None
        for col, end in enumerate(column_end):
            if end <= s:
                column_end[col] = e
                break
        else:
            col = len(column_end)
            column_end.append(e)
        group.append((key, col))
        group_end = e if group_end is None else max(group_end, e)
    if group:
        flush()
    return result
