"""性能の計測（仕様8章、AC-22）。scripts/make_perf_data.py で作ったデータで、画面を実際に動かして時間を測る。

    python scripts/make_perf_data.py %TEMP%\\wc_perf
    python scripts/measure_perf.py %TEMP%\\wc_perf

基準: 起動から操作可能まで5秒以内、週の切り替え1秒以内、チーム一覧10名分5秒以内、予定2000件のICSを3秒以内。
画面の描画まで含めて測る（各操作のあと、ウィンドウ全体を描き直す）。
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    data = Path(sys.argv[1])
    user = sys.argv[2] if len(sys.argv) > 2 else "user01"
    os.environ.setdefault("WORKLOG_CANVAS_HOME", tempfile.mkdtemp(prefix="wc_perf_home_"))
    t_proc = time.perf_counter()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from worklog_canvas.core import backup
    from worklog_canvas.core.repository import DataFolder
    from worklog_canvas.core.settings import Settings
    from worklog_canvas.ui.app import MainWindow, _apply_font
    from worklog_canvas.ui.state import AppState
    _apply_font(app)

    def settle(win):
        app.processEvents()
        win.grab()  # 描画を最後まで行わせる
        app.processEvents()

    results = []

    def check(name, seconds, limit):
        ok = seconds <= limit
        results.append(ok)
        print(f"{'OK ' if ok else 'NG '} {name}: {seconds:.2f} 秒（基準 {limit} 秒以内）")

    # 1. 起動から操作可能まで（読み込み、バックアップ、画面の作成と最初の描画）
    t0 = time.perf_counter()
    folder = DataFolder(data)
    repo = folder.user(user)
    backup.make_daily_backup(folder, user, dt.date.today())
    state = AppState(folder, repo, Settings())
    win = MainWindow(state)
    win.resize(1280, 800)
    win.show()
    win.timeline.go_today()
    settle(win)
    check(f"起動から操作可能まで（タスク{len(repo.tasks)}件・作業バー{len(repo.worklogs)}件）",
          time.perf_counter() - t0, 5)
    print(f"    参考: Python と画面部品の読み込みを含めると {time.perf_counter() - t_proc:.2f} 秒")

    # 2. 週の切り替え（タイムライン）
    worst = 0.0
    for direction in (-1, -1, -1, 1, 1, 1):
        t0 = time.perf_counter()
        win.timeline.step(direction)
        settle(win)
        worst = max(worst, time.perf_counter() - t0)
    check("週の切り替え（タイムライン、6回の最大）", worst, 1)

    # 週の切り替え（集計・週報）
    win.tabs.setCurrentWidget(win.summary)
    settle(win)
    worst = 0.0
    for page, step in ((win.summary.summary, lambda d: win.summary.summary.step(d)),
                       (win.summary.report, lambda d: win.summary.report.set_week(
                           win.summary.report.week + dt.timedelta(days=7 * d)))):
        win.summary.setCurrentWidget(page)
        settle(win)
        for d in (-1, 1):
            t0 = time.perf_counter()
            step(d)
            settle(win)
            worst = max(worst, time.perf_counter() - t0)
    check("週の切り替え（集計・週報、最大）", worst, 1)

    # 参考: タスク一覧の表示と、進捗率の変更後の作り直し
    t0 = time.perf_counter()
    win.tabs.setCurrentWidget(win.task_list)
    settle(win)
    print(f"    参考: タスク一覧の表示 {time.perf_counter() - t0:.2f} 秒")
    t0 = time.perf_counter()
    state.tasks_changed.emit()
    settle(win)
    print(f"    参考: タスク一覧の作り直し（進捗率の変更後など） {time.perf_counter() - t0:.2f} 秒")

    # 3. チーム一覧（全員分を読み込み、1人1列で表示）
    win.tabs.setCurrentWidget(win.team)
    t0 = time.perf_counter()
    win.team.reload()
    settle(win)
    check(f"チーム一覧（{len(win.team.members)}名分）", time.perf_counter() - t0, 5)

    # 4. 予定表ファイル
    ics_path = data / "perf_calendar.ics"
    if ics_path.exists():
        win.tabs.setCurrentWidget(win.timeline)
        settle(win)
        t0 = time.perf_counter()
        win.timeline.load_ics(str(ics_path))
        settle(win)
        check("予定表ファイル（予定2000件）の読み込みと表示", time.perf_counter() - t0, 3)
        worst = 0.0
        for direction in (-1, 1):
            t0 = time.perf_counter()
            win.timeline.step(direction)
            settle(win)
            worst = max(worst, time.perf_counter() - t0)
        check("予定表ファイルを読み込んだ状態での週の切り替え", worst, 1)

    win.close()
    print("すべて基準内です" if all(results) else "基準を超えた項目があります")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
