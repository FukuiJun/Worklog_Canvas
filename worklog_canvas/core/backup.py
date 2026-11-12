"""バックアップと、壊れたJSONの退避・復元（F-07、仕様9章）。

<自分のフォルダ>/backup/<YYYYMMDD>/ に、その日最初の起動時だけJSONをコピーする（直近14日分を保持）。
共有の categories.json も、復元できるように自分のバックアップに含める。
"""
from __future__ import annotations

import datetime as _dt
import re
import shutil
from pathlib import Path

from .repository import CATEGORIES_FILE, USER_FILES, DataFolder

BACKUP_DIR = "backup"
KEEP_DAYS = 14
_DAY_RE = re.compile(r"^\d{8}$")


def backup_root(folder: DataFolder, username: str) -> Path:
    return folder.users_dir / username / BACKUP_DIR


def _day_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and _DAY_RE.match(p.name)), key=lambda p: p.name)


def make_daily_backup(folder: DataFolder, username: str, today: _dt.date, keep: int = KEEP_DAYS) -> Path | None:
    """その日最初の1回だけバックアップを作る。作ったらそのフォルダを、既にあれば None を返す。"""
    root = backup_root(folder, username)
    day = root / today.strftime("%Y%m%d")
    if day.exists():
        return None
    tmp = root / f".{day.name}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    sources = [folder.users_dir / username / name for name in USER_FILES] + [folder.categories_path]
    for src in sources:
        if src.is_file():
            shutil.copy2(src, tmp / src.name)
    tmp.rename(day)  # 途中で落ちても中途半端なバックアップを「その日の分」と見なさない
    for old in _day_dirs(root)[:-keep]:
        shutil.rmtree(old, ignore_errors=True)
    return day


def latest_backup_of(folder: DataFolder, username: str, filename: str) -> tuple[_dt.date, Path] | None:
    """filename の最新のバックアップ（日付, パス）。無ければ None。"""
    for d in reversed(_day_dirs(backup_root(folder, username))):
        f = d / filename
        if f.is_file():
            return _dt.datetime.strptime(d.name, "%Y%m%d").date(), f
    return None


def quarantine(path: Path, now: _dt.datetime) -> Path:
    """壊れたファイルを <名前>.broken_<日時> に改名する。"""
    dst = path.with_name(f"{path.name}.broken_{now:%Y%m%d_%H%M%S}")
    n = 1
    while dst.exists():
        dst = path.with_name(f"{path.name}.broken_{now:%Y%m%d_%H%M%S}_{n}")
        n += 1
    path.rename(dst)
    return dst


def restore(backup_file: Path, target: Path) -> None:
    tmp = target.with_name(f".{target.name}.restore.tmp")
    shutil.copy2(backup_file, tmp)
    tmp.replace(target)


def backup_file_for(path: Path, folder: DataFolder, username: str) -> tuple[_dt.date, Path] | None:
    """壊れたファイル path に対応するバックアップを探す（categories.json も自分のバックアップから）。"""
    name = CATEGORIES_FILE if path == folder.categories_path else path.name
    return latest_backup_of(folder, username, name)
