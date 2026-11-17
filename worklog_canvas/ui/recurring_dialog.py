"""定期タスク（F-09）の登録・編集ダイアログと、一覧の管理ダイアログ。"""
from __future__ import annotations

import copy
import datetime as _dt

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from ..core import recurring as rc
from ..core import timeline as tl
from ..core.models import KIND_ONEOFF, KIND_TASK, ONEOFF_TITLE_MAX, ValidationError
from .state import AppState
from .widgets import OptionalDateEdit, TimeCombo, color_icon, error_label, show_error


class RecurrenceFields(QWidget):
    """繰り返しの時間帯の入力欄（時刻・繰り返し・曜日・日にち・開始日・終了日）。

    定期タスクの登録画面と、タスクの登録画面（種類=定期）で共用する。
    """

    def __init__(self, state: AppState, base: rc.RecurringItem, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        tbox = QWidget()
        tlay = QHBoxLayout(tbox)
        tlay.setContentsMargins(0, 0, 0, 0)
        self.start, self.end = TimeCombo(), TimeCombo()
        tlay.addWidget(self.start)
        tlay.addWidget(QLabel("〜"))
        tlay.addWidget(self.end)
        tlay.addStretch()
        form.addRow("時刻", tbox)
        self.pattern = QComboBox()
        self.pattern.addItems(rc.PATTERNS)
        form.addRow("繰り返し", self.pattern)
        self.days_box = QWidget()
        dl = QHBoxLayout(self.days_box)
        dl.setContentsMargins(0, 0, 0, 0)
        self.day_checks = []
        for name in rc.WEEKDAY_NAMES:
            cb = QCheckBox(name)
            self.day_checks.append(cb)
            dl.addWidget(cb)
        dl.addStretch()
        form.addRow("曜日", self.days_box)
        self.month_day = QSpinBox()
        self.month_day.setRange(1, 31)
        self.month_day.setSuffix(" 日")
        self.month_day.setToolTip("その月にない日（31日など）は月末")
        form.addRow("日にち", self.month_day)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        form.addRow("開始日", self.start_date)
        self.end_date = OptionalDateEdit(today=state.today)
        form.addRow("終了日（任意）", self.end_date)
        self.pattern.currentTextChanged.connect(self._sync)
        self.load(base)

    def load(self, it: rc.RecurringItem) -> None:
        self.start.set_minutes(it.start)
        self.end.set_minutes(it.end)
        self.pattern.setCurrentText(it.pattern)
        for i, cb in enumerate(self.day_checks):
            cb.setChecked(i in it.weekdays)
        self.month_day.setValue(it.month_day)
        sd = it.start_date
        self.start_date.setDate(QDate(sd.year, sd.month, sd.day))
        self.end_date.set_date(it.end_date)
        self._sync()

    def _sync(self) -> None:
        p = self.pattern.currentText()
        self.days_box.setEnabled(p in (rc.WEEKLY, rc.BIWEEKLY))
        self.month_day.setEnabled(p == rc.MONTHLY)

    def apply(self, it: rc.RecurringItem) -> rc.RecurringItem:
        """入力内容を it に入れたものを返す（メイン・メモ・id はそのまま）。"""
        d = self.start_date.date()
        new = copy.deepcopy(it)
        new.start, new.end = self.start.minutes(), self.end.minutes()
        new.pattern = self.pattern.currentText()
        new.weekdays = [i for i, cb in enumerate(self.day_checks) if cb.isChecked()]
        new.month_day = self.month_day.value()
        new.start_date = _dt.date(d.year(), d.month(), d.day())
        new.end_date = self.end_date.date()
        return new


def default_recurrence(state: AppState) -> rc.RecurringItem:
    return rc.RecurringItem(id="", start=540, end=600, weekdays=[state.today().weekday()],
                            start_date=state.today())


class RecurringDialog(QDialog):
    """定期タスクの登録（item=None）・編集。initial で初期値を渡せる（右クリックした曜日・時刻など）。"""

    def __init__(self, state: AppState, item: rc.RecurringItem | None = None, parent=None,
                 initial: rc.RecurringItem | None = None):
        super().__init__(parent)
        self.state = state
        self.original = item
        base = copy.deepcopy(item or initial or default_recurrence(state))
        self.base = base
        self.setWindowTitle("定期タスクの編集" if item else "定期タスクの登録")
        self.saved: rc.RecurringItem | None = None

        form = QFormLayout()
        kind_box = QWidget()
        kl = QHBoxLayout(kind_box)
        kl.setContentsMargins(0, 0, 0, 0)
        self.rb_task, self.rb_oneoff = QRadioButton("タスク"), QRadioButton("単発作業")
        grp = QButtonGroup(self)
        for b in (self.rb_task, self.rb_oneoff):
            grp.addButton(b)
            kl.addWidget(b)
        kl.addStretch()
        form.addRow("種別", kind_box)
        self.task_combo = QComboBox()
        choices = tl.sort_open_tasks(state.repo.tasks)
        if base.kind == KIND_TASK and base.task_id and all(t.id != base.task_id for t in choices):
            choices += [t for t in state.repo.tasks if t.id == base.task_id]  # 完了したタスクでも今の設定は残す
        for t in choices:
            self.task_combo.addItem(color_icon(state.task_color(t)), t.name, t.id)
        form.addRow("タスク", self.task_combo)
        self.title = QLineEdit(base.title)
        self.title.setMaxLength(ONEOFF_TITLE_MAX)
        self.title.setPlaceholderText("例: 朝会")
        form.addRow("タイトル", self.title)
        self.fields = RecurrenceFields(state, base)
        self.memo = QPlainTextEdit(base.memo)
        self.memo.setFixedHeight(56)

        note = QLabel("タイムラインに「定期の予定」として表示されます。右クリック →「作業バーにする」で記録します。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #5B6B7B;")
        self.err = error_label()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.fields)
        memo_form = QFormLayout()
        memo_form.addRow("メモ", self.memo)
        lay.addLayout(memo_form)
        lay.addWidget(note)
        lay.addWidget(self.err)
        lay.addWidget(buttons)
        self.setMinimumWidth(500)

        if base.kind == KIND_TASK and self.task_combo.count():
            self.rb_task.setChecked(True)
            self.task_combo.setCurrentIndex(max(0, self.task_combo.findData(base.task_id)))
        else:
            self.rb_oneoff.setChecked(True)
        self.rb_task.setEnabled(self.task_combo.count() > 0)
        self.rb_task.toggled.connect(self._sync)
        self._sync()

    # 以前の名前でも参照できるように（テストや右クリックからの初期値の確認用）
    @property
    def start(self):
        return self.fields.start

    @property
    def end(self):
        return self.fields.end

    @property
    def day_checks(self):
        return self.fields.day_checks

    def _sync(self) -> None:
        is_task = self.rb_task.isChecked()
        self.task_combo.setEnabled(is_task)
        self.title.setEnabled(not is_task)

    def build(self) -> rc.RecurringItem:
        is_task = self.rb_task.isChecked()
        it = self.fields.apply(self.base)
        it.id = self.original.id if self.original else ""
        it.kind = KIND_TASK if is_task else KIND_ONEOFF
        it.task_id = self.task_combo.currentData() if is_task else None
        it.title = "" if is_task else self.title.text().strip()
        it.memo = self.memo.toPlainText()
        return it

    def _save(self) -> None:
        item = self.build()
        try:
            if self.original is None:
                self.saved = self.state.repo.add_recurring(item)
            else:
                self.state.repo.update_recurring(item)
                self.saved = item
        except ValidationError as e:
            show_error(self.err, str(e))
            return
        except KeyError:
            show_error(self.err, "選んだタスクが見つかりません")
            return
        self.state.worklogs_changed.emit()  # タイムラインの定期の予定を描き直す
        self.accept()


def item_label(state: AppState, it: rc.RecurringItem) -> str:
    return tl.item_label(it.kind, it.task_id, it.title, state.tasks_by_id())


class RecurringListDialog(QDialog):
    """登録した定期タスクの一覧（追加・編集・削除）。"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("定期タスク")
        self.list = QListWidget()
        self.list.setMinimumSize(520, 260)
        self.list.itemDoubleClicked.connect(lambda _i: self.edit())
        self.btn_add = QPushButton("＋ 登録")
        self.btn_add.setProperty("accent", True)
        self.btn_edit, self.btn_del = QPushButton("編集"), QPushButton("削除")
        close = QPushButton("閉じる")
        row = QHBoxLayout()
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(close)
        hint = QLabel("決まった時間の作業（朝会など）を登録すると、該当する日のタイムラインに「定期の予定」として表示されます。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5B6B7B;")
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(self.list, 1)
        lay.addLayout(row)
        self.btn_add.clicked.connect(self.add)
        self.btn_edit.clicked.connect(self.edit)
        self.btn_del.clicked.connect(self.delete)
        close.clicked.connect(self.accept)
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            b.setEnabled(not state.readonly)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        tasks = self.state.tasks_by_id()
        for it in self.state.repo.recurring:
            color = self.state.sub_color(it.kind, it.task_id, tasks)
            row = QListWidgetItem(color_icon(color), f"{item_label(self.state, it)}　—　{it.describe()}")
            row.setData(Qt.UserRole, it.id)
            if it.end_date:
                row.setToolTip(f"{it.start_date}〜{it.end_date}")
            self.list.addItem(row)
        if not self.state.repo.recurring:
            empty = QListWidgetItem("（まだ登録されていません）")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)

    def _selected(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def add(self) -> None:
        if RecurringDialog(self.state, None, self).exec():
            self.refresh()

    def edit(self) -> None:
        rid = self._selected()
        if rid and not self.state.readonly:
            if RecurringDialog(self.state, self.state.repo.get_recurring(rid), self).exec():
                self.refresh()

    def delete(self) -> None:
        rid = self._selected()
        if not rid or self.state.readonly:
            return
        it = self.state.repo.get_recurring(rid)
        if QMessageBox.question(self, "定期タスクの削除",
                                f"「{item_label(self.state, it)}（{it.describe()}）」を削除しますか？\n"
                                "記録済みの作業バーは消えません。") != QMessageBox.Yes:
            return
        self.state.repo.delete_recurring(rid)
        self.state.worklogs_changed.emit()
        self.refresh()
