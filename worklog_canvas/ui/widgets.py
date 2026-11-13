"""小さな共通部品。"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QComboBox, QDateEdit, QHBoxLayout, QLabel, QSpinBox, QToolButton, QWidget

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
    """空にできる日付入力（「—」が未設定）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.edit.calendarWidget().clicked.connect(lambda d: self.edit.setDate(d))

    def date(self) -> _dt.date | None:
        d = self.edit.date()
        if d == _NONE_DATE:
            return None
        return _dt.date(d.year(), d.month(), d.day())

    def set_date(self, d: _dt.date | None) -> None:
        self.edit.setDate(_NONE_DATE if d is None else QDate(d.year, d.month, d.day))


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
