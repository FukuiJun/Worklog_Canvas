"""データモデルと入力検証（仕様 5.2）。

JSONのキー名は仕様 5.2 の項目名（日本語）をそのまま使う。
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from . import timeutil as tu

# --- 列挙値 -------------------------------------------------------------
STATUS_NOT_STARTED = "未着手"
STATUS_IN_PROGRESS = "進行中"
STATUS_ON_HOLD = "保留"
STATUS_DONE = "完了"
STATUSES = (STATUS_NOT_STARTED, STATUS_IN_PROGRESS, STATUS_ON_HOLD, STATUS_DONE)

PRIORITIES = ("高", "中", "低")

KIND_TASK = "タスク"
KIND_ONEOFF = "単発作業"
KINDS = (KIND_TASK, KIND_ONEOFF)

SOURCE_MANUAL = "手動"
SOURCE_OUTLOOK = "Outlook"
SOURCES = (SOURCE_MANUAL, SOURCE_OUTLOOK)

TASK_NAME_MAX = 100
ONEOFF_TITLE_MAX = 50
WEEKLY_NOTE_MAX = 400
PROGRESS_STEP = 5
ESTIMATE_STEP = 0.25

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ValidationError(ValueError):
    """入力値が仕様の制約に合わない。field は対象項目名（画面でメッセージを出す位置に使う）。"""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


# --- 検証ヘルパ -----------------------------------------------------------
def validate_progress(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("進捗率", "進捗率は整数で入力してください")
    if not (0 <= value <= 100) or value % PROGRESS_STEP != 0:
        raise ValidationError("進捗率", "進捗率は0〜100の5刻みで入力してください")
    return value


def validate_estimate(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0 or abs(value / ESTIMATE_STEP - round(value / ESTIMATE_STEP)) > 1e-9:
        raise ValidationError("予定工数", "予定工数は0以上の0.25刻みで入力してください")
    return float(value)


# --- タスク ---------------------------------------------------------------
@dataclass
class ProgressEntry:
    date: _dt.date
    progress: int

    def to_dict(self) -> dict:
        return {"日付": self.date.isoformat(), "進捗率": self.progress}

    @classmethod
    def from_dict(cls, d: dict) -> "ProgressEntry":
        return cls(date=_dt.date.fromisoformat(d["日付"]), progress=int(d["進捗率"]))


@dataclass
class Task:
    id: str
    name: str
    category: str = ""
    status: str = STATUS_NOT_STARTED
    priority: str = "中"
    start_date: _dt.date | None = None
    planned_end: _dt.date | None = None  # 完了予定日
    deadline: _dt.date | None = None  # 期限
    done_date: _dt.date | None = None  # 完了日
    estimate_hours: float | None = None  # 予定工数
    progress: int = 0
    history: list[ProgressEntry] = field(default_factory=list)
    memo: str = ""

    # 進捗率（F-03）
    def set_progress(self, value: int, today: _dt.date) -> None:
        """進捗率を変更し、履歴に記録する。同じ日に複数回変更したら最後の値で上書き。

        100にしたときにステータスを完了にするかの確認は画面側で行う
        （needs_done_confirmation を参照）。
        """
        validate_progress(value)
        if value == self.progress:
            return
        self.progress = value
        for entry in self.history:
            if entry.date == today:
                entry.progress = value
                break
        else:
            self.history.append(ProgressEntry(today, value))
            self.history.sort(key=lambda e: e.date)

    def needs_done_confirmation(self) -> bool:
        return self.progress == 100 and self.status != STATUS_DONE

    def set_status(self, status: str, today: _dt.date) -> None:
        """ステータス変更。完了にしたら完了日を自動入力、完了以外に戻したら完了日を消す。"""
        if status not in STATUSES:
            raise ValidationError("ステータス", f"ステータスが不正です: {status}")
        if status == STATUS_DONE and self.status != STATUS_DONE:
            self.done_date = today
        elif status != STATUS_DONE:
            self.done_date = None
        self.status = status

    @property
    def is_open(self) -> bool:
        """未完了か。"""
        return self.status != STATUS_DONE

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValidationError("タスク名", "タスク名を入力してください")
        if len(self.name) > TASK_NAME_MAX:
            raise ValidationError("タスク名", f"タスク名は{TASK_NAME_MAX}文字以内で入力してください")
        if self.status not in STATUSES:
            raise ValidationError("ステータス", f"ステータスが不正です: {self.status}")
        if self.priority not in PRIORITIES:
            raise ValidationError("優先度", f"優先度が不正です: {self.priority}")
        validate_progress(self.progress)
        validate_estimate(self.estimate_hours)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "タスク名": self.name,
            "カテゴリ": self.category,
            "ステータス": self.status,
            "優先度": self.priority,
            "開始日": tu.format_date(self.start_date),
            "完了予定日": tu.format_date(self.planned_end),
            "期限": tu.format_date(self.deadline),
            "完了日": tu.format_date(self.done_date),
            "予定工数": self.estimate_hours,
            "進捗率": self.progress,
            "進捗履歴": [e.to_dict() for e in self.history],
            "メモ": self.memo,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        est = d.get("予定工数")
        return cls(
            id=d["id"],
            name=d["タスク名"],
            category=d.get("カテゴリ") or "",
            status=d.get("ステータス", STATUS_NOT_STARTED),
            priority=d.get("優先度", "中"),
            start_date=tu.parse_date(d.get("開始日")),
            planned_end=tu.parse_date(d.get("完了予定日")),
            deadline=tu.parse_date(d.get("期限")),
            done_date=tu.parse_date(d.get("完了日")),
            estimate_hours=float(est) if est is not None else None,
            progress=int(d.get("進捗率", 0)),
            history=[ProgressEntry.from_dict(e) for e in d.get("進捗履歴", [])],
            memo=d.get("メモ") or "",
        )


# --- 作業バー ---------------------------------------------------------------
@dataclass
class Worklog:
    id: str
    date: _dt.date
    start: int  # 0:00 からの経過分
    end: int
    kind: str = KIND_TASK
    task_id: str | None = None
    title: str = ""
    memo: str = ""
    source: str = SOURCE_MANUAL

    @property
    def duration(self) -> int:
        """所要時間（分）。"""
        return self.end - self.start

    def validate(self) -> None:
        if self.start % tu.SNAP_MINUTES or self.end % tu.SNAP_MINUTES:
            raise ValidationError("時刻", "時刻は15分刻みで指定してください")
        if not (0 <= self.start < self.end <= tu.DAY_MINUTES):
            raise ValidationError("時刻", "終了時刻は開始時刻より後にしてください")
        if self.duration < tu.MIN_DURATION_MINUTES:
            raise ValidationError("時刻", "作業バーは15分以上にしてください")
        if self.kind not in KINDS:
            raise ValidationError("種別", f"種別が不正です: {self.kind}")
        if self.source not in SOURCES:
            raise ValidationError("取込元", f"取込元が不正です: {self.source}")
        if self.kind == KIND_TASK and not self.task_id:
            raise ValidationError("タスク", "タスクを選んでください")
        if self.kind == KIND_ONEOFF:
            if not self.title or not self.title.strip():
                raise ValidationError("タイトル", "タイトルを入力してください")
            if len(self.title) > ONEOFF_TITLE_MAX:
                raise ValidationError("タイトル", f"タイトルは{ONEOFF_TITLE_MAX}文字以内で入力してください")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "日付": self.date.isoformat(),
            "開始時刻": tu.format_hhmm(self.start),
            "終了時刻": tu.format_hhmm(self.end),
            "種別": self.kind,
            "タスクid": self.task_id if self.kind == KIND_TASK else None,
            "タイトル": self.title if self.kind == KIND_ONEOFF else "",
            "メモ": self.memo,
            "取込元": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Worklog":
        return cls(
            id=d["id"],
            date=_dt.date.fromisoformat(d["日付"]),
            start=tu.parse_hhmm(d["開始時刻"]),
            end=tu.parse_hhmm(d["終了時刻"]),
            kind=d.get("種別", KIND_TASK),
            task_id=d.get("タスクid"),
            title=d.get("タイトル") or "",
            memo=d.get("メモ") or "",
            source=d.get("取込元", SOURCE_MANUAL),
        )


# --- 週次メモ・カテゴリ・プロフィール -----------------------------------------
@dataclass
class WeeklyNote:
    week_start: _dt.date
    reflection: str = ""  # 所感・課題
    next_week: str = ""  # 来週の予定

    def validate(self) -> None:
        if self.week_start.weekday() != 0:
            raise ValidationError("週開始日", "週開始日は月曜日にしてください")
        if len(self.reflection) > WEEKLY_NOTE_MAX:
            raise ValidationError("所感・課題", f"所感・課題は{WEEKLY_NOTE_MAX}文字以内で入力してください")
        if len(self.next_week) > WEEKLY_NOTE_MAX:
            raise ValidationError("来週の予定", f"来週の予定は{WEEKLY_NOTE_MAX}文字以内で入力してください")

    def to_dict(self) -> dict:
        return {
            "週開始日": self.week_start.isoformat(),
            "所感・課題": self.reflection,
            "来週の予定": self.next_week,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WeeklyNote":
        return cls(
            week_start=_dt.date.fromisoformat(d["週開始日"]),
            reflection=d.get("所感・課題") or "",
            next_week=d.get("来週の予定") or "",
        )


@dataclass
class Category:
    name: str
    color: str

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValidationError("カテゴリ名", "カテゴリ名を入力してください")
        if not _COLOR_RE.match(self.color):
            raise ValidationError("色", "色は#RRGGBB形式で指定してください")

    def to_dict(self) -> dict:
        return {"カテゴリ名": self.name, "色": self.color}

    @classmethod
    def from_dict(cls, d: dict) -> "Category":
        return cls(name=d["カテゴリ名"], color=d["色"])


@dataclass
class Profile:
    display_name: str

    def to_dict(self) -> dict:
        return {"表示名": self.display_name}

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(display_name=d.get("表示名") or "")
