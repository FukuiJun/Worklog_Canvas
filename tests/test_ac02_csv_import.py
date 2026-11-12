"""AC-02: 5.2のサンプルCSVを取り込むと3件のタスクが追加され、2件目の完了予定日が2026-11-20になる（F-01）。"""
import datetime as dt
from pathlib import Path

import pytest

from worklog_canvas.core import csv_import
from worklog_canvas.core.models import Category, Task
from worklog_canvas.core.repository import DataFolder

DATA = Path(__file__).parent / "data"


@pytest.mark.parametrize("name", ["sample_tasks_utf8bom.csv", "sample_tasks_sjis.csv"])
def test_ac02_sample_csv(data_folder, name):
    data_folder.add_category(Category("次世代基板", "#2A78D6"))
    repo = data_folder.user("fukui")
    repo.add_task(Task(id="", name="既存のタスク"))
    result = csv_import.import_csv(DATA / name, data_folder, repo)

    assert len(result.tasks) == 3 and result.skipped == []
    again = DataFolder(data_folder.root).user("fukui")  # 保存されている
    new = again.tasks[1:]
    assert [t.id for t in new] == ["T-0002", "T-0003", "T-0004"]
    assert new[0].name == "次世代基板：抵抗変更等によるマイコンのバッテリ読み取り精度の検証・評価"
    assert new[1].planned_end == dt.date(2026, 11, 20)
    assert new[1].deadline is None and new[0].planned_end is None
    assert [t.category for t in new] == ["次世代基板", "治具", "チャージャIC"]
    assert all(t.status == "未着手" and t.priority == "中" and t.progress == 0 for t in new)
    # categories.json にないカテゴリは自動で追加
    assert result.new_categories == ["治具", "チャージャIC"]
    cats = {c.name: c.color for c in data_folder.load_categories()}
    assert set(cats) == {"次世代基板", "治具", "チャージャIC"}
    assert len(set(cats.values())) == 3  # 色は重ならない


def test_csv_invalid_rows_are_skipped_with_line_numbers(data_folder, tmp_path):
    p = tmp_path / "bad.csv"
    p.write_bytes(("﻿タスク名,カテゴリ,完了予定日,期限\n"
                   "OK1,,2026/11/20,\n"
                   ",治具,,\n"  # 3行目: タスク名が空
                   "\n"  # 空行は数えない
                   "日付が変,,11月20日,\n"  # 5行目
                   + "長" * 101 + ",,,\n"  # 6行目
                   "OK2,,,2026-12-01\n").encode("utf-8"))
    repo = data_folder.user("fukui")
    result = csv_import.import_csv(p, data_folder, repo)
    assert [t.name for t in result.tasks] == ["OK1", "OK2"]
    assert result.tasks[0].planned_end == dt.date(2026, 11, 20)
    assert [n for n, _ in result.skipped] == [3, 5, 6]
    assert "3行スキップ（行番号: 3、5、6）" in result.message()


def test_csv_columns_found_by_header_name(data_folder, tmp_path):
    p = tmp_path / "order.csv"
    p.write_bytes("期限,タスク名\r\n2026-11-30,順番違い\r\n".encode("cp932"))
    result = csv_import.import_csv(p, data_folder, data_folder.user("fukui"))
    assert (result.tasks[0].name, result.tasks[0].deadline) == ("順番違い", dt.date(2026, 11, 30))


def test_csv_utf8_without_bom_and_quoted_commas(data_folder, tmp_path):
    p = tmp_path / "nobom.csv"
    p.write_text('タスク名,カテゴリ\n"評価, まとめ",\n', encoding="utf-8")
    result = csv_import.import_csv(p, data_folder, data_folder.user("fukui"))
    assert result.tasks[0].name == "評価, まとめ"


@pytest.mark.parametrize("content", [b"", "名前,カテゴリ\nA,\n".encode("utf-8"), b"\x81\x81\xff\xfe\xfd"])
def test_csv_unreadable_file(data_folder, tmp_path, content):
    p = tmp_path / "x.csv"
    p.write_bytes(content)
    with pytest.raises(csv_import.CsvFormatError):
        csv_import.import_csv(p, data_folder, data_folder.user("fukui"))
    assert data_folder.user("fukui").tasks == []
