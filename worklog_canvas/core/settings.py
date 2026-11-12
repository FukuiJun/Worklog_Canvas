"""%APPDATA%/WorklogCanvas/settings.json（仕様 5.2）。"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import storage
from . import timeutil as tu

APP_DIR_NAME = "WorklogCanvas"
DEFAULT_VIEW_START = "08:00"
DEFAULT_VIEW_END = "20:00"


def app_dir() -> Path:
    """設定・ログの保存先。環境変数 WORKLOG_CANVAS_HOME があればそれを使う（テスト・開発用）。"""
    override = os.environ.get("WORKLOG_CANVAS_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


@dataclass
class Settings:
    data_folder: str | None = None
    view_start: str = DEFAULT_VIEW_START  # タイムラインの表示開始時刻（Q-05）
    view_end: str = DEFAULT_VIEW_END
    view_mode: str = "week"  # "day" / "week"
    ics_path: str | None = None  # M6
    report_dir: str | None = None  # 週報を最後に保存したフォルダ
    csv_dir: str | None = None  # CSVを最後に選んだフォルダ

    @property
    def view_range(self) -> tuple[int, int]:
        """表示範囲（分）。不正な値なら既定値。"""
        try:
            s, e = tu.parse_hhmm(self.view_start), tu.parse_hhmm(self.view_end)
            if s % 60 == 0 and e % 60 == 0 and s < e:
                return s, e
        except ValueError:
            pass
        return tu.parse_hhmm(DEFAULT_VIEW_START), tu.parse_hhmm(DEFAULT_VIEW_END)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or app_dir() / "settings.json"
        try:
            data = storage.read_json(path, default={}) or {}
        except storage.JsonFormatError:
            data = {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        storage.atomic_write_json(path or app_dir() / "settings.json", asdict(self))
