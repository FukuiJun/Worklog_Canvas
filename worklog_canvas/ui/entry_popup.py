"""作業バー作成時の入力ポップアップ（F-02）。

- ↑↓ で候補（未完了タスク）を選んで Enter、または候補をクリック → メイン=タスク
- 文字を入力して Enter（候補を選んでいない状態）→ メイン=単発作業（入力文字がタイトル）
- Esc → 作成を取り消す
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from ..core import timeline as tl
from ..core import timeutil as tu
from ..core.models import KIND_ONEOFF, KIND_TASK, ONEOFF_TITLE_MAX, Task
from .widgets import color_icon, error_label, show_error


@dataclass
class EntryResult:
    kind: str
    task_id: str | None = None
    title: str = ""


class EntryPopup(QDialog):
    def __init__(self, tasks: list[Task], color_of, start: int, end: int, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("entryPopup")
        self.result_value: EntryResult | None = None
        self._tasks = tl.sort_open_tasks(tasks)
        self._color_of = color_of
        self._explicit = False  # 利用者が候補を明示的に選んだか

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        head = QLabel(f"{tu.format_hhmm(start)}〜{tu.format_hhmm(end)}（{tu.format_hours(end - start)}）")
        head.setStyleSheet("font-weight: bold;")
        lay.addWidget(head)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("タスク名で絞り込み／単発作業のタイトルを入力")
        self.edit.setMaxLength(ONEOFF_TITLE_MAX + 20)
        lay.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setMinimumSize(380, 200)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.list)
        self.err = error_label()
        lay.addWidget(self.err)
        hint = QLabel("Enter：入力した文字で単発作業を記録\n↑↓で候補を選んでEnter／クリック：タスクを記録\nEsc：取り消し")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        lay.addWidget(hint)

        self.edit.textChanged.connect(self._refilter)
        self.edit.returnPressed.connect(self._enter)
        self.edit.installEventFilter(self)
        self.list.installEventFilter(self)
        self.list.itemClicked.connect(self._choose_item)
        self.list.itemActivated.connect(self._choose_item)
        self._refilter("")
        self.edit.setFocus()

    # --- 候補 ---
    def _refilter(self, text: str) -> None:
        self.list.clear()
        for t in tl.filter_tasks(self._tasks, text):
            item = QListWidgetItem(color_icon(self._color_of(t)), t.name)
            item.setData(Qt.UserRole, t.id)
            item.setToolTip(f"{t.name}\n{t.id}　{t.category or '（カテゴリなし）'}　{t.status}")
            self.list.addItem(item)
        self.list.setCurrentRow(-1)
        self._explicit = False
        show_error(self.err, None)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress:
            key = ev.key()
            if obj is self.edit and key in (Qt.Key_Down, Qt.Key_Up) and self.list.count():
                self.list.setFocus()
                self.list.setCurrentRow(0 if key == Qt.Key_Down else self.list.count() - 1)
                self._explicit = True
                return True
            if obj is self.list:
                if key == Qt.Key_Up and self.list.currentRow() <= 0:
                    self.list.setCurrentRow(-1)
                    self._explicit = False
                    self.edit.setFocus()
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter) and self.list.currentItem():
                    self._choose_item(self.list.currentItem())
                    return True
                if ev.text() and ev.text().isprintable() and key not in (Qt.Key_Up, Qt.Key_Down):
                    self.edit.setFocus()
                    self.edit.event(ev)
                    return True
        return super().eventFilter(obj, ev)

    # --- 決定 ---
    def _choose_item(self, item: QListWidgetItem) -> None:
        self.result_value = EntryResult(KIND_TASK, task_id=item.data(Qt.UserRole))
        self.accept()

    def _enter(self) -> None:
        if self._explicit and self.list.currentItem():
            self._choose_item(self.list.currentItem())
            return
        title = self.edit.text().strip()
        if not title:
            show_error(self.err, "タスクを選ぶか、タイトルを入力してください")
            return
        if len(title) > ONEOFF_TITLE_MAX:
            show_error(self.err, f"タイトルは{ONEOFF_TITLE_MAX}文字以内で入力してください")
            return
        self.result_value = EntryResult(KIND_ONEOFF, title=title)
        self.accept()
