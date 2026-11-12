"""作業バー操作の取り消し（F-02: Ctrl+Z、20操作まで）。

タイムラインでの作業バーの作成・変更・削除はこのクラスを通して行い、逆操作を記録する。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from .models import Worklog
from .repository import UserRepository

UNDO_LIMIT = 20


@dataclass
class _Op:
    kind: str  # "add" / "update" / "delete"
    before: Worklog | None
    after: Worklog | None
    label: str


class WorklogEditor:
    def __init__(self, repo: UserRepository, limit: int = UNDO_LIMIT):
        self.repo = repo
        self.limit = limit
        self._stack: list[_Op] = []

    def _push(self, op: _Op) -> None:
        self._stack.append(op)
        del self._stack[:-self.limit]

    # --- 操作（失敗したら例外。記録もしない） ---
    def add(self, w: Worklog, label: str = "作成") -> Worklog:
        new = self.repo.add_worklog(copy.deepcopy(w))
        self._push(_Op("add", None, copy.deepcopy(new), label))
        return new

    def update(self, w: Worklog, label: str = "変更") -> None:
        old = copy.deepcopy(self.repo.get_worklog(w.id))
        new = copy.deepcopy(w)
        self.repo.update_worklog(new)
        self._push(_Op("update", old, copy.deepcopy(new), label))

    def delete(self, worklog_id: str, label: str = "削除") -> Worklog:
        old = self.repo.delete_worklog(worklog_id)
        self._push(_Op("delete", copy.deepcopy(old), None, label))
        return old

    # --- 取り消し ---
    @property
    def can_undo(self) -> bool:
        return bool(self._stack)

    def __len__(self) -> int:
        return len(self._stack)

    def undo(self) -> str | None:
        """直前の操作を取り消し、その操作名を返す。取り消すものが無ければ None。

        取り消しに失敗した場合（タスクが削除されたなど）は例外を送出し、その操作は記録から消える。
        """
        if not self._stack:
            return None
        op = self._stack.pop()
        if op.kind == "add":
            self.repo.delete_worklog(op.after.id)
        elif op.kind == "update":
            self.repo.update_worklog(copy.deepcopy(op.before))
        elif op.kind == "delete":
            self.repo.restore_worklog(copy.deepcopy(op.before))
        return op.label

    def clear(self) -> None:
        self._stack.clear()
