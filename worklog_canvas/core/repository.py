"""データフォルダと利用者ごとのデータ（仕様 5.2, F-01〜F-03, F-07）。

データフォルダの構成:
    <データフォルダ>/categories.json
    <データフォルダ>/users/<ユーザー名>/tasks.json
    <データフォルダ>/users/<ユーザー名>/worklogs.json
    <データフォルダ>/users/<ユーザー名>/weekly_notes.json
    <データフォルダ>/users/<ユーザー名>/profile.json

各ファイルの形式（例: tasks.json）:
    {"version": 1, "next_id": 4, "tasks": [ {タスク}, ... ]}
"""
from __future__ import annotations

import copy
import datetime as _dt
import os
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable

from . import overlap, storage
from .models import (
    KIND_ONEOFF,
    KIND_TASK,
    ONEOFF_TITLE_MAX,
    Category,
    Profile,
    Task,
    ValidationError,
    WeeklyNote,
    Worklog,
)

SCHEMA_VERSION = 1

TASKS_FILE = "tasks.json"
WORKLOGS_FILE = "worklogs.json"
WEEKLY_NOTES_FILE = "weekly_notes.json"
PROFILE_FILE = "profile.json"
CATEGORIES_FILE = "categories.json"
USERS_DIR = "users"


class ReadOnlyError(PermissionError):
    """閲覧モード（他メンバーのデータ）で書き込もうとした。"""


def _today() -> _dt.date:
    return _dt.date.today()


def _next_id(meta_next: int | None, existing_ids: Iterable[str], prefix: str) -> int:
    n = max(1, int(meta_next or 1))
    for i in existing_ids:
        if i.startswith(prefix):
            try:
                n = max(n, int(i[len(prefix):]) + 1)
            except ValueError:
                pass
    return n


class DataFolder:
    """共有フォルダ上のデータフォルダ。"""

    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    @property
    def users_dir(self) -> Path:
        return self.root / USERS_DIR

    @property
    def categories_path(self) -> Path:
        return self.root / CATEGORIES_FILE

    def list_usernames(self) -> list[str]:
        if not self.users_dir.is_dir():
            return []
        return sorted(p.name for p in self.users_dir.iterdir() if p.is_dir() and not p.name.startswith("."))

    def user(self, username: str, readonly: bool = False) -> "UserRepository":
        repo = UserRepository(self, username, readonly=readonly)
        repo.load()
        return repo

    # --- カテゴリ（全員共通） ---
    def load_categories(self) -> list[Category]:
        data = storage.read_json(self.categories_path, default={"categories": []})
        return [Category.from_dict(d) for d in data.get("categories", [])]

    def add_category(self, category: Category) -> bool:
        """カテゴリを追加する。読み込み直してから追記し、一時ファイル経由で置き換える。

        同名のカテゴリが既にあれば何もしないで False を返す。
        """
        category.validate()
        current = self.load_categories()
        if any(c.name == category.name for c in current):
            return False
        current.append(category)
        storage.atomic_write_json(
            self.categories_path,
            {"version": SCHEMA_VERSION, "categories": [c.to_dict() for c in current]},
        )
        return True

    def category_colors(self) -> dict[str, str]:
        return {c.name: c.color for c in self.load_categories()}


class UserRepository:
    """1人分のデータ。変更系メソッドは呼ぶたびに該当ファイルへ自動保存する。"""

    def __init__(self, folder: DataFolder, username: str, readonly: bool = False,
                 today: Callable[[], _dt.date] = _today):
        self.folder = folder
        self.username = username
        self.readonly = readonly
        self._today = today
        self.tasks: list[Task] = []
        self.worklogs: list[Worklog] = []
        self.weekly_notes: list[WeeklyNote] = []
        self.profile = Profile(display_name=username)
        self._next_task = 1
        self._next_worklog = 1

    # --- パス ---
    @property
    def dir(self) -> Path:
        return self.folder.users_dir / self.username

    def path(self, name: str) -> Path:
        return self.dir / name

    # --- 読み込み ---
    def load(self) -> None:
        t = storage.read_json(self.path(TASKS_FILE), default={})
        self.tasks = [Task.from_dict(d) for d in t.get("tasks", [])]
        self._next_task = _next_id(t.get("next_id"), (x.id for x in self.tasks), "T-")

        w = storage.read_json(self.path(WORKLOGS_FILE), default={})
        self.worklogs = [Worklog.from_dict(d) for d in w.get("worklogs", [])]
        self._next_worklog = _next_id(w.get("next_id"), (x.id for x in self.worklogs), "W-")

        n = storage.read_json(self.path(WEEKLY_NOTES_FILE), default={})
        self.weekly_notes = [WeeklyNote.from_dict(d) for d in n.get("weekly_notes", [])]

        p = storage.read_json(self.path(PROFILE_FILE), default=None)
        self.profile = Profile.from_dict(p) if p else Profile(display_name=self.username)

    # --- 保存 ---
    def _check_writable(self) -> None:
        if self.readonly:
            raise ReadOnlyError("閲覧モードでは編集できません")

    def save_tasks(self) -> None:
        self._check_writable()
        storage.atomic_write_json(self.path(TASKS_FILE), {
            "version": SCHEMA_VERSION,
            "next_id": self._next_task,
            "tasks": [t.to_dict() for t in self.tasks],
        })

    def save_worklogs(self) -> None:
        self._check_writable()
        storage.atomic_write_json(self.path(WORKLOGS_FILE), {
            "version": SCHEMA_VERSION,
            "next_id": self._next_worklog,
            "worklogs": [w.to_dict() for w in sorted(self.worklogs, key=lambda w: (w.date, w.start, w.id))],
        })

    def save_weekly_notes(self) -> None:
        self._check_writable()
        storage.atomic_write_json(self.path(WEEKLY_NOTES_FILE), {
            "version": SCHEMA_VERSION,
            "weekly_notes": [n.to_dict() for n in sorted(self.weekly_notes, key=lambda n: n.week_start)],
        })

    def save_profile(self) -> None:
        self._check_writable()
        storage.atomic_write_json(self.path(PROFILE_FILE), self.profile.to_dict())

    def save_all(self) -> None:
        self.save_profile()
        self.save_tasks()
        self.save_worklogs()
        self.save_weekly_notes()

    # --- タスク（F-01） ---
    def get_task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(task_id)

    def open_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.is_open]

    def add_task(self, task: Task) -> Task:
        """task.id は無視して自動採番する。保存したタスクを返す。"""
        self._check_writable()
        task = replace(task, id=f"T-{self._next_task:04d}")
        task.validate()
        self.tasks.append(task)
        self._next_task += 1
        self.save_tasks()
        return task

    def add_tasks(self, tasks: list[Task]) -> list[Task]:
        """複数のタスクをまとめて追加する（保存は1回）。1件でも不正なら何も追加しない。"""
        self._check_writable()
        added = []
        n = self._next_task
        for t in tasks:
            t = replace(t, id=f"T-{n:04d}")
            t.validate()
            added.append(t)
            n += 1
        if not added:
            return []
        self.tasks.extend(added)
        self._next_task = n
        self.save_tasks()
        return added

    def update_task(self, task: Task) -> None:
        """同じ id のタスクを置き換える（id は変更不可）。"""
        self._check_writable()
        task.validate()
        for i, t in enumerate(self.tasks):
            if t.id == task.id:
                self.tasks[i] = task
                break
        else:
            raise KeyError(task.id)
        self.save_tasks()

    def linked_worklogs(self, task_id: str) -> list[Worklog]:
        """メインまたはサブタスクとしてそのタスクを含む作業バー。"""
        return [w for w in self.worklogs if task_id in w.task_ids()]

    def delete_task(self, task_id: str) -> int:
        """タスクを削除する。紐づく作業バーのメイン・サブタスクは単発作業に変え、
        タイトルに元のタスク名を入れる。

        確認ダイアログは画面側で linked_worklogs() を見て出す。変換した作業バー数を返す。
        """
        self._check_writable()
        task = self.get_task(task_id)
        title = task.name[:ONEOFF_TITLE_MAX]
        linked = self.linked_worklogs(task_id)
        for w in linked:
            if w.kind == KIND_TASK and w.task_id == task_id:
                w.kind, w.task_id, w.title = KIND_ONEOFF, None, title
            for sub in w.subs:
                if sub.kind == KIND_TASK and sub.task_id == task_id:
                    sub.kind, sub.task_id, sub.title = KIND_ONEOFF, None, title
        if linked:
            self.save_worklogs()  # 先に作業バーを保存（途中で落ちても参照切れにならない）
        self.tasks = [t for t in self.tasks if t.id != task_id]
        self.save_tasks()
        return len(linked)

    # --- 進捗率（F-03） ---
    def set_progress(self, task_id: str, value: int, today: _dt.date | None = None) -> Task:
        self._check_writable()
        task = self.get_task(task_id)
        task.set_progress(value, today or self._today())
        self.save_tasks()
        return task

    def set_status(self, task_id: str, status: str, today: _dt.date | None = None) -> Task:
        self._check_writable()
        task = self.get_task(task_id)
        task.set_status(status, today or self._today())
        self.save_tasks()
        return task

    # --- 作業バー（F-02） ---
    def get_worklog(self, worklog_id: str) -> Worklog:
        for w in self.worklogs:
            if w.id == worklog_id:
                return w
        raise KeyError(worklog_id)

    def worklogs_on(self, day: _dt.date) -> list[Worklog]:
        return sorted((w for w in self.worklogs if w.date == day), key=lambda w: (w.start, w.end, w.id))

    def worklogs_between(self, start: _dt.date, end: _dt.date) -> list[Worklog]:
        return sorted((w for w in self.worklogs if start <= w.date <= end),
                      key=lambda w: (w.date, w.start, w.end, w.id))

    def _validate_worklog(self, w: Worklog, exclude_id: str | None = None) -> None:
        w.validate()
        for task_id in w.task_ids():
            self.get_task(task_id)  # 存在しないタスクは KeyError
        same_day = [(x.id, x.start, x.end) for x in self.worklogs if x.date == w.date and x.id != exclude_id]
        overlap.check_no_overlap(w.start, w.end, same_day)

    def add_worklog(self, w: Worklog) -> Worklog:
        """w.id は無視して自動採番する。既存の作業バーと重なる場合は OverlapError。"""
        self._check_writable()
        w = replace(w, id=f"W-{self._next_worklog:06d}")
        self._validate_worklog(w)
        self.worklogs.append(w)
        self._next_worklog += 1
        self.save_worklogs()
        return w

    def update_worklog(self, w: Worklog) -> None:
        """移動・伸縮・編集。検証に失敗したら何も変更しない（操作前の状態のまま）。"""
        self._check_writable()
        self.get_worklog(w.id)
        self._validate_worklog(w, exclude_id=w.id)
        self.worklogs = [w if x.id == w.id else x for x in self.worklogs]
        self.save_worklogs()

    def restore_worklog(self, w: Worklog) -> None:
        """削除した作業バーを同じ id で戻す（元に戻す操作用）。"""
        self._check_writable()
        if any(x.id == w.id for x in self.worklogs):
            raise ValueError(f"作業バー {w.id} は既にあります")
        self._validate_worklog(w)
        self.worklogs.append(w)
        self.save_worklogs()

    def delete_worklog(self, worklog_id: str) -> Worklog:
        self._check_writable()
        w = self.get_worklog(worklog_id)
        self.worklogs = [x for x in self.worklogs if x.id != worklog_id]
        self.save_worklogs()
        return w

    # --- 週次メモ ---
    def get_weekly_note(self, week_start: _dt.date) -> WeeklyNote:
        for n in self.weekly_notes:
            if n.week_start == week_start:
                return copy.copy(n)
        return WeeklyNote(week_start=week_start)

    def set_weekly_note(self, note: WeeklyNote) -> None:
        self._check_writable()
        note.validate()
        self.weekly_notes = [n for n in self.weekly_notes if n.week_start != note.week_start] + [note]
        self.save_weekly_notes()

    # --- プロフィール ---
    def set_display_name(self, name: str) -> None:
        self._check_writable()
        if not name or not name.strip():
            raise ValidationError("表示名", "表示名を入力してください")
        self.profile = Profile(display_name=name.strip())
        self.save_profile()
