"""性能確認用のデータを作る（仕様8章、AC-22）。

    python scripts/make_perf_data.py <出力先フォルダ> [--members 10] [--tasks 500] [--worklogs 5000] [--ics-events 2000]

- 利用者ごとに タスク500件・作業バー5000件（1人目は必ず。2人目以降も同じ量）
- 予定2000件の予定表ファイル（<出力先>/perf_calendar.ics）
作業バーは、今日を含む週から過去にさかのぼって平日に並べる（重ならない、サブタスク付きを含む）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worklog_canvas.core import storage  # noqa: E402
from worklog_canvas.core.colors import CATEGORY_PALETTE  # noqa: E402
from worklog_canvas.core.models import (  # noqa: E402
    KIND_ONEOFF, KIND_TASK, STATUSES, Category, ProgressEntry, Profile, SubItem, Task, Worklog,
)
from worklog_canvas.core.repository import SCHEMA_VERSION  # noqa: E402

CATEGORIES = ["次世代基板", "治具", "チャージャIC", "文書", "管理", "評価", "試作", "その他"]
SLOTS = [(540, 600), (600, 720), (780, 870), (870, 960), (960, 1080)]  # 1日5本（9:00〜18:00）


def make_user(root: Path, username: str, display: str, n_tasks: int, n_logs: int, today: dt.date,
              rnd: random.Random) -> None:
    d = root / "users" / username
    tasks = []
    for i in range(1, n_tasks + 1):
        status = STATUSES[i % 4]
        hist = [ProgressEntry(today - dt.timedelta(days=7 * k), min(100, 10 * (5 - k))) for k in range(4, 0, -1)]
        tasks.append(Task(
            id=f"T-{i:04d}", name=f"性能確認用タスク{i:04d}：{CATEGORIES[i % 8]}の作業項目", category=CATEGORIES[i % 8],
            status=status, priority=("高", "中", "低")[i % 3],
            planned_end=today + dt.timedelta(days=rnd.randint(-10, 40)) if i % 2 else None,
            deadline=today + dt.timedelta(days=rnd.randint(0, 60)) if i % 5 == 0 else None,
            done_date=today - dt.timedelta(days=i % 30) if status == "完了" else None,
            estimate_hours=float(rnd.choice([4, 8, 16, 24])) if i % 3 == 0 else None,
            progress=100 if status == "完了" else hist[-1].progress,
            history=hist if status != "未着手" else [], memo=""))
    open_ids = [t.id for t in tasks if t.status != "完了"]
    logs = []
    day = today + dt.timedelta(days=4 - today.weekday())  # 今週の金曜から過去へ
    n = 0
    while n < n_logs:
        if day.weekday() < 5:
            for s, e in SLOTS:
                if n >= n_logs:
                    break
                n += 1
                if n % 7 == 0:
                    w = Worklog(f"W-{n:06d}", day, s, e, kind=KIND_ONEOFF, title=rnd.choice(["会議", "朝会", "製造応援"]))
                else:
                    main = rnd.choice(open_ids)
                    subs = []
                    if n % 4 == 0:
                        sub = rnd.choice(open_ids)
                        if sub != main:
                            subs.append(SubItem(KIND_TASK, sub))
                    w = Worklog(f"W-{n:06d}", day, s, e, kind=KIND_TASK, task_id=main, subs=subs)
                logs.append(w)
        day -= dt.timedelta(days=1)
    storage.atomic_write_json(d / "profile.json", Profile(display).to_dict())
    storage.atomic_write_json(d / "tasks.json", {"version": SCHEMA_VERSION, "next_id": n_tasks + 1,
                                                 "tasks": [t.to_dict() for t in tasks]})
    storage.atomic_write_json(d / "worklogs.json", {"version": SCHEMA_VERSION, "next_id": n + 1,
                                                    "worklogs": [w.to_dict() for w in logs]})
    storage.atomic_write_json(d / "weekly_notes.json", {"version": SCHEMA_VERSION, "weekly_notes": []})


def make_ics(path: Path, n_events: int, today: dt.date) -> None:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Worklog Canvas perf//JA"]
    start = dt.datetime.combine(today - dt.timedelta(days=n_events // 8), dt.time(9, 0))
    for i in range(n_events):
        s = start + dt.timedelta(days=i // 8, minutes=60 * (i % 8))
        lines += ["BEGIN:VEVENT", f"UID:perf-{i}", f"SUMMARY:予定{i}",
                  f"DTSTART:{s:%Y%m%dT%H%M%S}", f"DTEND:{s + dt.timedelta(minutes=45):%Y%m%dT%H%M%S}"]
        if i % 100 == 0:
            lines.append("RRULE:FREQ=WEEKLY;COUNT=52")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--members", type=int, default=10)
    ap.add_argument("--tasks", type=int, default=500)
    ap.add_argument("--worklogs", type=int, default=5000)
    ap.add_argument("--ics-events", type=int, default=2000)
    a = ap.parse_args()
    root = Path(a.out)
    today = dt.date.today()
    rnd = random.Random(1)
    storage.atomic_write_json(root / "categories.json", {
        "version": SCHEMA_VERSION,
        "categories": [Category(c, CATEGORY_PALETTE[i]).to_dict() for i, c in enumerate(CATEGORIES)]})
    for m in range(a.members):
        make_user(root, f"user{m + 1:02d}", f"メンバー{m + 1:02d}", a.tasks, a.worklogs, today, rnd)
    make_ics(root / "perf_calendar.ics", a.ics_events, today)
    print(f"作成しました: {root}（{a.members}名 × タスク{a.tasks}件・作業バー{a.worklogs}件、予定{a.ics_events}件）")


if __name__ == "__main__":
    main()
