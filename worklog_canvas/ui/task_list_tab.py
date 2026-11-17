"""タスク一覧画面（F-01）。"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton,
    QSlider,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import csv_import
from ..core import timeutil as tu
from ..core.models import (
    KIND_TASK, PRIORITIES, STATUS_NOT_STARTED, STATUSES, TASK_NAME_MAX, TASK_TYPES, TYPE_DAILY, TYPE_RECURRING, TYPE_WORK,
    Task,
)
from .state import AppState
from .task_dialog import TaskDialog
from .widgets import color_icon
from .worklog_dialog import confirm_done

OVERDUE_PLANNED = QColor("#E67E22")  # 完了予定日を過ぎた未完了タスク（橙）
OVERDUE_DEADLINE = QColor("#D32F2F")  # 期限を過ぎた未完了タスク（赤）
UNCATEGORIZED = "（未分類）"
ALL = "すべて"
OPEN = "未完了"

COLUMNS = ["ID", "タスク名", "種類", "カテゴリ", "サブカテゴリ", "ステータス", "優先度", "開始日", "完了予定日", "期限", "完了日",
           "実績時間", "進捗率"]


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
                subcategory=task.subcategory,
                status=STATUS_NOT_STARTED, priority=task.priority, start_date=task.start_date,
                planned_end=task.planned_end, deadline=task.deadline,
                memo=task.memo, task_type=task.task_type)


class TaskListTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        bar = QHBoxLayout()
        self.btn_add = QPushButton("＋ タスクを追加")
        self.btn_add.setProperty("accent", True)
        self.add_menu = QMenu(self.btn_add)
        for kind, text, tip in ((TYPE_WORK, "業務タスク", "進捗率・完了予定日・期限を管理し、完了させるタスク"),
                                (TYPE_DAILY, "日常タスク", "メール対応・雑務など終わりのない日々の作業"),
                                (TYPE_RECURRING, "定期タスク", "朝会など決まった時間に繰り返す作業")):
            a = self.add_menu.addAction(f"{text}　—　{tip}")
            a.setObjectName(kind)
            a.triggered.connect(lambda _c=False, k=kind: self.add_task(k))
        self.btn_add.setMenu(self.add_menu)
        self.btn_edit = QPushButton("編集")
        self.btn_dup = QPushButton("複製")
        self.btn_del = QPushButton("削除")
        self.btn_csv = QPushButton("CSVから取り込む…")
        self.btn_csv.setToolTip("列: タスク名,カテゴリ,完了予定日,期限（任意: サブカテゴリ,種類）"
                                "（UTF-8 BOM付き または Shift_JIS）")
        for b in (self.btn_add, self.btn_edit, self.btn_dup, self.btn_del, self.btn_csv):
            bar.addWidget(b)
        bar.addSpacing(20)
        bar.addWidget(QLabel("カテゴリ"))
        self.f_category = QComboBox()
        bar.addWidget(self.f_category)
        bar.addWidget(QLabel("種類"))
        self.f_type = QComboBox()
        self.f_type.addItems([ALL, *TASK_TYPES])
        bar.addWidget(self.f_type)
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

        self.btn_edit.clicked.connect(self.edit_selected)
        self.btn_dup.clicked.connect(self.duplicate_selected)
        self.btn_del.clicked.connect(self.delete_selected)
        self.btn_csv.clicked.connect(self.import_csv)
        self.table.cellDoubleClicked.connect(lambda r, c: self.edit_selected())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.f_category.currentIndexChanged.connect(self.refresh)
        self.f_status.currentIndexChanged.connect(self.refresh)
        self.f_type.currentIndexChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        state.tasks_changed.connect(self.refresh)
        state.categories_changed.connect(self._fill_category_filter)
        self._fill_category_filter()

    def _fill_category_filter(self) -> None:
        """カテゴリの絞り込み。カテゴリの下にサブカテゴリを字下げして並べる（data は (カテゴリ, サブ)）。"""
        cur = self.f_category.currentData()
        self.f_category.blockSignals(True)
        self.f_category.clear()
        self.f_category.addItem(ALL, None)
        for name, color in self.state.category_colors.items():
            self.f_category.addItem(color_icon(color), name, (name, None))
            for sub in self.state.subcategories.get(name, []):
                self.f_category.addItem(f"　└ {sub}", (name, sub))
        self.f_category.addItem(UNCATEGORIZED, ("", None))
        idx = next((i for i in range(self.f_category.count()) if self.f_category.itemData(i) == cur), 0)
        self.f_category.setCurrentIndex(idx)
        self.f_category.blockSignals(False)
        self.refresh()

    def filtered_tasks(self) -> list[Task]:
        cat_filter, st = self.f_category.currentData(), self.f_status.currentText()
        kind = self.f_type.currentText()
        out = []
        for t in self.state.repo.tasks:
            if kind not in (ALL, "") and t.task_type != kind:
                continue
            if cat_filter is not None:
                cat, sub = cat_filter
                if t.category != cat or (sub is not None and t.subcategory != sub):
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
        actual: dict[str, int] = {}
        for w in self.state.repo.worklogs:
            if w.kind == KIND_TASK and w.task_id:
                actual[w.task_id] = actual.get(w.task_id, 0) + w.duration
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
            kind_item = SortItem(t.task_type)
            kind_item.setData(Qt.UserRole, TASK_TYPES.index(t.task_type))
            cells.append(kind_item)
            cat = SortItem(t.category or "")
            cat.setIcon(color_icon(self.state.task_color(t)))
            cells.append(cat)
            cells.append(SortItem(t.subcategory or ""))
            # 日常・定期タスクはステータス・優先度を持たない（「—」）
            st = SortItem(t.status if t.is_work else "—")
            st.setData(Qt.UserRole, STATUSES.index(t.status) if t.is_work else -1)
            cells.append(st)
            pr = SortItem(t.priority if t.is_work else "—")
            pr.setData(Qt.UserRole, PRIORITIES.index(t.priority) if t.is_work else -1)
            cells.append(pr)
            if not t.is_work:
                st.setTextAlignment(Qt.AlignCenter)
                pr.setTextAlignment(Qt.AlignCenter)
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
            # 実績時間: これまでに作業バーで記録したメイン時間の累計（かかった工数）
            minutes = actual.get(t.id, 0)
            act = SortItem(tu.format_hours(minutes) if minutes else "")
            act.setData(Qt.UserRole, minutes)
            act.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            act.setToolTip("作業バーで記録したメイン時間の累計（サブ時間は含まない）")
            cells.append(act)
            prog = SortItem("" if t.is_work else "—")
            prog.setData(Qt.UserRole, t.progress if t.is_work else -1)
            if not t.is_work:
                prog.setTextAlignment(Qt.AlignCenter)
                prog.setToolTip("日常・定期タスクは進捗率を持ちません")
            cells.append(prog)
            for c, item in enumerate(cells):
                item.setData(Qt.UserRole + 1, t.id)
                self.table.setItem(r, c, item)
            if t.is_work:  # 進捗率は業務タスクだけ
                slider = ProgressSlider(t.id, t.progress, not self.state.readonly)
                slider.committed.connect(self.set_progress)
                self.table.setCellWidget(r, len(COLUMNS) - 1, slider)
            else:
                self.table.removeCellWidget(r, len(COLUMNS) - 1)
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
        self.btn_csv.setEnabled(not self.state.readonly)

    def build_context_menu(self, pos) -> QMenu | None:
        """表の右クリックメニュー（編集・複製・削除）。右クリックした行を選んでから出す。"""
        item = self.table.itemAt(pos)
        if item is None:
            return None
        self.table.selectRow(item.row())
        menu = QMenu(self.table)
        editable = not self.state.readonly
        for name, text, slot in (("edit", "編集…", self.edit_selected), ("duplicate", "複製…", self.duplicate_selected),
                                 ("delete", "削除…", self.delete_selected)):
            a = menu.addAction(text)
            a.setObjectName(name)
            a.setEnabled(editable)
            a.triggered.connect(lambda _c=False, f=slot: f())
            if name == "duplicate":
                menu.addSeparator()
        return menu

    def _show_context_menu(self, pos) -> None:
        menu = self.build_context_menu(pos)
        if menu is not None:
            menu.exec(self.table.viewport().mapToGlobal(pos))

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

    def import_csv(self, path: str | None = None) -> None:
        """タスク取り込み用CSVから一括追加する（F-01）。"""
        if self.state.readonly:
            return
        if not path:
            start = self.state.settings.csv_dir or str(Path.home())
            path, _ = QFileDialog.getOpenFileName(self, "タスクを取り込むCSVを選ぶ", start, "CSV ファイル (*.csv);;すべて (*)")
            if not path:
                return
        try:
            result = csv_import.import_csv(path, self.state.folder, self.state.repo)
        except csv_import.CsvFormatError as e:
            QMessageBox.warning(self, "CSVの取り込み", f"取り込めませんでした。\n{e}")
            return
        except OSError as e:
            QMessageBox.critical(self, "CSVの取り込み", f"取り込めませんでした。\n{e}")
            return
        self.state.settings.csv_dir = str(Path(path).parent)
        try:
            self.state.settings.save()
        except OSError:
            pass
        if result.new_categories:
            self.state.reload_categories()
        self.state.tasks_changed.emit()
        QMessageBox.information(self, "CSVの取り込み", result.message())

    def add_task(self, task_type: str = TYPE_WORK) -> None:
        """タスクを追加する（業務・日常・定期のいずれか）。"""
        dlg = TaskDialog(self.state, None, self, task_type=task_type)
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
