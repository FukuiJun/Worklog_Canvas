"""JSONファイルの読み書き（F-07）。

保存は「同じフォルダの一時ファイルに書き、fsync してから os.replace で置き換える」。
途中で例外が起きても元のファイルは変更されない（AC-18）。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class JsonFormatError(ValueError):
    """JSONが壊れていて読めない（9章: 改名とバックアップ復元は M5 で画面と合わせて実装）。"""

    def __init__(self, path: Path, cause: Exception):
        super().__init__(f"JSONを読み取れませんでした: {path}: {cause}")
        self.path = Path(path)
        self.cause = cause


def dumps(data: Any) -> str:
    """UTF-8・LF・日本語はそのまま、で整形した文字列（末尾改行あり）。"""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def atomic_write_text(path: str | os.PathLike, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")  # BOMなし
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: str | os.PathLike, data: Any) -> None:
    # 直列化はファイルに触る前に済ませる（直列化での失敗でファイルを壊さない）
    atomic_write_text(path, dumps(data))


def read_json(path: str | os.PathLike, default: Any = None) -> Any:
    """JSONを読む。ファイルが無ければ default を返す。壊れていれば JsonFormatError。"""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise JsonFormatError(path, e) from e
