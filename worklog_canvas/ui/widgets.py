"""小さな共通部品。"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QDate, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDateEdit, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QSizePolicy, QSlider,
    QToolButton, QWidget,
)

from ..core import timeutil as tu

ERROR_STYLE = "color: #C62828;"
_NONE_DATE = QDate(2000, 1, 1)


def color_icon(color: str, size: int = 12) -> QIcon:
    """カテゴリなどの色を示す丸い点。"""
    from PySide6.QtGui import QPainter
    pm = QPixmap(size * 2, size * 2)  # 2倍で描いて、高解像度の画面でもにじまないように
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    d = size * 2 * 0.72
    p.drawEllipse((size * 2 - d) / 2, (size * 2 - d) / 2, d, d)
    p.end()
    pm.setDevicePixelRatio(2)
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
        clear.setObjectName("dateClear")  # 丸い小さな「消す」ボタン（theme.py で見た目を決める）
        clear.setIcon(_clear_icon())
        clear.setIconSize(QSize(10, 10))
        clear.setFixedSize(26, 26)
        clear.setCursor(Qt.PointingHandCursor)
        clear.setToolTip("未設定にする")
        clear.setAccessibleName("日付を消す")
        clear.clicked.connect(lambda: self.set_date(None))
        sp = clear.sizePolicy()
        sp.setRetainSizeWhenHidden(True)  # 消えても欄の幅は変えない
        clear.setSizePolicy(sp)
        self.clear_button = clear
        lay.setSpacing(4)
        lay.addWidget(self.edit, 1)
        lay.addWidget(clear)
        cal = self.edit.calendarWidget()
        cal.clicked.connect(self._picked)
        cal.activated.connect(self._picked)
        self._popup = cal.window()
        self.edit.dateChanged.connect(self._changed)
        self.edit.dateChanged.connect(lambda _d: self._sync_clear())
        self._sync_clear()
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
    def _sync_clear(self) -> None:
        """日付が入っているときだけ「消す」ボタンを出す。"""
        self.clear_button.setVisible(self.date() is not None)

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


def _clear_icon() -> QIcon:
    """細い × の絵（文字の「×」より小さく、線の太さがそろう）。"""
    icon = QIcon()
    for color, mode in (("#7A8A99", QIcon.Normal), ("#0B5E8A", QIcon.Active)):
        pm = QPixmap(40, 40)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(color), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(10, 10, 30, 30)
        p.drawLine(30, 10, 10, 30)
        p.end()
        icon.addPixmap(pm, mode)
    return icon


class RadioChoice(QWidget):
    """横に並べたラジオボタンで1つ選ぶ（QComboBox と同じ currentText / setCurrentText で使える）。"""

    currentTextChanged = Signal(str)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(18)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        for text in items:
            b = QRadioButton(text)
            self.group.addButton(b)
            self.buttons[text] = b
            lay.addWidget(b)
            b.toggled.connect(lambda on, t=text: on and self.currentTextChanged.emit(t))
        lay.addStretch()
        if items:
            self.buttons[items[0]].setChecked(True)

    def currentText(self) -> str:
        b = self.group.checkedButton()
        return b.text() if b else ""

    def setCurrentText(self, text: str) -> None:
        if text in self.buttons:
            self.buttons[text].setChecked(True)


class ProgressBarInput(QWidget):
    """進捗率をバー（スライダー）で入力する（0〜100、5刻み）。右に「40%」のように数字を出す。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 20)  # 1目盛り = 5%
        self.slider.setPageStep(2)
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.slider.setAccessibleName("進捗率")
        self.label = QLabel("0%")
        self.label.setMinimumWidth(44)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(lambda v: self.label.setText(f"{v * 5}%"))

    def value(self) -> int:
        return self.slider.value() * 5

    def value5(self) -> int:
        return self.value()

    def setValue(self, value: int) -> None:
        self.slider.setValue(int(round(value / 5)))


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
