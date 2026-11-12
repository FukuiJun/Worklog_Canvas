"""作業バーの重なり判定（F-02）。

作業バー同士は重ねられない。並行作業はサブタスクで記録する。
区間は半開区間 [start, end) として扱う。10:00〜12:00 と 12:00〜13:00 は重ならない（接する配置は可）。
"""
from __future__ import annotations

from typing import Hashable, Iterable

OVERLAP_MESSAGE = "この時間帯にはすでに作業バーがあります。並行作業はサブタスクとして追加してください"


class OverlapError(ValueError):
    def __init__(self, conflicts: list[Hashable]):
        super().__init__(OVERLAP_MESSAGE)
        self.conflicts = conflicts  # 重なった既存の作業バーのキー


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def find_overlaps(start: int, end: int, existing: Iterable[tuple[Hashable, int, int]]) -> list[Hashable]:
    """[start, end) と重なる既存区間のキーを返す。"""
    return [k for k, s, e in existing if overlaps(start, end, s, e)]


def check_no_overlap(start: int, end: int, existing: Iterable[tuple[Hashable, int, int]]) -> None:
    conflicts = find_overlaps(start, end, existing)
    if conflicts:
        raise OverlapError(conflicts)


def first_overlap_in(intervals: Iterable[tuple[Hashable, int, int]]) -> tuple[Hashable, Hashable] | None:
    """区間の集まりの中に重なりがあれば、最初に見つかった1組のキーを返す（データ検査用）。"""
    prev = None
    for k, s, e in sorted(intervals, key=lambda x: (x[1], x[2])):
        if prev is not None and s < prev[2]:
            return prev[0], k
        if prev is None or e > prev[2]:
            prev = (k, s, e)
    return None
