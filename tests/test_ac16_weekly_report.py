"""AC-16: サンプルデータの週報で、タスク実績表の行数・並び順・各セルの値が期待値と一致する（xlsxを読み戻して検証）（F-06）。

期待値は scripts/make_sample_data.py の福井さんのデータ（2026/11/09の週）から手で計算したもの。
"""
import datetime as dt

import pytest

openpyxl = pytest.importorskip("openpyxl")

from worklog_canvas.core import weekly_report as wr  # noqa: E402
from worklog_canvas.core.models import Task, WeeklyNote, Worklog  # noqa: E402

D = dt.date
WEEK = D(2026, 11, 9)
TODAY = D(2026, 11, 13)

# (カテゴリ, タスク名, ステータス, 今週h, 今週サブh, 累計h, 週初%, 週末%, 完了予定日, 期限)
EXPECTED_ROWS = [
    ("チャージャIC", "チャージャIC：10時間充電停止の確認", "完了", 2.0, 3.0, 4.5, 80, 100, None, None),
    ("次世代基板", "次世代基板：マイコンのバッテリ読み取り精度の検証・評価", "進行中", 13.0, 0.0, 24.75, 30, 40,
     D(2026, 11, 20), D(2026, 11, 30)),
    ("治具", "IC微小電流測定用の治具作成（INA226＋Arduinoのプログラム）", "進行中", 10.25, 1.5, 15.25, 40, 60,
     D(2026, 11, 20), None),
    ("次世代基板", "次世代基板：回路図レビュー指摘の反映", "進行中", 3.0, 2.0, 7.5, 50, 70,
     D(2026, 11, 13), D(2026, 11, 18)),
    ("文書", "評価手順書の改訂", "保留", 4.0, 0.0, 4.0, 0, 20, None, None),
]


def _report(sample_folder, note=None):
    repo = sample_folder.user("fukui")
    cats = sample_folder.category_colors()
    return wr.build_report(repo.tasks, repo.worklogs, note or repo.get_weekly_note(WEEK), "福井", WEEK, TODAY,
                           list(cats), cats)


def _find(ws, text, col=1):
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, col).value == text:
            return r
    raise AssertionError(f"{text} が見つからない")


def test_ac16_task_table_read_back(sample_folder, tmp_path):
    rep = _report(sample_folder)
    path = wr.write_xlsx(rep, tmp_path / rep.filename)
    assert path.name == "週報_福井_20261109.xlsx"
    ws = openpyxl.load_workbook(path).active

    head = _find(ws, "カテゴリ")
    assert [ws.cell(head, c).value for c in range(1, 10)] == wr.TABLE_HEADER
    got = []
    r = head + 1
    while ws.cell(r, 2).value:
        c = [ws.cell(r, i) for i in range(1, 10)]
        start = int(c[6].number_format.split("%")[0].strip('"'))  # 週初は表示形式に入っている
        dates = [x.value.date() if x.value else None for x in c[7:9]]
        got.append((c[0].value, c[1].value, c[2].value, c[3].value, c[4].value, c[5].value, start, c[6].value,
                    *dates))
        r += 1
    assert len(got) == 5  # 行数
    assert got == EXPECTED_ROWS  # 並び順と各セルの値
    # 進捗率のセル内の横棒（データバー）
    rules = [rule for cf in ws.conditional_formatting for rule in cf.rules]
    assert any(rule.type == "dataBar" for rule in rules)


def test_ac16_other_sections(sample_folder, tmp_path):
    note = WeeklyNote(WEEK, reflection="治具の精度確認に想定より時間がかかった", next_week="")
    rep = _report(sample_folder, note)
    ws = openpyxl.load_workbook(wr.write_xlsx(rep, tmp_path / "w.xlsx")).active
    # ヘッダー・サマリー
    assert ws["A1"].value == "週報" and ws["B2"].value == "福井" and ws["D2"].value == "2026/11/09〜11/15"
    assert ws["H2"].value == "2026/11/13"
    r = _find(ws, "稼働時間の合計")
    assert (ws.cell(r, 2).value, ws.cell(r, 5).value, ws.cell(r, 8).value) == (36.25, 1, 3)
    # 単発作業（時系列、メイン合計 4.0h）
    r = _find(ws, "日付") + 1
    oneoffs = []
    while ws.cell(r, 1).value and ws.cell(r, 1).value.startswith("11/"):
        oneoffs.append((ws.cell(r, 1).value, ws.cell(r, 2).value, ws.cell(r, 3).value, ws.cell(r, 7).value))
        r += 1
    assert oneoffs == [
        ("11/09(月)", "09:00〜09:30", "朝会", "メイン"),
        ("11/09(月)", "13:00〜14:30", "会議", "サブ"),
        ("11/10(火)", "10:00〜11:30", "打合せ", "サブ"),
        ("11/11(水)", "15:30〜17:30", "製造応援", "メイン"),
        ("11/12(木)", "09:00〜09:30", "朝会", "メイン"),
        ("11/13(金)", "13:00〜14:00", "会議", "メイン"),
    ]
    assert (ws.cell(r, 7).value, ws.cell(r, 8).value) == ("合計", 4.0)
    # 日別の時間
    r = _find(ws, "稼働時間(h)", col=2) + 1
    assert [ws.cell(r + i, 2).value for i in range(7)] == [8.0, 7.0, 7.5, 6.75, 7.0, 0, 0]
    assert len(ws._charts) == 1
    # 来週の予定（入力なし → 未完了タスクを完了予定日の近い順に5件）・所感・課題
    texts = [ws.cell(i, 1).value for i in range(1, ws.max_row + 1)]
    auto = next(t for t in texts if isinstance(t, str) and t.startswith("・次世代基板：回路図"))
    assert auto.split("\n") == [
        "・次世代基板：回路図レビュー指摘の反映（完了予定 11/13）",
        "・次世代基板：マイコンのバッテリ読み取り精度の検証・評価（完了予定 11/20）",
        "・IC微小電流測定用の治具作成（INA226＋Arduinoのプログラム）（完了予定 11/20）",
        "・チャージャIC：温度特性の測定（完了予定 11/27）",
        "・評価手順書の改訂（完了予定 未設定）",
    ]
    assert "治具の精度確認に想定より時間がかかった" in texts
    # 印刷設定: A4縦・1ページ
    assert int(ws.page_setup.paperSize) == int(ws.PAPERSIZE_A4) and ws.page_setup.orientation == "portrait"
    assert (ws.page_setup.fitToWidth, ws.page_setup.fitToHeight) == (1, 1)


def test_next_week_uses_input_when_given(sample_folder):
    rep = _report(sample_folder, WeeklyNote(WEEK, next_week="試作基板の評価に着手"))
    assert rep.next_week == "試作基板の評価に着手" and not rep.next_week_auto


def test_text_copy_has_sections_3_4_6_7(sample_folder):
    note = WeeklyNote(WEEK, reflection="所感です", next_week="来週です")
    text = wr.report_text(_report(sample_folder, note))
    lines = text.splitlines()
    assert lines[0] == "■タスク実績（2026/11/09〜11/15）"
    assert lines[1] == "・[完了] チャージャIC：10時間充電停止の確認（チャージャIC）　今週 2.0h／サブ 3.0h／累計 4.5h／進捗 80%→100%"
    assert "■単発作業" in lines and "■来週の予定" in lines and "■所感・課題" in lines
    assert "・11/09(月) 13:00〜14:30 会議（サブ）" in lines
    assert "合計 4.0h（サブとして記録した分 3.0h は含まない）" in lines
    assert lines[lines.index("■来週の予定") + 1] == "来週です"
    assert lines[lines.index("■所感・課題") + 1] == "所感です"
    assert "■サマリー" not in text and "日別" not in text  # 1・2・5は含めない


def test_empty_week(sample_folder, tmp_path):
    repo = sample_folder.user("fukui")
    rep = wr.build_report(repo.tasks, repo.worklogs, None, "福井", D(2026, 11, 16), TODAY)
    assert rep.is_empty
    with pytest.raises(wr.ReportEmptyError) as e:
        wr.write_xlsx(rep, tmp_path / "x.xlsx")
    assert str(e.value) == "対象週の記録がありません"
    assert not (tmp_path / "x.xlsx").exists()


def test_more_than_20_rows_continue_on_page_2(tmp_path):
    tasks = [Task(f"T-{i:04d}", f"タスク{i}", status="進行中") for i in range(1, 24)]
    logs = [Worklog(f"W-{i}", WEEK, 15 * i, 15 * i + 15, task_id=t.id) for i, t in enumerate(tasks)]
    rep = wr.build_report(tasks, logs, None, "福井", WEEK, TODAY)
    ws = openpyxl.load_workbook(wr.write_xlsx(rep, tmp_path / "w.xlsx")).active
    head = _find(ws, "カテゴリ")
    assert ws.page_setup.fitToHeight == 0
    assert [b.id for b in ws.row_breaks.brk] == [head + 20]
    assert ws.cell(head + 21, 1).value == "カテゴリ"  # 2ページ目の先頭で見出しを繰り返す
    names = [ws.cell(r, 2).value for r in range(head + 1, head + 25) if ws.cell(r, 1).value != "カテゴリ"]
    assert len([n for n in names if n and n.startswith("タスク")]) == 23


def test_locked_file_message(sample_folder, tmp_path, monkeypatch):
    rep = _report(sample_folder)
    out = tmp_path / "out"
    out.mkdir()
    target = out / rep.filename

    def locked(a, b):
        raise PermissionError(13, "used by another process")
    monkeypatch.setattr(wr.os, "replace", locked)
    with pytest.raises(wr.ReportLockedError) as e:
        wr.write_xlsx(rep, target)
    assert str(e.value) == "ファイルを閉じてから再度実行してください"
    assert list(out.iterdir()) == []  # 一時ファイルも残らない
