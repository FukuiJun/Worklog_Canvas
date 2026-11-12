"""起動処理とメインウィンドウ。"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QTabWidget, QWidget, QVBoxLayout,
)

from ..core import storage
from ..core.repository import DataFolder
from ..core.settings import Settings
from .state import AppState
from .task_list_tab import TaskListTab
from .timeline_view import TimelineTab

APP_TITLE = "Worklog Canvas"


def _placeholder(text: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet("color:#777; font-size: 14px;")
    lay.addWidget(lab)
    return w


class MainWindow(QMainWindow):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1280, 720)
        self.tabs = QTabWidget()
        self.timeline = TimelineTab(state)
        self.task_list = TaskListTab(state)
        self.tabs.addTab(self.timeline, "タイムライン")
        self.tabs.addTab(self.task_list, "タスク一覧")
        self.tabs.addTab(_placeholder("集計・週報は次のバージョン（M3・M4）で追加します"), "集計・週報")
        self.tabs.addTab(_placeholder("チーム一覧は次のバージョン（M5）で追加します"), "チーム")
        self.setCentralWidget(self.tabs)

        sb = self.statusBar()
        self.message = QLabel()
        sb.addWidget(self.message, 1)
        who = QLabel(f"{state.repo.profile.display_name}（{state.repo.username}）　データフォルダ: {state.folder.root}")
        who.setStyleSheet("color:#666;")
        sb.addPermanentWidget(who)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(lambda: self.message.setText(""))
        state.error.connect(lambda m: self.show_message(m, error=True))
        state.info.connect(lambda m: self.show_message(m, error=False))

        undo = QShortcut(QKeySequence.Undo, self)
        undo.activated.connect(self._undo)

    def show_message(self, text: str, error: bool) -> None:
        self.message.setStyleSheet("color:#C62828; font-weight:bold;" if error else "color:#2E7D32;")
        self.message.setText(text)
        self._clear_timer.start(8000)

    def _undo(self) -> None:
        if self.tabs.currentWidget() is self.timeline:
            self.timeline.undo()


def _apply_font(app: QApplication) -> None:
    families = set(QFontDatabase.families())
    for name in ("Yu Gothic UI", "Meiryo UI", "Meiryo", "Noto Sans CJK JP", "WenQuanYi Zen Hei"):
        if name in families:
            app.setFont(QFont(name, 9))
            return


def choose_data_folder(parent=None) -> str | None:
    QMessageBox.information(parent, APP_TITLE, "データを保存するフォルダ（共有フォルダ）を選んでください。")
    path = QFileDialog.getExistingDirectory(parent, "データフォルダを選ぶ")
    return path or None


def build_state(data_folder: str, username: str, settings: Settings) -> AppState:
    folder = DataFolder(data_folder)
    repo = folder.user(username)
    if not repo.path("profile.json").exists():
        repo.save_profile()  # 他のメンバーの一覧に出るように
    return AppState(folder, repo, settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="WorklogCanvas")
    parser.add_argument("--data", help="データフォルダ（設定より優先。開発・確認用）")
    parser.add_argument("--user", help="ユーザー名（既定はWindowsのユーザー名。開発・確認用）")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_TITLE)
    _apply_font(app)

    settings = Settings.load()
    data = args.data or settings.data_folder
    if not data:
        data = choose_data_folder()
        if not data:
            return 0
        settings.data_folder = data
        settings.save()
    username = args.user or getpass.getuser()
    try:
        state = build_state(str(Path(data)), username, settings)
    except storage.JsonFormatError as e:
        QMessageBox.critical(None, APP_TITLE, f"データを読み込めませんでした。\n{e}")
        return 1
    except OSError as e:
        QMessageBox.critical(None, APP_TITLE, f"データフォルダに接続できませんでした。\n{e}")
        return 1
    win = MainWindow(state)
    win.show()
    return app.exec()
