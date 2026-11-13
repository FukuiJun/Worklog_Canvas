"""設定画面: 表示名、データフォルダ、タイムラインの表示時間帯（Q-05）、カテゴリの変更・削除（仕様 5.2）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import timeutil as tu
from ..core.models import ValidationError
from ..core.repository import CategoryInUseError
from .state import AppState
from .task_dialog import CategoryDialog
from .widgets import color_icon, error_label, show_error


class SettingsDialog(QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.state = state
        own = state.own_repo
        editable = not own.readonly

        form = QFormLayout()
        self.display_name = QLineEdit(own.profile.display_name)
        self.display_name.setMaxLength(20)
        self.display_name.setEnabled(editable)
        form.addRow("表示名", self.display_name)
        form.addRow("ユーザー名", QLabel(f"{own.username}（Windowsのユーザー名）"))
        form.addRow("バージョン", QLabel(__version__))

        folder_box = QWidget()
        fl = QHBoxLayout(folder_box)
        fl.setContentsMargins(0, 0, 0, 0)
        self.folder_label = QLabel(str(state.folder.root))
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.folder_label.setWordWrap(True)
        btn_folder = QPushButton("変更…")
        btn_folder.clicked.connect(self._change_folder)
        fl.addWidget(self.folder_label, 1)
        fl.addWidget(btn_folder)
        form.addRow("データフォルダ", folder_box)

        range_box = QWidget()
        rl = QHBoxLayout(range_box)
        rl.setContentsMargins(0, 0, 0, 0)
        self.start_hour, self.end_hour = QComboBox(), QComboBox()
        for h in range(0, 24):
            self.start_hour.addItem(f"{h}:00", h * 60)
        for h in range(1, 25):
            self.end_hour.addItem(f"{h}:00", h * 60)
        s, e = state.settings.view_range
        self.start_hour.setCurrentIndex(self.start_hour.findData(s))
        self.end_hour.setCurrentIndex(self.end_hour.findData(e))
        rl.addWidget(self.start_hour)
        rl.addWidget(QLabel("〜"))
        rl.addWidget(self.end_hour)
        rl.addStretch()
        form.addRow("タイムラインの表示時間帯", range_box)

        cat_group = QGroupBox("カテゴリ（全員共通）")
        cl = QVBoxLayout(cat_group)
        self.cat_list = QListWidget()
        self.cat_list.setFixedHeight(150)
        cl.addWidget(self.cat_list)
        row = QHBoxLayout()
        self.btn_cat_add = QPushButton("追加…")
        self.btn_cat_rename = QPushButton("名前を変更…")
        self.btn_cat_delete = QPushButton("削除")
        for b in (self.btn_cat_add, self.btn_cat_rename, self.btn_cat_delete):
            b.setEnabled(editable)
            row.addWidget(b)
        row.addStretch()
        cl.addLayout(row)
        hint = QLabel("名前の変更と削除は、そのカテゴリを使うタスクが自分のデータに0件のときだけできます。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        cl.addWidget(hint)
        self.cat_err = error_label()
        cl.addWidget(self.cat_err)
        self.btn_cat_add.clicked.connect(self._add_category)
        self.btn_cat_rename.clicked.connect(self._rename_category)
        self.btn_cat_delete.clicked.connect(self._delete_category)

        self.err = error_label()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(cat_group)
        lay.addWidget(self.err)
        lay.addWidget(buttons)
        self.setMinimumWidth(560)
        self._fill_categories()

    # --- カテゴリ ---
    def _fill_categories(self) -> None:
        self.state.reload_categories()
        self.cat_list.clear()
        counts = {}
        for t in self.state.own_repo.tasks:
            counts[t.category] = counts.get(t.category, 0) + 1
        for name, color in self.state.category_colors.items():
            n = counts.get(name, 0)
            item = QListWidgetItem(color_icon(color), f"{name}　（自分のタスク {n} 件）")
            item.setData(Qt.UserRole, name)
            self.cat_list.addItem(item)

    def _selected_category(self) -> str | None:
        item = self.cat_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _add_category(self) -> None:
        if CategoryDialog(self.state, self).exec():
            self._fill_categories()

    def _rename_category(self) -> None:
        name = self._selected_category()
        if not name:
            return
        new, ok = QInputDialog.getText(self, "カテゴリ名の変更", "新しいカテゴリ名", text=name)
        if not ok or new.strip() == name:
            return
        try:
            self.state.folder.rename_category(name, new.strip(), self.state.own_repo.tasks)
        except (CategoryInUseError, ValidationError, KeyError, OSError) as e:
            show_error(self.cat_err, str(e) if not isinstance(e, KeyError) else "カテゴリが見つかりません")
            return
        show_error(self.cat_err, None)
        self._fill_categories()

    def _delete_category(self) -> None:
        name = self._selected_category()
        if not name:
            return
        if QMessageBox.question(self, "カテゴリの削除",
                                f"カテゴリ「{name}」を削除しますか？\n（他のメンバーのタスクで使われている場合、"
                                "その人の画面では「（未分類）」の色で表示されます）") != QMessageBox.Yes:
            return
        try:
            self.state.folder.delete_category(name, self.state.own_repo.tasks)
        except (CategoryInUseError, KeyError, OSError) as e:
            show_error(self.cat_err, str(e) if not isinstance(e, KeyError) else "カテゴリが見つかりません")
            return
        show_error(self.cat_err, None)
        self._fill_categories()

    # --- データフォルダ ---
    def _change_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "データフォルダを選ぶ", str(self.state.folder.root))
        if not path or path == str(self.state.folder.root):
            return
        self.state.settings.data_folder = path
        try:
            self.state.settings.save()
        except OSError as e:
            show_error(self.err, f"設定を保存できませんでした: {e}")
            return
        self.folder_label.setText(f"{path}\n（次回の起動から使います。今のデータはコピーされません）")

    # --- 保存 ---
    def _save(self) -> None:
        start, end = self.start_hour.currentData(), self.end_hour.currentData()
        if end <= start:
            show_error(self.err, "表示時間帯は、終わりを始まりより後にしてください")
            return
        own = self.state.own_repo
        name = self.display_name.text().strip()
        if not own.readonly and name != own.profile.display_name:
            try:
                own.set_display_name(name)
            except ValidationError as e:
                show_error(self.err, str(e))
                return
        st = self.state.settings
        st.view_start, st.view_end = tu.format_hhmm(start), tu.format_hhmm(end)
        try:
            st.save()
        except OSError:
            pass
        self.state.settings_changed.emit()
        self.accept()
