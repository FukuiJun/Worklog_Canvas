"""AC-18: 保存処理の途中で例外が起きても、元のJSONが壊れない（F-07）。"""
import json
import os

import pytest

from worklog_canvas.core import storage
from worklog_canvas.core.models import Task


@pytest.fixture
def saved(data_folder):
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="元のタスク"))
    path = repo.path("tasks.json")
    return repo, path, path.read_bytes()


def _leftover_tmp(path):
    return [p for p in path.parent.iterdir() if p.name.endswith(".tmp")]


def test_ac18_exception_while_writing(saved, monkeypatch):
    repo, path, original = saved

    real_fdopen = os.fdopen

    class Broken:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

        def write(self, data):
            self.f.write(data[: len(data) // 2])  # 半分書いたところで失敗
            raise OSError("ディスク障害（テスト）")

    monkeypatch.setattr(storage.os, "fdopen", lambda fd, mode: Broken(real_fdopen(fd, mode)))
    repo.tasks[0].name = "書き換え途中"
    with pytest.raises(OSError):
        repo.save_tasks()
    assert path.read_bytes() == original
    assert _leftover_tmp(path) == []


def test_ac18_exception_on_fsync(saved, monkeypatch):
    repo, path, original = saved
    monkeypatch.setattr(storage.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync失敗")))
    repo.tasks[0].name = "書き換え途中"
    with pytest.raises(OSError):
        repo.save_tasks()
    assert path.read_bytes() == original
    assert _leftover_tmp(path) == []


def test_ac18_exception_on_replace(saved, monkeypatch):
    repo, path, original = saved
    monkeypatch.setattr(storage.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("使用中")))
    repo.tasks[0].name = "書き換え途中"
    with pytest.raises(PermissionError):
        repo.save_tasks()
    assert path.read_bytes() == original
    assert _leftover_tmp(path) == []


def test_ac18_exception_during_serialization(saved):
    repo, path, original = saved
    with pytest.raises(TypeError):
        storage.atomic_write_json(path, {"tasks": [object()]})
    assert path.read_bytes() == original
    assert _leftover_tmp(path) == []


def test_ac18_keyboard_interrupt_is_also_safe(saved, monkeypatch):
    repo, path, original = saved
    monkeypatch.setattr(storage.os, "replace", lambda a, b: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        repo.save_tasks()
    assert path.read_bytes() == original
    assert _leftover_tmp(path) == []


def test_ac18_successful_save_replaces_content(saved):
    repo, path, original = saved
    repo.tasks[0].name = "新しい名前"
    repo.save_tasks()
    assert json.loads(path.read_text("utf-8"))["tasks"][0]["タスク名"] == "新しい名前"
    assert _leftover_tmp(path) == []


def test_broken_json_is_reported(tmp_path):
    p = tmp_path / "tasks.json"
    p.write_text('{"tasks": [', encoding="utf-8")
    with pytest.raises(storage.JsonFormatError):
        storage.read_json(p)
