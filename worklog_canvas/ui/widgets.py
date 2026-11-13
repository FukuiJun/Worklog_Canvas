"""小さな共通部品。"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QDate, QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QComboBox, QDateEdit, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QToolButton, QWidget

from ..core import timeutil as tu

ERROR_STYLE = "color: #C62828;"
_NONE_DATE = QDate(2000, 1, 1)


def color_icon(color: str, size: int = 12) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(color))
    return QIcon(pm)


def text_color_for(bg: str) -> QColor:
    c = QColor(bg)
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return QColor("#212121") if lum > 160 else QColor("#FFFFFF")


def error_label() -> QLabel:
    lab = QLabel()
    lab.setStyleSheet(ERROR_STYLE)
    lab.setWordWrap(True)
    lab.hide()
    return lab


def show_error(label: QLabel, message: str | None) -> None:
    label.setText(message or "")
    label.setVisible(bool(message))


class OptionalDateEdit(QWidget):
    """空にできる日付入力（「—」が未設定）。

    未設定のときは、内部では 2000-01-01 を「未設定」の印にしている。そのままだと、カレンダーを開いたり
    ↑↓キーを押したりしたときに2000年から始まってしまうので、未設定の欄を操作し始めたら今日の日付から始める。
    - クリック（カレンダーを開く）: いったん今日にする。日付を選ばずに閉じたら未設定に戻す
    - キー入力: 今日から入力を始める
    - Tab で移るだけなら変えない
    """

    _NO_START_KEYS = (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter,
                      Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta)

    def __init__(self, parent=None, today=_dt.date.today):
        super().__init__(parent)
        self._today = today
        self._provisional = False  # クリックで仮に今日を入れた状態（まだ利用者が決めていない）
        self._setting = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QDateEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("yyyy-MM-dd")
        self.edit.setMinimumDate(_NONE_DATE)
        self.edit.setSpecialValueText("—")
        self.edit.setDate(_NONE_DATE)
        clear = QToolButton()
        clear.setText("×")
        clear.setToolTip("未設定にする")
        clear.clicked.connect(lambda: self.set_date(None))
        lay.addWidget(self.edit, 1)
        lay.addWidget(clear)
        cal = self.edit.calendarWidget()
        cal.clicked.connect(self._picked)
        cal.activated.connect(self._picked)
        self._popup = cal.window()
        self.edit.dateChanged.connect(self._changed)
        self._inputs = [self.edit] + self.edit.findChildren(QLineEdit)
        for w in self._inputs + [self._popup]:
            w.installEventFilter(self)

    # --- 値 ---
    def date(self) -> _dt.date | None:
        d = self.edit.date()
        if d == _NONE_DATE:
            return None
        return _dt.date(d.year(), d.month(), d.day())

    def set_date(self, d: _dt.date | None) -> None:
        self._provisional = False
        self._set(d)

    def _set(self, d: _dt.date | None) -> None:
        self._setting = True
        try:
            self.edit.setDate(_NONE_DATE if d is None else QDate(d.year, d.month, d.day))
        finally:
            self._setting = False

    # --- 未設定の欄を操作し始めたとき ---
    def _start_from_today(self, provisional: bool) -> None:
        if self.date() is None:
            self._provisional = provisional
            self._set(self._today())

    def _changed(self, _d) -> None:
        if not self._setting:
            self._provisional = False  # 利用者が日付を変えた

    def _picked(self, d: QDate) -> None:
        self._provisional = False
        self.edit.setDate(d)

    def _revert_if_untouched(self) -> None:
        if self._provisional:
            self._provisional = False
            self._set(None)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self._popup:
            if t == QEvent.Hide:  # カレンダーを閉じた（選んだ場合は先に _picked が呼ばれる）
                QTimer.singleShot(0, self._revert_if_untouched)
        elif t == QEvent.MouseButtonPress:
            self._start_from_today(provisional=True)
        elif t == QEvent.KeyPress and ev.key() not in self._NO_START_KEYS and self.date() is None:
            self._start_from_today(provisional=False)
            if ev.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown):
                return True  # 最初の↑↓は「今日を表示する」だけにする（今日の1年後などにしない）
        elif t == QEvent.FocusOut and ev.reason() != Qt.PopupFocusReason and not self._popup.isVisible():
            self._revert_if_untouched()
        return super().eventFilter(obj, ev)


class ProgressSpin(QSpinBox):
    """進捗率（0〜100、5刻み）。5の倍数でない値は最も近い5の倍数に直す。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setSingleStep(5)
        self.setSuffix(" %")
        self.editingFinished.connect(lambda: self.setValue(self.value5()))

    def value5(self) -> int:
        return int(round(self.value() / 5)) * 5


class TimeCombo(QComboBox):
    """15分刻みの時刻選択（00:00〜24:00）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        for m in range(0, tu.DAY_MINUTES + 1, tu.SNAP_MINUTES):
            self.addItem(tu.format_hhmm(m), m)
        self.setMaxVisibleItems(16)

    def minutes(self) -> int:
        return int(self.currentData())

    def set_minutes(self, m: int) -> None:
        self.setCurrentIndex(self.findData(m))
