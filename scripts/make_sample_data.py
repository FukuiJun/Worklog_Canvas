"""サンプルデータ（仕様 10章）を sample_data/ に生成する。

    python scripts/make_sample_data.py [出力先フォルダ]

3名分。各自タスク8件、作業バー2週間分（2026-11-02〜11-13の平日。11-03は祝日で記録なし）。
作業バーは重ならない。並行作業はサブタスク（メイン1つ＋サブ最大3つ）で記録している。
単発作業（メイン・サブの両方）を含む。手計算の期待値は tests/test_sample_data.py に記載。
サンプルICSファイルは M6 で追加する。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worklog_canvas.core import storage  # noqa: E402
from worklog_canvas.core.models import (  # noqa: E402
    KIND_ONEOFF, KIND_TASK, Category, ProgressEntry, SubItem, Task, Worklog,
    WeeklyNote, Profile,
)
from worklog_canvas.core import timeutil as tu  # noqa: E402
from worklog_canvas.core.repository import SCHEMA_VERSION  # noqa: E402

CATEGORIES = [
    Category("次世代基板", "#2A78D6"),
    Category("治具", "#EB6834"),
    Category("チャージャIC", "#1BAF7A"),
    Category("文書", "#EDA100"),
    Category("管理", "#E87BA4"),
]

D = dt.date


def task(n, name, cat, status, prio, *, start=None, planned=None, deadline=None,
         done=None, est=None, history=(), memo=""):
    hist = [ProgressEntry(D(2026, 11, d), p) for d, p in history]
    return Task(
        id=f"T-{n:04d}", name=name, category=cat, status=status, priority=prio,
        start_date=D(2026, 11, start) if start else None,
        planned_end=D(2026, 11, planned) if planned else None,
        deadline=D(2026, 11, deadline) if deadline else None,
        done_date=D(2026, 11, done) if done else None,
        estimate_hours=est,
        progress=hist[-1].progress if hist else 0,
        history=hist, memo=memo,
    )


# 作業バーの表記: (日, "HH:MM-HH:MM", メイン[, [サブ, ...]])
#   メイン・サブは タスク番号 または "#単発作業のタイトル"
USERS = {
    "fukui": {
        "display": "福井",
        "tasks": [
            task(1, "次世代基板：マイコンのバッテリ読み取り精度の検証・評価", "次世代基板", "進行中", "高",
                 start=2, planned=20, deadline=30, est=16.0,
                 history=[(2, 10), (4, 20), (6, 30), (10, 35), (12, 40)], memo="抵抗変更後の測定は来週"),
            task(2, "IC微小電流測定用の治具作成（INA226＋Arduinoのプログラム）", "治具", "進行中", "中",
                 start=2, planned=20, est=12.0, history=[(4, 30), (6, 40), (9, 50), (12, 60)]),
            task(3, "チャージャIC：10時間充電停止の確認", "チャージャIC", "完了", "中",
                 start=4, done=11, history=[(4, 50), (6, 80), (11, 100)]),
            task(4, "次世代基板：回路図レビュー指摘の反映", "次世代基板", "進行中", "中",
                 start=4, planned=13, deadline=18, history=[(4, 30), (6, 50), (11, 60), (12, 70)]),
            task(5, "評価手順書の改訂", "文書", "保留", "低", history=[(10, 20)]),
            task(6, "試作基板の部品手配", "次世代基板", "完了", "高", start=2, done=5,
                 history=[(2, 50), (5, 100)]),
            task(7, "チャージャIC：温度特性の測定", "チャージャIC", "未着手", "中", planned=27),
            task(8, "月次報告の作成", "管理", "未着手", "低", deadline=30),
        ],
        "worklogs": [
            (2, "09:00-10:00", 6), (2, "10:00-12:00", 1), (2, "13:00-15:00", 2), (2, "15:00-17:30", 1),
            (4, "09:00-09:30", "#朝会"), (4, "09:30-12:00", 4), (4, "13:00-14:00", 3),
            (4, "14:00-15:00", 3, [2]), (4, "15:00-16:00", 2), (4, "16:00-18:00", 1),
            (5, "09:00-12:00", "#製造応援"), (5, "13:00-14:00", 6), (5, "14:00-17:00", 1),
            (6, "09:00-09:30", "#朝会"), (6, "09:30-10:00", 2), (6, "10:00-11:30", 2, [3]),
            (6, "11:30-12:00", 3), (6, "13:00-15:00", 4), (6, "15:00-17:15", 1),
            (9, "09:00-09:30", "#朝会"), (9, "09:30-12:00", 1), (9, "13:00-14:30", 2, [3, "#会議"]),
            (9, "14:30-16:00", 2), (9, "16:00-18:00", 4),
            (10, "09:00-10:00", 1), (10, "10:00-11:30", 1, [2, 3, "#打合せ"]), (10, "11:30-12:00", 1),
            (10, "13:00-17:00", 5),
            (11, "09:00-11:00", 3), (11, "11:00-12:00", 4), (11, "13:00-15:30", 1),
            (11, "15:30-17:30", "#製造応援"),
            (12, "09:00-09:30", "#朝会"), (12, "09:30-12:00", 2), (12, "13:00-15:00", 1, [4]),
            (12, "15:00-16:45", 2),
            (13, "09:00-12:00", 1), (13, "13:00-14:00", "#会議"), (13, "14:00-17:00", 2),
        ],
        "notes": [WeeklyNote(D(2026, 11, 2), reflection="治具の精度確認に想定より時間がかかった")],
    },
    "sato": {
        "display": "佐藤",
        "tasks": [
            task(1, "電源基板：ノイズ対策の評価", "次世代基板", "進行中", "高", start=2, planned=19,
                 deadline=27, est=20.0, history=[(2, 20), (4, 30), (9, 40), (13, 50)]),
            task(2, "治具：負荷試験用電子負荷の制御プログラム", "治具", "進行中", "中", start=2, planned=25,
                 history=[(5, 20), (12, 30)]),
            task(3, "チャージャIC：充電電流プロファイルの確認", "チャージャIC", "進行中", "中", start=4,
                 planned=16, history=[(4, 30), (9, 50), (11, 60)]),
            task(4, "評価結果報告書の作成", "文書", "未着手", "中", planned=30),
            task(5, "測定器の校正手配", "管理", "完了", "低", done=6, history=[(5, 50), (6, 100)]),
            task(6, "次世代基板：EMI事前測定", "次世代基板", "保留", "中", history=[(6, 10)]),
            task(7, "新人向け測定手順の説明資料", "文書", "進行中", "低", history=[(5, 20), (12, 40)]),
            task(8, "治具：ケーブル治具の改修", "治具", "完了", "中", start=9, done=12,
                 history=[(9, 40), (11, 90), (12, 100)]),
        ],
        "worklogs": [
            (2, "09:00-12:00", 1), (2, "13:00-17:00", 2),
            (4, "09:00-10:00", 3), (4, "10:00-11:00", 3, ["#会議"]), (4, "11:00-12:00", 3),
            (4, "13:00-17:00", 1),
            (5, "09:00-11:00", 5), (5, "11:00-12:00", 7), (5, "13:00-18:00", 2),
            (6, "09:00-12:00", "#製造応援"), (6, "13:00-15:00", 1), (6, "15:00-17:00", 6),
            (9, "09:00-12:00", 1), (9, "13:00-15:00", 3, [8]), (9, "15:00-17:00", 3),
            (10, "09:00-12:00", 2), (10, "13:00-14:00", "#会議"), (10, "14:00-17:30", 1),
            (11, "09:00-12:00", 3), (11, "13:00-17:00", 8),
            (12, "09:00-10:00", 7, [1]), (12, "10:00-11:00", 7), (12, "11:00-12:00", 8),
            (12, "13:00-17:00", 2),
            (13, "09:00-12:00", 1), (13, "13:00-16:00", "#製造応援"),
        ],
        "notes": [],
    },
    "suzuki": {
        "display": "鈴木",
        "tasks": [
            task(1, "次世代基板：量産試作スケジュールの調整", "次世代基板", "進行中", "高", start=2,
                 planned=20, deadline=20, history=[(2, 20), (6, 30), (11, 40), (12, 50)]),
            task(2, "チャージャIC：評価結果のレビュー", "チャージャIC", "進行中", "中", start=4, planned=13,
                 history=[(4, 40), (9, 60), (12, 70)]),
            task(3, "治具製作の外注見積り比較", "治具", "完了", "中", start=5, done=10,
                 history=[(5, 50), (10, 100)]),
            task(4, "部内予算の見直し", "管理", "進行中", "中", start=4, planned=27, deadline=30, est=8.0,
                 history=[(4, 10), (11, 20)]),
            task(5, "評価手順書の承認", "文書", "未着手", "低", planned=18),
            task(6, "顧客向け技術資料の確認", "文書", "進行中", "中", start=6, planned=10, deadline=11,
                 history=[(6, 30), (10, 50), (12, 60)]),
            task(7, "次世代基板：部品選定会議の準備", "次世代基板", "完了", "高", start=2, done=4,
                 history=[(2, 50), (4, 100)]),
            task(8, "年末の設備点検計画", "管理", "保留", "低"),
        ],
        "worklogs": [
            (2, "09:00-10:00", "#朝会"), (2, "10:00-12:00", 7), (2, "13:00-17:00", 1),
            (4, "09:00-12:00", 7), (4, "13:00-14:00", 4), (4, "14:00-15:00", 4, [2]), (4, "15:00-16:00", 2),
            (5, "09:00-12:00", 3), (5, "13:00-17:00", "#会議"),
            (6, "09:00-12:00", 1), (6, "13:00-14:00", 6, [2]), (6, "14:00-16:00", 6),
            (9, "09:00-12:00", 2), (9, "13:00-17:00", 1),
            (10, "09:00-11:00", 3), (10, "11:00-12:00", "#打合せ"), (10, "13:00-15:00", 6),
            (10, "15:00-16:00", 6, [4]), (10, "16:00-17:00", 6),
            (11, "09:00-12:00", 4), (11, "13:00-15:00", 1), (11, "15:00-17:00", "#会議"),
            (12, "09:00-10:00", 6), (12, "10:00-11:30", 6, [2, "#打合せ"]), (12, "11:30-12:00", 6),
            (12, "13:00-16:00", 1),
            (13, "09:00-12:00", 2), (13, "13:00-15:00", 4),
        ],
        "notes": [],
    },
}


def _item(target) -> SubItem:
    if isinstance(target, str):
        return SubItem(kind=KIND_ONEOFF, title=target.lstrip("#"))
    return SubItem(kind=KIND_TASK, task_id=f"T-{target:04d}")


def build_worklogs(rows) -> list[Worklog]:
    out = []
    for i, (day, span, main, *rest) in enumerate(rows, start=1):
        s, e = span.split("-")
        m = _item(main)
        w = Worklog(f"W-{i:06d}", D(2026, 11, day), tu.parse_hhmm(s), tu.parse_hhmm(e),
                    kind=m.kind, task_id=m.task_id, title=m.title,
                    subs=[_item(x) for x in (rest[0] if rest else [])])
        w.validate()
        out.append(w)
    return out


def main(out_dir: Path) -> None:
    storage.atomic_write_json(out_dir / "categories.json", {
        "version": SCHEMA_VERSION, "categories": [c.to_dict() for c in CATEGORIES]})
    for username, u in USERS.items():
        d = out_dir / "users" / username
        tasks = u["tasks"]
        for t in tasks:
            t.validate()
        worklogs = build_worklogs(u["worklogs"])
        storage.atomic_write_json(d / "profile.json", Profile(u["display"]).to_dict())
        storage.atomic_write_json(d / "tasks.json", {
            "version": SCHEMA_VERSION, "next_id": len(tasks) + 1, "tasks": [t.to_dict() for t in tasks]})
        storage.atomic_write_json(d / "worklogs.json", {
            "version": SCHEMA_VERSION, "next_id": len(worklogs) + 1,
            "worklogs": [w.to_dict() for w in worklogs]})
        storage.atomic_write_json(d / "weekly_notes.json", {
            "version": SCHEMA_VERSION, "weekly_notes": [n.to_dict() for n in u["notes"]]})
    print(f"サンプルデータを書き出しました: {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "sample_data")
