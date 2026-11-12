"""タスク一覧画面（F-01）。"""
from __future__ import annotations

import copy
import datetime as _dt

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QSlider,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.models import PRIORITIES, STATUS_NOT_STARTED, STATUSES, TASK_NAME_MAX, Task
from .state import AppState
from .task_dialog import TaskDialog
from .widgets import color_icon
from .worklog_dialog import confirm_done

OVERDUE_PLANNED = QColor("#E67E22")  # 完了予定日を過ぎた未完了タスク（橙）
OVERDUE_DEADLINE = QColor("#D32F2F")  # 期限を過ぎた未完了タスク（赤）
UNCATEGORIZED = "（未分類）"
ALL = "すべて"
OPEN = "未完了"

COLUMNS = ["ID", "タスク名", "カテゴリ", "ステータス", "優先度", "開始日", "完了予定日", "期限", "完了日",
           "予定工数", "進捗率"]


class SortItem(QTableWidgetItem):
    """表示文字ではなく Qt.UserRole の値で並べ替える。"""

    def __lt__(self, other):
        a, b = self.data(Qt.UserRole), other.data(Qt.UserRole)
        if a is None or b is None:
            return super().__lt__(other)
        return a < b


def _date_item(d: _dt.date | None) -> SortItem:
    it = SortItem(d.isoformat() if d else "")
    it.setData(Qt.UserRole, d.isoformat() if d else "9999-12-31")  # 未設定は末尾
    return it


class _NoWheelSlider(QSlider):
    """表をスクロールしているときに誤って値が変わらないよう、ホイールは表へ渡す。"""

    def wheelEvent(self, ev):
        ev.ignore()


class ProgressSlider(QWidget):
    """進捗率のスライダー（0〜100、5刻み）。つまみを離した時点（キー操作は変更のたび）で確定する。"""

    committed = Signal(str, int)  # タスクid, 進捗率

    def __init__(self, task_id: str, value: int, enabled: bool, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        self.slider = _NoWheelSlider(Qt.Horizontal)
        self.slider.setRange(0, 20)  # 1目盛り = 5%
        self.slider.setPageStep(2)
        self.slider.setValue(value // 5)
        self.slider.setEnabled(enabled)
        self.slider.setToolTip("進捗率（5%刻み）")
        self.label = QLabel(f"{value}%")
        self.label.setMinimumWidth(36)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderReleased.connect(self._commit)

    def value(self) -> int:
        return self.slider.value() * 5

    def _changed(self, _v: int) -> None:
        self.label.setText(f"{self.value()}%")
        if not self.slider.isSliderDown():
            self._commit()

    def _commit(self) -> None:
        self.committed.emit(self.task_id, self.value())


def duplicate_of(task: Task) -> Task:
    """複製の初期値: 進捗とステータスはリセットし、名前に「（コピー）」を付ける。"""
    suffix = "（コピー）"
    return Task(id="", name=(task.name[:TASK_NAME_MAX - len(suffix)] + suffix), category=task.category,
                status=STATUS_NOT_STARTED, priority=task.priority, start_date=task.start_date,
                planned_end=task.planned_end, deadline=task.deadline, estimate_hours=task.estimate_hours,
                memo=task.memo)


class TaskListTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        bar = QHBoxLayout()
        self.btn_add = QPushButton("追加")
        self.btn_edit = QPushButton("編集")
        self.btn_dup = QPushButton("複製")
        self.btn_del = QPushButton("削除")
        for b in (self.btn_add, self.btn_edit, self.btn_dup, self.btn_del):
            bar.addWidget(b)
        bar.addSpacing(20)
        bar.addWidget(QLabel("カテゴリ"))
        self.f_category = QComboBox()
        bar.addWidget(self.f_category)
        bar.addWidget(QLabel("ステータス"))
        self.f_status = QComboBox()
        self.f_status.addItems([ALL, OPEN, *STATUSES])
        bar.addWidget(self.f_status)
        bar.addStretch()
        self.count_label = QLabel()
        bar.addWidget(self.count_label)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.Fixed)
        self.table.setColumnWidth(len(COLUMNS) - 1, 170)
        legend = QLabel("<span style='color:#E67E22'>■</span> 完了予定日を過ぎた未完了タスク　"
                        "<span style='color:#D32F2F'>■</span> 期限を過ぎた未完了タスク　"
                        "見出しをクリックすると並べ替え")
        legend.setStyleSheet("color:#555;")

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)
        lay.addWidget(legend)

        self.btn_add.clicked.connect(self.add_task)
        self.btn_edit.clicked.connect(self.edit_selected)
        self.btn_dup.clicked.connect(self.duplicate_selected)
        self.btn_del.clicked.connect(self.delete_selected)
        self.table.cellDoubleClicked.connect(lambda r, c: self.edit_selected())
        self.f_category.currentIndexChanged.connect(self.refresh)
        self.f_status.currentIndexChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        state.tasks_changed.connect(self.refresh)
        state.categories_changed.connect(self._fill_category_filter)
        self._fill_category_filter()

    def _fill_category_filter(self) -> None:
        cur = self.f_category.currentText() or ALL
        self.f_category.blockSignals(True)
        self.f_category.clear()
        self.f_category.addItem(ALL)
        for name, color in self.state.category_colors.items():
            self.f_category.addItem(color_icon(color), name)
        self.f_category.addItem(UNCATEGORIZED)
        idx = self.f_category.findText(cur)
        self.f_category.setCurrentIndex(max(0, idx))
        self.f_category.blockSignals(False)
        self.refresh()

    def filtered_tasks(self) -> list[Task]:
        cat, st = self.f_category.currentText(), self.f_status.currentText()
        out = []
        for t in self.state.repo.tasks:
            if cat == UNCATEGORIZED and t.category:
                continue
            if cat not in (ALL, UNCATEGORIZED, "") and t.category != cat:
                continue
            if st == OPEN and not t.is_open:
                continue
            if st not in (ALL, OPEN) and t.status != st:
                continue
            out.append(t)
        return out

    def refresh(self) -> None:
        selected = self.selected_task_id()
        today = self.state.today()
        tasks = self.filtered_tasks()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(tasks))
        for r, t in enumerate(tasks):
            cells = []
            it = SortItem(t.id)
            it.setData(Qt.UserRole, t.id)
            cells.append(it)
            name = SortItem(t.name)
            name.setToolTip(t.memo or t.name)
            cells.append(name)
            cat = SortItem(t.category or "")
            cat.setIcon(color_icon(self.state.task_color(t)))
            cells.append(cat)
            st = SortItem(t.status)
            st.setData(Qt.UserRole, STATUSES.index(t.status))
            cells.append(st)
            pr = SortItem(t.priority)
            pr.setData(Qt.UserRole, PRIORITIES.index(t.priority))
            cells.append(pr)
            cells.append(_date_item(t.start_date))
            planned = _date_item(t.planned_end)
            if t.is_open and t.planned_end and t.planned_end < today:
                planned.setForeground(OVERDUE_PLANNED)
                planned.setToolTip("完了予定日を過ぎています")
            cells.append(planned)
            deadline = _date_item(t.deadline)
            if t.is_open and t.deadline and t.deadline < today:
                deadline.setForeground(OVERDUE_DEADLINE)
                deadline.setToolTip("期限を過ぎています")
            cells.append(deadline)
            cells.append(_date_item(t.done_date))
            est = SortItem("" if t.estimate_hours is None else f"{t.estimate_hours:g} h")
            est.setData(Qt.UserRole, t.estimate_hours if t.estimate_hours is not None else -1.0)
            cells.append(est)
            prog = SortItem("")
            prog.setData(Qt.UserRole, t.progress)
            cells.append(prog)
            for c, item in enumerate(cells):
                item.setData(Qt.UserRole + 1, t.id)
                self.table.setItem(r, c, item)
            slider = ProgressSlider(t.id, t.progress, not self.state.readonly)
            slider.committed.connect(self.set_progress)
            self.table.setCellWidget(r, len(COLUMNS) - 1, slider)
        self.table.setSortingEnabled(True)
        self.count_label.setText(f"{len(tasks)} 件 / 全 {len(self.state.repo.tasks)} 件")
        if selected:
            self.select_task(selected)
        self._sync_buttons()

    def selected_task_id(self) -> str | None:
        items = self.table.selectedItems()
        return items[0].data(Qt.UserRole + 1) if items else None

    def select_task(self, task_id: str) -> None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole + 1) == task_id:
                self.table.selectRow(r)
                return

    def _sync_buttons(self) -> None:
        has = self.selected_task_id() is not None and not self.state.readonly
        for b in (self.btn_edit, self.btn_dup, self.btn_del):
            b.setEnabled(has)
        self.btn_add.setEnabled(not self.state.readonly)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Delete:
            self.delete_selected()
            return
        super().keyPressEvent(ev)

    # --- 操作 ---
    def set_progress(self, task_id: str, value: int) -> None:
        """スライダーで進捗率を変更（F-03）。変更した日の履歴に記録し、100なら完了にするか確認する。"""
        if self.state.readonly or self.state.repo.get_task(task_id).progress == value:
            return
        try:
            self.state.repo.set_progress(task_id, value, self.state.today())
        except OSError as e:
            QMessageBox.critical(self, "Worklog Canvas", f"保存できませんでした: {e}")
            return
        confirm_done(self, self.state, task_id)
        # スライダー自身の処理が終わってから表を作り直す
        QTimer.singleShot(0, self.state.tasks_changed.emit)

    def add_task(self) -> None:
        dlg = TaskDialog(self.state, None, self)
        if dlg.exec() and dlg.saved:
            self.select_task(dlg.saved.id)

    def edit_selected(self) -> None:
        tid = self.selected_task_id()
        if tid and not self.state.readonly:
            TaskDialog(self.state, self.state.repo.get_task(tid), self).exec()

    def duplicate_selected(self) -> None:
        tid = self.selected_task_id()
        if not tid:
            return
        dlg = TaskDialog(self.state, None, self, initial=duplicate_of(self.state.repo.get_task(tid)))
        dlg.setWindowTitle("タスクの複製")
        if dlg.exec() and dlg.saved:
            self.select_task(dlg.saved.id)

    def delete_selected(self) -> None:
        tid = self.selected_task_id()
        if not tid or self.state.readonly:
            return
        task = self.state.repo.get_task(tid)
        n = len(self.state.repo.linked_worklogs(tid))
        if n:
            msg = (f"「{task.name}」は {n} 件の作業バーで使われています。\n"
                   f"削除すると、これらは単発作業（タイトル：元のタスク名）に変わります。\n"
                   "削除しますか？\n\n※ タイムラインの「元に戻す」履歴は消去されます。")
        else:
            msg = f"「{task.name}」を削除しますか？"
        if QMessageBox.question(self, "タスクの削除", msg) != QMessageBox.Yes:
            return
        try:
            self.state.repo.delete_task(tid)
        except OSError as e:
            QMessageBox.critical(self, "Worklog Canvas", f"保存できませんでした: {e}")
            return
        self.state.editor.clear()  # 削除したタスクを参照する取り消し操作が残らないように
        self.state.tasks_changed.emit()
        self.state.worklogs_changed.emit()
