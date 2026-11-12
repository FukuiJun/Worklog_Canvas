"""M5（データ処理）: バックアップ、壊れたJSONの退避と復元、二重起動の検出、カテゴリの変更・削除、チーム一覧、ログ。"""
import datetime as dt
import json
import logging

import pytest

from worklog_canvas.core import applog, backup, storage, team
from worklog_canvas.core.lock import UserLock
from worklog_canvas.core.models import Category, Task, ValidationError
from worklog_canvas.core.repository import CategoryInUseError, DataFolder

D = dt.date


# --- バックアップ（F-07） ---
def test_daily_backup_once_per_day_and_keep_14(sample_folder):
    root = backup.backup_root(sample_folder, "fukui")
    first = backup.make_daily_backup(sample_folder, "fukui", D(2026, 11, 12))
    assert first == root / "20261112"
    assert sorted(p.name for p in first.iterdir()) == [
        "categories.json", "profile.json", "tasks.json", "weekly_notes.json", "worklogs.json"]
    assert backup.make_daily_backup(sample_folder, "fukui", D(2026, 11, 12)) is None  # 同じ日の2回目は作らない
    for i in range(1, 20):
        backup.make_daily_backup(sample_folder, "fukui", D(2026, 11, 12) + dt.timedelta(days=i))
    days = sorted(p.name for p in root.iterdir())
    assert len(days) == 14 and days[0] == "20261118" and days[-1] == "20261201"


def test_backup_does_not_include_itself_or_other_users(sample_folder):
    day = backup.make_daily_backup(sample_folder, "fukui", D(2026, 11, 12))
    assert not (day / "backup").exists()
    assert not (sample_folder.users_dir / "sato" / "backup").exists()


# --- 壊れたJSON（9章） ---
def test_broken_json_quarantine_and_restore(sample_folder):
    backup.make_daily_backup(sample_folder, "fukui", D(2026, 11, 11))
    repo = sample_folder.user("fukui")
    n_before = len(repo.worklogs)
    path = repo.path("worklogs.json")
    good = path.read_bytes()
    path.write_text('{"worklogs": [', encoding="utf-8")
    with pytest.raises(storage.JsonFormatError) as e:
        sample_folder.user("fukui")
    assert e.value.path == path
    moved = backup.quarantine(path, dt.datetime(2026, 11, 12, 9, 30, 5))
    assert moved.name == "worklogs.json.broken_20261112_093005" and not path.exists()
    date, src = backup.backup_file_for(path, sample_folder, "fukui")
    assert date == D(2026, 11, 11)
    backup.restore(src, path)
    assert path.read_bytes() == good
    assert len(sample_folder.user("fukui").worklogs) == n_before


def test_broken_categories_restored_from_own_backup(sample_folder):
    backup.make_daily_backup(sample_folder, "fukui", D(2026, 11, 11))
    sample_folder.categories_path.write_text("xx", encoding="utf-8")
    found = backup.backup_file_for(sample_folder.categories_path, sample_folder, "fukui")
    assert found and found[1].name == "categories.json"


# --- 二重起動（9章） ---
def test_second_pc_gets_readonly(tmp_path):
    t0 = dt.datetime(2026, 11, 12, 9, 0)
    pc1 = UserLock(tmp_path, host="PC-1", pid=100)
    pc2 = UserLock(tmp_path, host="PC-2", pid=200)
    assert pc1.acquire(t0).acquired
    r = pc2.acquire(t0 + dt.timedelta(seconds=30))
    assert not r.acquired and r.other.host == "PC-1"
    # 1台目が更新を続けている間は使用中
    pc1.heartbeat(t0 + dt.timedelta(minutes=5))
    assert not pc2.acquire(t0 + dt.timedelta(minutes=6)).acquired
    # 更新が2分以上止まった（強制終了など）なら引き継げる
    assert pc2.acquire(t0 + dt.timedelta(minutes=8)).acquired
    pc2.release()
    assert not (tmp_path / ".lock").exists()


def test_lock_released_normally(tmp_path):
    pc1 = UserLock(tmp_path, host="PC-1", pid=100)
    pc1.acquire()
    pc1.release()
    assert UserLock(tmp_path, host="PC-2", pid=200).acquire().acquired


def test_same_pc_dead_process_is_taken_over(tmp_path):
    UserLock(tmp_path, host="PC-1", pid=999999).acquire()  # 存在しないプロセス
    assert UserLock(tmp_path, host="PC-1", pid=100).acquire().acquired


# --- カテゴリの変更・削除（5.2） ---
def test_category_rename_and_delete_only_when_unused(sample_folder):
    repo = sample_folder.user("fukui")
    with pytest.raises(CategoryInUseError):
        sample_folder.delete_category("治具", repo.tasks)
    with pytest.raises(CategoryInUseError):
        sample_folder.rename_category("治具", "治工具", repo.tasks)
    sample_folder.add_category(Category("未使用", "#123456"))
    sample_folder.rename_category("未使用", "使っていない", repo.tasks)
    assert "使っていない" in sample_folder.category_colors()
    with pytest.raises(ValidationError):
        sample_folder.rename_category("使っていない", "治具", repo.tasks)  # 既にある名前
    sample_folder.delete_category("使っていない", repo.tasks)
    assert "使っていない" not in sample_folder.category_colors()


# --- チーム一覧（F-08） ---
def test_team_members_and_day(sample_folder):
    me = sample_folder.user("fukui")
    members = team.load_members(sample_folder, me)
    assert [m.display_name for m in members] == ["福井", "佐藤", "鈴木"]
    assert members[0].repo is me and all(m.repo.readonly for m in members[1:])
    day = team.team_day(members, D(2026, 11, 12))
    assert [d.working / 60 for d in day] == [6.75, 7.0, 6.0]
    assert [t.id for t in day[0].in_progress] == ["T-0004", "T-0001", "T-0002"]
    assert all(t.status == "進行中" for d in day for t in d.in_progress)


def test_team_unreadable_member_does_not_stop_others(sample_folder):
    (sample_folder.users_dir / "sato" / "tasks.json").write_text("{", encoding="utf-8")
    members = team.load_members(sample_folder, sample_folder.user("fukui"))
    sato = next(m for m in members if m.username == "sato")
    assert not sato.ok and sato.error
    assert sum(m.ok for m in members) == 2
    days = team.team_day(members, D(2026, 11, 12))
    assert days[members.index(sato)].worklogs == [] and days[0].working == 405


def test_readonly_member_cannot_write(sample_folder):
    other = sample_folder.user("sato", readonly=True)
    from worklog_canvas.core.repository import ReadOnlyError
    with pytest.raises(ReadOnlyError):
        other.add_task(Task(id="", name="x"))
    with pytest.raises(ReadOnlyError):
        other.delete_worklog(other.worklogs[0].id)


def test_display_name(sample_folder):
    repo = sample_folder.user("fukui")
    repo.set_display_name(" 福井 J ")
    assert DataFolder(sample_folder.root).user("fukui").profile.display_name == "福井 J"
    with pytest.raises(ValidationError):
        repo.set_display_name("  ")


# --- ログ（8章） ---
def test_log_rotation_settings(tmp_path):
    logger = applog.setup(tmp_path)
    handler = next(h for h in logger.handlers if hasattr(h, "maxBytes"))
    assert handler.maxBytes == 1_000_000 and handler.backupCount == 2
    logger.info("起動")
    handler.flush()
    assert "起動" in (tmp_path / "app.log").read_text("utf-8")
    logger.removeHandler(handler)
    handler.close()
