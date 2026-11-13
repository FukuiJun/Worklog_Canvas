"""画面間で共有する状態と変更通知。"""
from __future__ import annotations

import datetime as _dt
from typing import Callable

from PySide6.QtCore import QObject, Signal

from ..core import colors
from ..core.models import Task, Worklog
from ..core.repository import DataFolder, UserRepository
from ..core.settings import Settings
from ..core.undo import WorklogEditor


class AppState(QObject):
    tasks_changed = Signal()
    worklogs_changed = Signal()
    categories_changed = Signal()
    error = Signal(str)  # 操作を受け付けなかったなどの通知（赤で表示）
    info = Signal(str)
    repo_switched = Signal()  # 表示する利用者を切り替えた
    save_state_changed = Signal()  # 未保存の有無が変わった
    settings_changed = Signal()  # 表示時間帯などの設定を変えた

    def __init__(self, folder: DataFolder, repo: UserRepository, settings: Settings,
                 today: Callable[[], _dt.date] = _dt.date.today):
        super().__init__()
        self.folder = folder
        self.repo = repo
        self.settings = settings
        self.today = today
        self.own_repo = repo  # 自分のデータ（他メンバーの閲覧中も保持する）
        self.locked_by: str | None = None  # 他のPCで使用中のため閲覧モードのとき、その相手
        self.editor = WorklogEditor(repo)
        self.category_colors: dict[str, str] = {}
        repo.on_save_state = lambda _r: self.save_state_changed.emit()
        self.reload_categories()

    @property
    def readonly(self) -> bool:
        return self.repo.readonly

    @property
    def viewing_other(self) -> bool:
        return self.repo is not self.own_repo

    @property
    def unsaved(self) -> bool:
        return bool(self.own_repo.pending)

    def switch_to(self, repo: UserRepository) -> None:
        """表示する利用者を切り替える（他メンバーは読み取り専用、自分に戻るときは own_repo）。"""
        self.repo = repo
        self.editor = WorklogEditor(repo)
        self.repo_switched.emit()
        self.tasks_changed.emit()
        self.worklogs_changed.emit()

    def reload_categories(self) -> None:
        """categories.json を読み直す。読めなければ（他の人が保存中に壊れた等）前の色のまま知らせる。"""
        from ..core.storage import JsonFormatError
        try:
            self.category_colors = self.folder.category_colors()
        except (JsonFormatError, OSError) as e:
            self.error.emit(f"カテゴリ（categories.json）を読み込めませんでした: {e}")
            return
        self.categories_changed.emit()

    def tasks_by_id(self) -> dict[str, Task]:
        return {t.id: t for t in self.repo.tasks}

    def task_color(self, task: Task | None) -> str:
        return colors.task_color(task, self.category_colors)

    def worklog_color(self, w: Worklog, tasks_by_id: dict[str, Task] | None = None) -> str:
        return colors.worklog_color(w, tasks_by_id or self.tasks_by_id(), self.category_colors)

    def sub_color(self, kind: str, task_id: str | None, tasks_by_id: dict[str, Task]) -> str:
        if kind == "単発作業":
            return colors.ONEOFF_COLOR
        return colors.task_color(tasks_by_id.get(task_id), self.category_colors)
