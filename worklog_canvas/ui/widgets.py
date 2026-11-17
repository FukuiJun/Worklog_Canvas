"""小さな共通部品。"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QDate, QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCalendarWidget, QComboBox, QDateEdit, QHBoxLayout, QLabel,
    QLineEdit, QRadioButton, QSizePolicy, QSlider, QSpinBox, QToolButton, QWidget,
)

from ..core import timeutil as tu

ERROR_STYLE = "color: #C62828;"
_NONE_DATE = QDate(2000, 1, 1)
ROW_HEIGHT = 36  # ラジオボタン・バーの行の高さ（入力欄の高さ＋上下の余白）


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
        enable_calendar_hover(self.edit)
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


def row_label(text: str) -> QLabel:
    """ラジオボタン・バーの行の見出し（行の高さに合わせて上下中央にそろえる）。"""
    label = QLabel(text)
    label.setMinimumHeight(ROW_HEIGHT)
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return label


class RadioChoice(QWidget):
    """横に並べたラジオボタンで1つ選ぶ（QComboBox と同じ currentText / setCurrentText で使える）。"""

    currentTextChanged = Signal(str)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(18)
        self.setMinimumHeight(ROW_HEIGHT)  # ほかの入力欄と同じ高さにして、行の間を詰めすぎない
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
    """進捗率をバー（スライダー）か数値で入力する（0〜100、5刻み）。バーと数値の欄は連動する。

    数値の欄には 5 の倍数でない値も打てるが、確定したときに最も近い 5 の倍数に直す。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(12)
        self.setMinimumHeight(ROW_HEIGHT)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 20)  # 1目盛り = 5%
        self.slider.setPageStep(2)
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.slider.setAccessibleName("進捗率のバー")
        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setSingleStep(5)
        self.spin.setSuffix(" %")
        self.spin.setFixedWidth(96)
        self.spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.spin.setAccessibleName("進捗率")
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.spin.editingFinished.connect(lambda: self.spin.setValue(self.value5()))

    def _from_slider(self, v: int) -> None:
        if self.spin.value() // 5 != v or self.spin.value() % 5:
            self.spin.blockSignals(True)
            self.spin.setValue(v * 5)
            self.spin.blockSignals(False)

    def _from_spin(self, v: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v / 5)))
        self.slider.blockSignals(False)

    def value(self) -> int:
        return self.spin.value()

    def value5(self) -> int:
        """5刻みに丸めた値（保存に使う）。"""
        return int(round(self.spin.value() / 5)) * 5

    def setValue(self, value: int) -> None:
        self.spin.setValue(int(value))


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


class _CalendarHover(QObject):
    """カレンダーの日付の上にマウスを置いたとき、その日（クリックすると選ばれる日）を淡く色づける。

    QCalendarWidget の日付のマスはスタイルシートの :hover が効かないので、マウスの位置の日付に
    文字の書式（背景色）を付け、離れたら戻す。
    """

    COLOR = QColor("#E3F2FB")

    def __init__(self, cal: QCalendarWidget):
        super().__init__(cal)
        self.cal = cal
        self.view = cal.findChild(QAbstractItemView)
        self.hovered: QDate | None = None
        if self.view is not None:
            self.view.setMouseTracking(True)
            self.view.viewport().setMouseTracking(True)
            self.view.viewport().installEventFilter(self)
        cal.currentPageChanged.connect(lambda _y, _m: self._set(None))

    def date_at(self, pos) -> QDate | None:
        """表示中のマス（pos はビューポートの座標）の日付。曜日・週番号の見出しは None。"""
        index = self.view.indexAt(pos)
        if not index.isValid():
            return None
        first_row = 0 if self.cal.horizontalHeaderFormat() == QCalendarWidget.NoHorizontalHeader else 1
        first_col = 0 if self.cal.verticalHeaderFormat() == QCalendarWidget.NoVerticalHeader else 1
        row, col = index.row() - first_row, index.column() - first_col
        if row < 0 or col < 0:
            return None
        try:
            day = int(index.data())
        except (TypeError, ValueError):
            return None
        shown = QDate(self.cal.yearShown(), self.cal.monthShown(), 1)
        if row <= 1 and day > 20:
            shown = shown.addMonths(-1)  # 前の月の末の日
        elif row >= 4 and day < 15:
            shown = shown.addMonths(1)  # 次の月の初めの日
        d = QDate(shown.year(), shown.month(), day)
        return d if d.isValid() else None

    def _set(self, d: QDate | None) -> None:
        if d == self.hovered:
            return
        if self.hovered is not None:
            self.cal.setDateTextFormat(self.hovered, QTextCharFormat())
        self.hovered = d
        if d is not None:
            fmt = QTextCharFormat()
            fmt.setBackground(self.COLOR)
            self.cal.setDateTextFormat(d, fmt)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.MouseMove:
            self._set(self.date_at(ev.position().toPoint()))
        elif t in (QEvent.Leave, QEvent.Hide):
            self._set(None)
        return False


def enable_calendar_hover(date_edit: QDateEdit) -> None:
    """日付欄のカレンダー（ポップアップ）で、マウスを置いた日を淡く色づけるようにする。"""
    cal = date_edit.calendarWidget()
    if cal is not None and not cal.property("_wc_hover"):
        cal.setProperty("_wc_hover", True)
        _CalendarHover(cal)
