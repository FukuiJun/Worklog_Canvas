"""タスク取り込み用CSV（仕様 5.2、F-01）。

- 文字コードは UTF-8（BOM付き）または Shift_JIS を自動判定する。
- 1行目は見出し（タスク名,カテゴリ,完了予定日,期限）。列は見出しの名前で探すので順番は問わない。
- タスク名以外は空でよい。categories.json にないカテゴリは自動で追加する。
- 不正な行はスキップし、行番号（ファイルの行番号。見出しが1行目）と理由を返す。
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from .colors import next_category_color
from .models import TASK_NAME_MAX, Category, Task
from .repository import DataFolder, UserRepository

HEADER_NAME = "タスク名"
HEADER_CATEGORY = "カテゴリ"
HEADER_PLANNED = "完了予定日"
HEADER_DEADLINE = "期限"

_DATE_RE = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")


class CsvFormatError(ValueError):
    """ファイル全体が読めない（文字コード不明、見出しがない など）。"""


@dataclass
class ImportResult:
    tasks: list[Task] = field(default_factory=list)  # 追加したタスク
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (行番号, 理由)
    new_categories: list[str] = field(default_factory=list)

    def message(self) -> str:
        text = f"{len(self.tasks)}件のタスクを追加しました。"
        if self.new_categories:
            text += f"\nカテゴリを追加しました: {'、'.join(self.new_categories)}"
        if self.skipped:
            lines = "、".join(str(n) for n, _ in self.skipped)
            text += f"\n{len(self.skipped)}行スキップ（行番号: {lines}）"
            text += "".join(f"\n　{n}行目: {reason}" for n, reason in self.skipped)
        return text


def decode(raw: bytes) -> str:
    """BOM付きなら UTF-8。BOMなしは UTF-8 として厳密に読めればUTF-8、読めなければ Shift_JIS（cp932）。

    Shift_JIS のバイト列が UTF-8 として正しく読めることはまずないため、この順で判定できる。
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise CsvFormatError("文字コードを判定できませんでした（UTF-8 BOM付き または Shift_JIS で保存してください）")


def parse_date(text: str) -> _dt.date | None:
    text = text.strip()
    if not text:
        return None
    m = _DATE_RE.match(text)
    if not m:
        raise ValueError(f"日付の形式が不正です: {text}（例: 2026-11-20）")
    return _dt.date(int(m[1]), int(m[2]), int(m[3]))


def parse(text: str) -> tuple[list[tuple[int, Task]], list[tuple[int, str]]]:
    """CSVの文字列を (行番号, タスク) の一覧とスキップ行に分ける。タスクの id は空。"""
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = list(reader)
    if not rows:
        raise CsvFormatError("ファイルが空です")
    header = [h.strip() for h in rows[0]]
    if HEADER_NAME not in header:
        raise CsvFormatError(f"1行目に見出し「{HEADER_NAME}」がありません")
    col = {name: header.index(name) for name in (HEADER_NAME, HEADER_CATEGORY, HEADER_PLANNED, HEADER_DEADLINE)
           if name in header}

    def cell(row: list[str], name: str) -> str:
        i = col.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    tasks: list[tuple[int, Task]] = []
    skipped: list[tuple[int, str]] = []
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue  # 空行は数えない
        name = cell(row, HEADER_NAME)
        try:
            if not name:
                raise ValueError("タスク名が空です")
            if len(name) > TASK_NAME_MAX:
                raise ValueError(f"タスク名が{TASK_NAME_MAX}文字を超えています")
            task = Task(id="", name=name, category=cell(row, HEADER_CATEGORY),
                        planned_end=parse_date(cell(row, HEADER_PLANNED)),
                        deadline=parse_date(cell(row, HEADER_DEADLINE)))
            task.validate()
        except ValueError as e:
            skipped.append((line_no, str(e)))
            continue
        tasks.append((line_no, task))
    return tasks, skipped


def import_csv(path: str | Path, folder: DataFolder, repo: UserRepository) -> ImportResult:
    """CSVを読み、タスクを一括で追加する（保存は1回）。"""
    raw = Path(path).read_bytes()
    parsed, skipped = parse(decode(raw))
    result = ImportResult(skipped=skipped)
    known = {c.name: c.color for c in folder.load_categories()}
    for _, task in parsed:
        if task.category and task.category not in known:
            color = next_category_color(set(known.values()))
            folder.add_category(Category(task.category, color))
            known[task.category] = color
            result.new_categories.append(task.category)
    result.tasks = repo.add_tasks([t for _, t in parsed])
    return result
