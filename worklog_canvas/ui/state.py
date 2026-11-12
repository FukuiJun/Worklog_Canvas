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

    def __init__(self, folder: DataFolder, repo: UserRepository, settings: Settings,
                 today: Callable[[], _dt.date] = _dt.date.today):
        super().__init__()
        self.folder = folder
        self.repo = repo
        self.settings = settings
        self.today = today
        self.editor = WorklogEditor(repo)
        self.category_colors: dict[str, str] = {}
        self.reload_categories()

    @property
    def readonly(self) -> bool:
        return self.repo.readonly

    def reload_categories(self) -> None:
        self.category_colors = self.folder.category_colors()
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
