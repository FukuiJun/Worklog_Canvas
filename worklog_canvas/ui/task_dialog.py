"""タスクの追加・編集ダイアログ（F-01）と、カテゴリの追加ダイアログ。"""
from __future__ import annotations

import copy
from dataclasses import replace

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..core.colors import next_category_color
from ..core.models import (
    KIND_TASK, PRIORITIES, STATUS_DONE, STATUSES, TASK_NAME_MAX, TASK_TYPES, TYPE_DAILY, TYPE_RECURRING,
    TYPE_WORK, Category, Task, ValidationError,
)
from .state import AppState
from .widgets import OptionalDateEdit, ProgressSpin, color_icon, error_label, show_error
from .worklog_dialog import confirm_done


class CategoryDialog(QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.setWindowTitle("カテゴリの追加")
        self.state = state
        self.color = next_category_color(set(state.category_colors.values()))
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

    TYPE_LABELS = {TYPE_WORK: "業務タスク", TYPE_DAILY: "日常タスク", TYPE_RECURRING: "定期タスク"}

    def __init__(self, state: AppState, task: Task | None = None, parent=None, initial: Task | None = None,
                 task_type: str | None = None):
        super().__init__(parent)
        self.state = state
        self.original = task
        base = copy.deepcopy(task or initial or Task(id="", name=""))
        if task is None and task_type:
            base.task_type = task_type
        if task is None and not base.is_work and base.status == "未着手":
            base.status = "進行中"  # 日常・定期タスクは使い始めの状態で作る
        label = self.TYPE_LABELS.get(base.task_type, "タスク")
        self.setWindowTitle(f"{label}の編集" if task else f"{label}の追加")

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
        self.start_date, self.planned_end, self.deadline, self.done_date = (
            OptionalDateEdit(today=state.today) for _ in range(4))
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
        self.task_type = QComboBox()
        for t in TASK_TYPES:
            self.task_type.addItem(self.TYPE_LABELS[t], t)
        self.task_type.setCurrentIndex(self.task_type.findData(base.task_type))
        self.type_hint = QLabel()
        self.type_hint.setWordWrap(True)
        self.type_hint.setStyleSheet("color: #5B6B7B;")
        type_box = QWidget()
        tl_ = QVBoxLayout(type_box)
        tl_.setContentsMargins(0, 0, 0, 0)
        tl_.addWidget(self.task_type)
        tl_.addWidget(self.type_hint)
        # 定期タスクの繰り返しの時間帯（タスクをメインにした定期の時間帯。1つ目を編集する）
        from .recurring_dialog import RecurrenceFields, default_recurrence
        linked = state.repo.recurring_of(task.id) if task else []
        self._recurrence_base = copy.deepcopy(linked[0]) if linked else default_recurrence(state)
        self.recurrence = RecurrenceFields(state, self._recurrence_base)
        self.recurrence_box = QGroupBox("繰り返しの時間帯（タイムラインに「定期の予定」として出ます）")
        rl = QVBoxLayout(self.recurrence_box)
        rl.addWidget(self.recurrence)

        form = QFormLayout()
        self.form = form
        form.addRow("種類", type_box)
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
        lay.addWidget(self.recurrence_box)
        lay.addWidget(self.err)
        lay.addWidget(buttons)
        self.status.currentTextChanged.connect(self._status_changed)
        self.task_type.currentIndexChanged.connect(self._type_changed)
        self.setMinimumWidth(540)
        self.saved: Task | None = None
        self._type_changed()

    def current_type(self) -> str:
        return self.task_type.currentData()

    def _type_changed(self) -> None:
        """種類に合わせて入力欄を出し分ける。日常・定期タスクは進捗率・日付・予定工数を持たない。"""
        kind = self.current_type()
        is_work = kind == TYPE_WORK
        for w in (self.planned_end, self.deadline, self.estimate, self.progress):
            self.form.setRowVisible(w, is_work)
        self.recurrence_box.setVisible(kind == TYPE_RECURRING)
        self.type_hint.setText({
            TYPE_WORK: "進捗率・完了予定日・期限を管理し、完了させるタスク",
            TYPE_DAILY: "メール対応・雑務など終わりのない日々の作業（進捗率・期限なし）",
            TYPE_RECURRING: "朝会など決まった時間に繰り返す作業（進捗率・期限なし）",
        }[kind])
        self.adjustSize()

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
            task_type=self.current_type(),
        )

    def _save(self) -> None:
        show_error(self.name_err, None)
        show_error(self.err, None)
        task = self.build()
        if not task.is_work:
            task.clear_work_fields()
        new_progress = self.progress.value5() if task.is_work else task.progress
        today = self.state.today()
        recurrence = None
        if task.task_type == TYPE_RECURRING:
            recurrence = self.recurrence.apply(self._recurrence_base)
            recurrence.kind, recurrence.title = KIND_TASK, ""
            try:  # タスクを保存する前に、繰り返しの入力を確かめる
                recurrence.task_id = "（確認用）"
                recurrence.validate()
            except ValidationError as e:
                show_error(self.err, str(e))
                return
        try:
            if self.original is None:
                task.validate()
                task = self.state.repo.add_task(task)
            else:
                self.state.repo.update_task(task)
            if new_progress != task.progress:
                self.state.repo.set_progress(task.id, new_progress, today)
            repo = self.state.repo
            if recurrence is not None:
                recurrence.task_id = task.id
                if recurrence.id:
                    repo.update_recurring(recurrence)
                else:
                    repo.add_recurring(recurrence)
            elif self.original is not None:
                for r in repo.recurring_of(task.id):  # 定期タスクでなくなったら、繰り返しの時間帯も消す
                    repo.delete_recurring(r.id)
        except ValidationError as e:
            show_error(self.name_err if e.field == "タスク名" else self.err, str(e))
            return
        except OSError as e:
            show_error(self.err, f"保存できませんでした: {e}")
            return
        confirm_done(self, self.state, task.id)
        self.saved = self.state.repo.get_task(task.id)
        self.state.tasks_changed.emit()
        self.state.worklogs_changed.emit()  # 定期の予定を描き直す
        self.accept()
