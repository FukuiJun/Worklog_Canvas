"""作業バーの編集ダイアログ（F-02）。"""
from __future__ import annotations

import copy
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout,
    QWidget,
)

from ..core import timeline as tl
from ..core.models import (
    KIND_ONEOFF, KIND_TASK, MAX_SUBTASKS, ONEOFF_TITLE_MAX, STATUS_DONE, SubItem, ValidationError, Worklog,
)
from ..core.overlap import OverlapError
from .state import AppState
from .widgets import ProgressSpin, TimeCombo, color_icon, error_label, show_error


def confirm_done(parent, state: AppState, task_id: str) -> None:
    """進捗率を100にしたとき、ステータスを完了にするか確認する（F-03）。"""
    task = state.repo.get_task(task_id)
    if task.needs_done_confirmation():
        ans = QMessageBox.question(parent, "Worklog Canvas",
                                   f"「{task.name}」の進捗率が100%になりました。\nステータスを「完了」にしますか？")
        if ans == QMessageBox.Yes:
            state.repo.set_status(task_id, STATUS_DONE, state.today())


class WorklogDialog(QDialog):
    def __init__(self, state: AppState, worklog: Worklog, parent=None):
        super().__init__(parent)
        self.setWindowTitle("作業バーの編集")
        self.state = state
        self.original = worklog
        self.subs: list[SubItem] = copy.deepcopy(worklog.subs)
        tasks_by_id = state.tasks_by_id()
        self._tasks_by_id = tasks_by_id
        # 選べるタスク: 未完了 + 現在使っているタスク（完了済みでも）
        used = worklog.task_ids()
        self._choices = tl.sort_open_tasks(state.repo.tasks) + \
            [t for t in state.repo.tasks if not t.is_open and t.id in used]

        form = QFormLayout()
        # 種別
        kind_box = QWidget()
        kl = QHBoxLayout(kind_box)
        kl.setContentsMargins(0, 0, 0, 0)
        self.rb_task = QRadioButton("タスク")
        self.rb_oneoff = QRadioButton("単発作業")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_task)
        grp.addButton(self.rb_oneoff)
        kl.addWidget(self.rb_task)
        kl.addWidget(self.rb_oneoff)
        kl.addStretch()
        form.addRow("種別", kind_box)
        self.task_combo = self._task_combo()
        form.addRow("タスク", self.task_combo)
        self.title_edit = QLineEdit(worklog.title)
        self.title_edit.setMaxLength(ONEOFF_TITLE_MAX)
        form.addRow("タイトル", self.title_edit)
        # 時刻
        tbox = QWidget()
        tlay = QHBoxLayout(tbox)
        tlay.setContentsMargins(0, 0, 0, 0)
        self.start_combo, self.end_combo = TimeCombo(), TimeCombo()
        self.start_combo.set_minutes(worklog.start)
        self.end_combo.set_minutes(worklog.end)
        tlay.addWidget(self.start_combo)
        tlay.addWidget(QLabel("〜"))
        tlay.addWidget(self.end_combo)
        tlay.addStretch()
        form.addRow(f"時刻（{worklog.date:%Y/%m/%d}）", tbox)
        # サブタスク
        form.addRow("サブタスク", self._subs_box())
        self.memo = QPlainTextEdit(worklog.memo)
        self.memo.setFixedHeight(60)
        form.addRow("メモ", self.memo)
        self.progress = ProgressSpin()
        form.addRow("進捗率（メインのタスク）", self.progress)

        self.err = error_label()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.err)
        lay.addWidget(buttons)

        if worklog.kind == KIND_TASK:
            self.rb_task.setChecked(True)
            idx = self.task_combo.findData(worklog.task_id)
            self.task_combo.setCurrentIndex(max(idx, 0))
        else:
            self.rb_oneoff.setChecked(True)
        self.rb_task.toggled.connect(self._sync_kind)
        self.task_combo.currentIndexChanged.connect(self._load_progress)
        self._sync_kind()
        self._load_progress()
        self._refresh_subs()
        self.setMinimumWidth(480)

    def _task_combo(self) -> QComboBox:
        c = QComboBox()
        for t in self._choices:
            c.addItem(color_icon(self.state.task_color(t)), t.name, t.id)
        return c

    def _subs_box(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        self.sub_list = QListWidget()
        self.sub_list.setFixedHeight(72)
        self.sub_list.setTextElideMode(Qt.ElideRight)
        self.sub_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        v.addWidget(self.sub_list)
        row1 = QHBoxLayout()
        self.sub_task_combo = self._task_combo()
        self.btn_add_sub_task = QPushButton("タスクを追加")
        self.btn_add_sub_task.clicked.connect(self._add_sub_task)
        row1.addWidget(self.sub_task_combo, 1)
        row1.addWidget(self.btn_add_sub_task)
        v.addLayout(row1)
        row2 = QHBoxLayout()
        self.sub_title = QLineEdit()
        self.sub_title.setPlaceholderText("単発作業のタイトル")
        self.sub_title.setMaxLength(ONEOFF_TITLE_MAX)
        self.btn_add_sub_title = QPushButton("単発作業を追加")
        self.btn_add_sub_title.clicked.connect(self._add_sub_title)
        self.btn_remove_sub = QPushButton("選んだサブタスクを外す")
        self.btn_remove_sub.clicked.connect(self._remove_sub)
        row2.addWidget(self.sub_title, 1)
        row2.addWidget(self.btn_add_sub_title)
        v.addLayout(row2)
        v.addWidget(self.btn_remove_sub, 0, Qt.AlignLeft)
        return box

    # --- 表示の同期 ---
    def _sync_kind(self) -> None:
        is_task = self.rb_task.isChecked()
        self.task_combo.setEnabled(is_task)
        self.title_edit.setEnabled(not is_task)
        self.progress.setEnabled(is_task and self.task_combo.count() > 0)

    def _load_progress(self) -> None:
        tid = self.task_combo.currentData()
        if tid:
            self.progress.setValue(self.state.repo.get_task(tid).progress)

    def _refresh_subs(self) -> None:
        self.sub_list.clear()
        for s in self.subs:
            label = tl.item_label(s.kind, s.task_id, s.title, self._tasks_by_id)
            prefix = "" if s.kind == KIND_TASK else "［単発］"
            item = QListWidgetItem(color_icon(self.state.sub_color(s.kind, s.task_id, self._tasks_by_id)),
                                   prefix + label)
            item.setToolTip(label)
            self.sub_list.addItem(item)
        full = len(self.subs) >= MAX_SUBTASKS
        self.btn_add_sub_task.setEnabled(not full and self.sub_task_combo.count() > 0)
        self.btn_add_sub_title.setEnabled(not full)
        self.btn_remove_sub.setEnabled(bool(self.subs))

    def _add_sub_task(self) -> None:
        tid = self.sub_task_combo.currentData()
        if not tid:
            return
        main = self.task_combo.currentData() if self.rb_task.isChecked() else None
        if tid == main or any(s.kind == KIND_TASK and s.task_id == tid for s in self.subs):
            show_error(self.err, "同じタスクを重ねて選ぶことはできません")
            return
        self.subs.append(SubItem(KIND_TASK, task_id=tid))
        show_error(self.err, None)
        self._refresh_subs()

    def _add_sub_title(self) -> None:
        title = self.sub_title.text().strip()
        if not title:
            show_error(self.err, "単発作業のタイトルを入力してください")
            return
        self.subs.append(SubItem(KIND_ONEOFF, title=title))
        self.sub_title.clear()
        show_error(self.err, None)
        self._refresh_subs()

    def _remove_sub(self) -> None:
        row = self.sub_list.currentRow()
        if 0 <= row < len(self.subs):
            del self.subs[row]
            self._refresh_subs()

    # --- 保存 ---
    def build(self) -> Worklog:
        if self.rb_task.isChecked():
            kind, task_id, title = KIND_TASK, self.task_combo.currentData(), ""
        else:
            kind, task_id, title = KIND_ONEOFF, None, self.title_edit.text().strip()
        return replace(self.original, kind=kind, task_id=task_id, title=title,
                       start=self.start_combo.minutes(), end=self.end_combo.minutes(),
                       memo=self.memo.toPlainText(), subs=copy.deepcopy(self.subs))

    def _save(self) -> None:
        new = self.build()
        try:
            if new != self.original:
                self.state.editor.update(new, "編集")
                self.state.worklogs_changed.emit()
            if new.kind == KIND_TASK and self.progress.isEnabled():
                value = self.progress.value5()
                if value != self.state.repo.get_task(new.task_id).progress:
                    self.state.repo.set_progress(new.task_id, value, self.state.today())
                    confirm_done(self, self.state, new.task_id)
                    self.state.tasks_changed.emit()
        except (ValidationError, OverlapError) as e:
            show_error(self.err, str(e))
            return
        except OSError as e:
            show_error(self.err, f"保存できませんでした: {e}")
            return
        self.accept()
