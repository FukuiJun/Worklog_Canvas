"""起動処理とメインウィンドウ。"""
from __future__ import annotations

import argparse
import datetime as _dt
import getpass
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import applog, backup, storage, team
from ..core.lock import HEARTBEAT_SECONDS, UserLock
from ..core.repository import DataFolder, UserRepository
from ..core.settings import Settings, app_dir
from .settings_dialog import SettingsDialog
from .state import AppState
from .summary_tab import SummaryTab
from .task_list_tab import TaskListTab
from .team_tab import TeamTab
from .timeline_view import TimelineTab

APP_TITLE = "Worklog Canvas"
RETRY_SAVE_MS = 30_000
UNSAVED_TEXT = "未保存"
log = applog.get()


class MainWindow(QMainWindow):
    def __init__(self, state: AppState, lock: UserLock | None = None):
        super().__init__()
        self.state = state
        self.lock = lock
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1280, 720)

        # 上部: 利用者の切り替え・更新・設定、閲覧モードの表示
        top = QHBoxLayout()
        top.addWidget(QLabel("表示する人"))
        self.user_combo = QComboBox()
        self.user_combo.setMinimumWidth(160)
        top.addWidget(self.user_combo)
        self.btn_refresh = QPushButton("更新")
        self.btn_refresh.setToolTip("共有フォルダから読み込み直す（他のメンバーの記録、カテゴリ）。自動では更新しません")
        top.addWidget(self.btn_refresh)
        self.banner = QLabel()
        self.banner.setStyleSheet("background:#FFF3C4; color:#5D4200; padding:4px 10px; border-radius:3px;"
                                  "font-weight:bold;")
        top.addSpacing(12)
        top.addWidget(self.banner)
        top.addStretch()
        self.btn_settings = QPushButton("設定…")
        top.addWidget(self.btn_settings)

        self.tabs = QTabWidget()
        self.timeline = TimelineTab(state)
        self.task_list = TaskListTab(state)
        self.summary = SummaryTab(state)
        self.team = TeamTab(state)
        self.tabs.addTab(self.timeline, "タイムライン")
        self.tabs.addTab(self.task_list, "タスク一覧")
        self.tabs.addTab(self.summary, "集計・週報")
        self.tabs.addTab(self.team, "チーム")
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(6, 6, 6, 0)
        cl.addLayout(top)
        cl.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        sb = self.statusBar()
        self.unsaved_label = QLabel(UNSAVED_TEXT)
        self.unsaved_label.setStyleSheet("color:#FFFFFF; background:#C62828; padding:1px 8px; font-weight:bold;")
        self.unsaved_label.setToolTip("共有フォルダに保存できませんでした。30秒ごとに再試行しています")
        self.unsaved_label.hide()
        sb.addWidget(self.unsaved_label)
        self.message = QLabel()
        sb.addWidget(self.message, 1)
        self.who = QLabel()
        self.who.setStyleSheet("color:#666;")
        sb.addPermanentWidget(self.who)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(lambda: self.message.setText(""))
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(RETRY_SAVE_MS)
        self._retry_timer.timeout.connect(self.retry_save)
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT_SECONDS * 1000)
        self._heartbeat.timeout.connect(self._beat)
        if lock is not None and lock.held:
            self._heartbeat.start()

        state.error.connect(lambda m: self.show_message(m, error=True))
        state.info.connect(lambda m: self.show_message(m, error=False))
        state.save_state_changed.connect(self._sync_unsaved)
        state.repo_switched.connect(self._sync_banner)
        self.user_combo.activated.connect(self._user_selected)
        self.btn_refresh.clicked.connect(self.refresh_from_disk)
        self.btn_settings.clicked.connect(self.open_settings)
        QShortcut(QKeySequence.Undo, self).activated.connect(self._undo)

        self.fill_users()
        self._sync_banner()
        self._sync_unsaved()

    # --- 表示 ---
    def show_message(self, text: str, error: bool) -> None:
        self.message.setStyleSheet("color:#C62828; font-weight:bold;" if error else "color:#2E7D32;")
        self.message.setText(text)
        self._clear_timer.start(8000)
        if error:
            log.info("操作を受け付けませんでした: %s", text)

    def _sync_banner(self) -> None:
        st = self.state
        if st.viewing_other:
            self.banner.setText(f"閲覧モード：{st.repo.profile.display_name}")
        elif st.locked_by:
            self.banner.setText(f"閲覧モード：{st.repo.profile.display_name}（{st.locked_by} で使用中のため編集できません）")
        else:
            self.banner.setText("")
        self.banner.setVisible(bool(self.banner.text()))
        idx = self.user_combo.findData(st.repo.username)
        if idx >= 0 and idx != self.user_combo.currentIndex():
            self.user_combo.blockSignals(True)
            self.user_combo.setCurrentIndex(idx)
            self.user_combo.blockSignals(False)
        own = st.own_repo
        self.who.setText(f"{own.profile.display_name}（{own.username}）　データフォルダ: {st.folder.root}")
        self.btn_settings.setEnabled(not st.viewing_other)

    def _sync_unsaved(self) -> None:
        unsaved = self.state.unsaved
        self.unsaved_label.setVisible(unsaved)
        if unsaved and not self._retry_timer.isActive():
            err = self.state.own_repo.last_save_error
            log.error("保存に失敗しました: %s", err)
            self._retry_timer.start()
        elif not unsaved and self._retry_timer.isActive():
            self._retry_timer.stop()
            log.info("未保存だった変更を保存しました")
            self.show_message("未保存だった変更を保存しました", error=False)

    def retry_save(self) -> bool:
        return self.state.own_repo.retry_pending()

    def _beat(self) -> None:
        try:
            self.lock.heartbeat()
        except OSError as e:
            log.warning("使用中の印を更新できませんでした: %s", e)

    # --- 利用者の切り替え（F-08） ---
    def fill_users(self) -> None:
        own = self.state.own_repo
        current = self.state.repo.username
        self.user_combo.blockSignals(True)
        self.user_combo.clear()
        self.user_combo.addItem(f"{own.profile.display_name}（自分）", own.username)
        try:
            names = team.member_names(self.state.folder)
        except OSError:
            names = {}
        for u, display in sorted(names.items(), key=lambda x: (x[1], x[0])):
            if u != own.username:
                self.user_combo.addItem(display, u)
                self.user_combo.setItemData(self.user_combo.count() - 1, u, Qt.ToolTipRole)
        self.user_combo.setCurrentIndex(max(0, self.user_combo.findData(current)))
        self.user_combo.blockSignals(False)

    def _user_selected(self, index: int) -> None:
        self.view_user(self.user_combo.itemData(index))

    def view_user(self, username: str) -> bool:
        st = self.state
        if username == st.repo.username:
            return True
        self.summary.report.save_note()  # 自分の入力途中のメモを保存してから切り替える
        if username == st.own_repo.username:
            st.switch_to(st.own_repo)
            return True
        try:
            repo = st.folder.user(username, readonly=True)
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.error("メンバーのデータを読み込めませんでした: %s: %s", username, e)
            QMessageBox.warning(self, APP_TITLE, f"{username} のデータを{team.LOAD_ERROR_MESSAGE}。\n{e}")
            self.user_combo.setCurrentIndex(max(0, self.user_combo.findData(st.repo.username)))
            return False
        st.switch_to(repo)
        return True

    def refresh_from_disk(self) -> None:
        """「更新」: 他のメンバーのデータとカテゴリを読み込み直す（自分のデータは画面の内容が正）。"""
        st = self.state
        st.reload_categories()
        self.fill_users()
        if st.viewing_other:
            try:
                st.switch_to(st.folder.user(st.repo.username, readonly=True))
            except (OSError, ValueError, KeyError, TypeError) as e:
                QMessageBox.warning(self, APP_TITLE, f"{team.LOAD_ERROR_MESSAGE}。\n{e}")
                st.switch_to(st.own_repo)
                self.fill_users()
        if self.team._loaded:
            self.team.reload()
        self.show_message("読み込み直しました", error=False)

    def open_settings(self) -> None:
        if SettingsDialog(self.state, self).exec():
            self.fill_users()
            self._sync_banner()
            self.state.tasks_changed.emit()

    def _undo(self) -> None:
        if self.tabs.currentWidget() is self.timeline:
            self.timeline.undo()

    # --- 終了 ---
    def closeEvent(self, ev):
        self.summary.report.save_note()
        if self.state.unsaved and not self.retry_save():
            ans = QMessageBox.warning(
                self, APP_TITLE,
                "共有フォルダに保存できていない変更があります。\n"
                "このまま終了すると、その変更は失われます。終了しますか？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                ev.ignore()
                return
            log.warning("未保存の変更を残したまま終了しました: %s", sorted(self.state.own_repo.pending))
        if self.lock is not None:
            self.lock.release()
        self._heartbeat.stop()
        self._retry_timer.stop()
        log.info("終了")
        super().closeEvent(ev)


# ===========================================================================
def _apply_font(app: QApplication) -> None:
    families = set(QFontDatabase.families())
    for name in ("Yu Gothic UI", "Meiryo UI", "Meiryo", "Noto Sans CJK JP", "WenQuanYi Zen Hei"):
        if name in families:
            app.setFont(QFont(name, 9))
            return


def choose_data_folder(parent=None, first: bool = True) -> str | None:
    if first:
        QMessageBox.information(parent, APP_TITLE, "データを保存するフォルダ（共有フォルダ）を選んでください。")
    path = QFileDialog.getExistingDirectory(parent, "データフォルダを選ぶ")
    return path or None


def check_folder(path: str) -> str | None:
    """データフォルダに接続できるか。できなければ理由を返す。"""
    p = Path(path)
    try:
        if not p.is_dir():
            return "フォルダが見つかりません"
        (p / "users").mkdir(exist_ok=True)
        list((p / "users").iterdir())
    except OSError as e:
        return str(e)
    return None


def connect_folder(settings: Settings, initial: str) -> str | None:
    """共有フォルダへ接続する。できなければ「再試行」「別のフォルダを選ぶ」「終了」を選ばせる（9章）。"""
    path = initial
    while True:
        reason = check_folder(path)
        if reason is None:
            return path
        log.error("データフォルダに接続できません: %s: %s", path, reason)
        box = QMessageBox(QMessageBox.Warning, APP_TITLE,
                          f"データフォルダに接続できません。\n{path}\n\n{reason}\n\n"
                          "ネットワークの接続を確認してください。")
        retry = box.addButton("再試行", QMessageBox.AcceptRole)
        other = box.addButton("別のフォルダを選ぶ", QMessageBox.ActionRole)
        box.addButton("終了", QMessageBox.RejectRole)
        box.setDefaultButton(retry)
        box.exec()
        clicked = box.clickedButton()
        if clicked is retry:
            continue
        if clicked is other:
            chosen = choose_data_folder(first=False)
            if chosen:
                path = chosen
                settings.data_folder = chosen
                try:
                    settings.save()
                except OSError:
                    pass
            continue
        return None


def load_own(folder: DataFolder, username: str, readonly: bool, ask=None) -> UserRepository | None:
    """自分のデータを読み込む。壊れたJSONは <名前>.broken_<日時> に改名し、最新のバックアップから復元するか確認する（9章）。

    ask(file_name, backup_date) -> bool は確認の関数（テスト用に差し替え可能）。
    """
    ask = ask or _ask_restore
    for _ in range(10):  # 壊れたファイルが複数あっても順に処理する
        try:
            repo = folder.user(username, readonly=readonly)
            folder.load_categories()  # 共有の categories.json も確かめる
            return repo
        except storage.JsonFormatError as e:
            path = e.path
            log.error("JSONが壊れていて読めません: %s", path)
            if readonly:
                QMessageBox.critical(None, APP_TITLE, f"データを読み込めませんでした。\n{path}")
                return None
            moved = backup.quarantine(path, _dt.datetime.now())
            found = backup.backup_file_for(path, folder, username)
            if found and ask(path.name, found[0], moved.name):
                backup.restore(found[1], path)
                log.info("バックアップ（%s）から復元しました: %s", found[0], path.name)
            elif not found:
                QMessageBox.warning(None, APP_TITLE,
                                    f"{path.name} が壊れていて読めませんでした。\n"
                                    f"壊れたファイルは {moved.name} に名前を変えて残しました。\n"
                                    "バックアップがないため、空の状態から始めます。")
    return None


def _ask_restore(name: str, date: _dt.date, moved: str) -> bool:
    ans = QMessageBox.question(
        None, APP_TITLE,
        f"{name} が壊れていて読めませんでした。\n壊れたファイルは {moved} に名前を変えて残しました。\n\n"
        f"最新のバックアップ（{date:%Y/%m/%d}）から復元しますか？\n"
        "「いいえ」を選ぶと、このファイルは空の状態から始めます。")
    return ans == QMessageBox.Yes


def _excepthook(exc_type, exc, tb) -> None:
    log.error("予期しないエラー:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
    try:
        QMessageBox.critical(None, APP_TITLE, f"予期しないエラーが起きました。\n{exc}\n\n詳しくは app.log を見てください。")
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="WorklogCanvas")
    parser.add_argument("--data", help="データフォルダ（設定より優先。開発・確認用）")
    parser.add_argument("--user", help="ユーザー名（既定はWindowsのユーザー名。開発・確認用）")
    parser.add_argument("--self-test", action="store_true",
                        help="exe の動作確認: 部品の読み込みと画面の作成を一時フォルダで試して終了する")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    if args.self_test:
        from .. import selftest
        return selftest.run()

    applog.setup(app_dir())
    log.info("起動（バージョン %s）", __version__)
    sys.excepthook = _excepthook
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_TITLE)
    _apply_font(app)

    settings = Settings.load()
    data = args.data or settings.data_folder
    if not data:
        data = choose_data_folder()
        if not data:
            log.info("終了（データフォルダ未選択）")
            return 0
        settings.data_folder = data
        try:
            settings.save()
        except OSError:
            pass
    data = connect_folder(settings, str(Path(data)))
    if data is None:
        log.info("終了（データフォルダに接続できない）")
        return 0
    folder = DataFolder(data)
    username = args.user or getpass.getuser()

    # 同じ利用者が別のPCで使用中なら閲覧モード（9章）
    user_dir = folder.users_dir / username
    user_dir.mkdir(parents=True, exist_ok=True)
    lock = UserLock(user_dir)
    try:
        result = lock.acquire()
    except OSError as e:
        log.error("使用中の確認ができませんでした: %s", e)
        result = None
    locked_by = None
    if result is not None and not result.acquired:
        locked_by = result.other.host
        log.warning("同じ利用者が別のPCで使用中のため閲覧モードで起動: %s", locked_by)
        QMessageBox.warning(None, APP_TITLE,
                            f"このユーザー（{username}）は、別のPC（{locked_by}）で使用中です。\n"
                            "データが食い違わないように、閲覧モードで起動します（編集はできません）。")

    repo = load_own(folder, username, readonly=locked_by is not None)
    if repo is None:
        lock.release()
        return 1
    if not repo.readonly:
        if not repo.path("profile.json").exists():
            repo.save_profile()  # 他のメンバーの一覧に出るように
        try:
            made = backup.make_daily_backup(folder, username, _dt.date.today())
            if made:
                log.info("バックアップを作成しました: %s", made.name)
        except OSError as e:
            log.error("バックアップを作成できませんでした: %s", e)
    state = AppState(folder, repo, settings)
    state.locked_by = locked_by
    win = MainWindow(state, lock)
    win.show()
    log.info("起動完了（%s、データフォルダ: %s）", username, data)
    code = app.exec()
    lock.release()
    return code
