"""タスクの追加・編集ダイアログ（F-01）と、カテゴリの追加ダイアログ。"""
from __future__ import annotations

import copy
from dataclasses import replace

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..core.models import (
    PRIORITIES, STATUS_DONE, STATUSES, TASK_NAME_MAX, Category, Task, ValidationError,
)
from .state import AppState
from .widgets import OptionalDateEdit, ProgressSpin, color_icon, error_label, show_error
from .worklog_dialog import confirm_done

NEW_CATEGORY_COLORS = ["#4E79A7", "#F28E2B", "#59A14F", "#B07AA1", "#76B7B2", "#EDC948",
                       "#E15759", "#FF9DA7", "#3E8E9E", "#6B6ECF"]


class CategoryDialog(QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.setWindowTitle("カテゴリの追加")
        self.state = state
        used = set(state.category_colors.values())
        self.color = next((c for c in NEW_CATEGORY_COLORS if c not in used), NEW_CATEGORY_COLORS[0])
        self.name = QLineEdit()
        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._pick)
        self._show_color()
        self.err = error_label()
        form = QFormLayout()
        form.addRow("カテゴリ名", self.name)
        form.addRow("色", self.color_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.err)
        lay.addWidget(buttons)

    def _show_color(self) -> None:
        self.color_btn.setIcon(color_icon(self.color, 16))
        self.color_btn.setText(self.color)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self, "色を選ぶ")
        if c.isValid():
            self.color = c.name().upper()
            self._show_color()

    def _save(self) -> None:
        cat = Category(self.name.text().strip(), self.color)
        try:
            added = self.state.folder.add_category(cat)
        except ValidationError as e:
            show_error(self.err, str(e))
            return
        except OSError as e:
            show_error(self.err, f"保存できませんでした: {e}")
            return
        if not added:
            show_error(self.err, None)  # 既にある → そのカテゴリを選ぶだけ
        self.created_name = cat.name
        self.state.reload_categories()
        self.accept()


class TaskDialog(QDialog):
    """task が None なら新規。duplicate_of を渡すと複製として新規作成。"""

    def __init__(self, state: AppState, task: Task | None = None, parent=None, initial: Task | None = None):
        super().__init__(parent)
        self.state = state
        self.original = task
        base = task or initial or Task(id="", name="")
        self.setWindowTitle("タスクの編集" if task else "タスクの追加")

        self.name = QLineEdit(base.name)
        self.name.setMaxLength(TASK_NAME_MAX)
        self.name_err = error_label()
        name_box = QWidget()
        nl = QVBoxLayout(name_box)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.addWidget(self.name)
        nl.addWidget(self.name_err)

        self.category = QComboBox()
        cat_box = QWidget()
        cl = QHBoxLayout(cat_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.category, 1)
        btn_cat = QPushButton("新しいカテゴリ…")
        btn_cat.clicked.connect(self._new_category)
        cl.addWidget(btn_cat)
        self._fill_categories(base.category)

        self.status = QComboBox()
        self.status.addItems(STATUSES)
        self.status.setCurrentText(base.status)
        self.priority = QComboBox()
        self.priority.addItems(PRIORITIES)
        self.priority.setCurrentText(base.priority)
        self.start_date, self.planned_end, self.deadline, self.done_date = (OptionalDateEdit() for _ in range(4))
        self.start_date.set_date(base.start_date)
        self.planned_end.set_date(base.planned_end)
        self.deadline.set_date(base.deadline)
        self.done_date.set_date(base.done_date)
        self.estimate = QDoubleSpinBox()
        self.estimate.setRange(0, 9999)
        self.estimate.setSingleStep(0.25)
        self.estimate.setDecimals(2)
        self.estimate.setSuffix(" 時間")
        self.estimate.setSpecialValueText("—")
        self.estimate.setValue(base.estimate_hours or 0)
        self.estimate.editingFinished.connect(
            lambda: self.estimate.setValue(round(self.estimate.value() * 4) / 4))
        self.progress = ProgressSpin()
        self.progress.setValue(base.progress)
        self.memo = QPlainTextEdit(base.memo)
        self.memo.setFixedHeight(80)

        form = QFormLayout()
        form.addRow("タスク名 *", name_box)
        form.addRow("カテゴリ", cat_box)
        form.addRow("ステータス", self.status)
        form.addRow("優先度", self.priority)
        form.addRow("開始日", self.start_date)
        form.addRow("完了予定日", self.planned_end)
        form.addRow("期限", self.deadline)
        form.addRow("完了日", self.done_date)
        form.addRow("予定工数", self.estimate)
        form.addRow("進捗率", self.progress)
        form.addRow("メモ", self.memo)
        self.err = error_label()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.err)
        lay.addWidget(buttons)
        self.status.currentTextChanged.connect(self._status_changed)
        self.setMinimumWidth(520)
        self.saved: Task | None = None

    def _fill_categories(self, select: str) -> None:
        self.category.clear()
        self.category.addItem("（なし）", "")
        for name, color in self.state.category_colors.items():
            self.category.addItem(color_icon(color), name, name)
        if select and self.category.findData(select) < 0:  # categories.json にないカテゴリ
            self.category.addItem(select, select)
        self.category.setCurrentIndex(max(0, self.category.findData(select)))

    def _new_category(self) -> None:
        dlg = CategoryDialog(self.state, self)
        if dlg.exec():
            self._fill_categories(dlg.created_name)

    def _status_changed(self, status: str) -> None:
        """完了にしたら完了日に今日を自動入力、完了以外に戻したら空にする。"""
        if status == STATUS_DONE and self.done_date.date() is None:
            self.done_date.set_date(self.state.today())
        elif status != STATUS_DONE:
            self.done_date.set_date(None)

    def build(self) -> Task:
        base = copy.deepcopy(self.original) if self.original else Task(id="", name="")
        est = self.estimate.value()
        return replace(
            base,
            name=self.name.text().strip(),
            category=self.category.currentData() or "",
            status=self.status.currentText(),
            priority=self.priority.currentText(),
            start_date=self.start_date.date(),
            planned_end=self.planned_end.date(),
            deadline=self.deadline.date(),
            done_date=self.done_date.date(),
            estimate_hours=round(est * 4) / 4 if est > 0 else None,
            memo=self.memo.toPlainText(),
        )

    def _save(self) -> None:
        show_error(self.name_err, None)
        show_error(self.err, None)
        task = self.build()
        new_progress = self.progress.value5()
        today = self.state.today()
        try:
            if self.original is None:
                task.validate()
                task = self.state.repo.add_task(task)
            else:
                self.state.repo.update_task(task)
            if new_progress != task.progress:
                self.state.repo.set_progress(task.id, new_progress, today)
        except ValidationError as e:
            show_error(self.name_err if e.field == "タスク名" else self.err, str(e))
            return
        except OSError as e:
            show_error(self.err, f"保存できませんでした: {e}")
            return
        confirm_done(self, self.state, task.id)
        self.saved = self.state.repo.get_task(task.id)
        self.state.tasks_changed.emit()
        self.accept()
