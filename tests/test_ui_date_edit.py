"""空にできる日付入力（OptionalDateEdit）: 未設定の欄を操作し始めたら今日の日付から始める。"""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QDate, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget, QVBoxLayout  # noqa: E402

from worklog_canvas.ui.widgets import OptionalDateEdit  # noqa: E402

TODAY = dt.date(2026, 11, 18)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def box(qapp):
    host = QWidget()
    lay = QVBoxLayout(host)
    first = QLineEdit()
    w = OptionalDateEdit(today=lambda: TODAY)
    lay.addWidget(first)
    lay.addWidget(w)
    host.resize(300, 100)
    host.show()
    QTest.qWaitForWindowExposed(host)
    yield host, first, w
    w._popup.hide()
    host.close()


def _click(e, pos):
    """実際のクリックと同じく、その位置にある部品（文字の部分なら内部の入力欄）へ送る。"""
    child = e.childAt(pos)
    target = child if child is not None and not child.testAttribute(Qt.WA_TransparentForMouseEvents) else e
    QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, target.mapFrom(e, pos))
    QApplication.processEvents()


def _open_calendar(w):
    e = w.edit
    _click(e, QPoint(e.width() - 6, e.height() // 2))  # ▼ボタン


def test_calendar_opens_at_today(box):
    _, _, w = box
    assert w.date() is None
    _open_calendar(w)
    cal = w.edit.calendarWidget()
    assert w._popup.isVisible()
    assert cal.selectedDate() == QDate(2026, 11, 18)
    assert (cal.yearShown(), cal.monthShown()) == (2026, 11)  # 2000年1月ではない


def test_close_without_choosing_keeps_unset(box):
    _, _, w = box
    _open_calendar(w)
    w._popup.hide()  # Esc や外側のクリックで閉じたのと同じ
    QApplication.processEvents()
    assert w.date() is None
    assert w.edit.text() == "—"


def test_choose_date_from_calendar(box):
    _, _, w = box
    _open_calendar(w)
    w.edit.calendarWidget().clicked.emit(QDate(2026, 11, 25))
    w._popup.hide()
    QApplication.processEvents()
    assert w.date() == dt.date(2026, 11, 25)


def test_choose_today_itself(box):
    _, _, w = box
    _open_calendar(w)
    w.edit.calendarWidget().clicked.emit(QDate(2026, 11, 18))
    w._popup.hide()
    QApplication.processEvents()
    assert w.date() == TODAY


def test_first_arrow_key_shows_today(box):
    _, _, w = box
    w.edit.setFocus()
    QTest.keyClick(w.edit, Qt.Key_Up)
    assert w.date() == TODAY
    QTest.keyClick(w.edit, Qt.Key_Up)  # 2回目からは普通に変わる
    assert w.date() is not None and w.date() > TODAY


def test_tab_only_does_not_set(box):
    _, first, w = box
    first.setFocus()
    QTest.keyClick(first, Qt.Key_Tab)
    QTest.keyClick(QApplication.focusWidget() or w.edit, Qt.Key_Tab)
    QApplication.processEvents()
    assert w.date() is None


def test_existing_date_is_not_changed(box):
    _, _, w = box
    w.set_date(dt.date(2026, 12, 24))
    _open_calendar(w)
    assert w.edit.calendarWidget().selectedDate() == QDate(2026, 12, 24)
    w._popup.hide()
    QApplication.processEvents()
    assert w.date() == dt.date(2026, 12, 24)


def test_clear_button_still_works(box):
    _, _, w = box
    w.set_date(TODAY)
    w.set_date(None)
    assert w.date() is None


def test_click_text_then_leave_without_change_keeps_unset(box):
    _, first, w = box
    e = w.edit
    _click(e, QPoint(10, e.height() // 2))  # 文字の部分
    assert w.date() == TODAY  # 操作し始めたら今日から
    assert not w._popup.isVisible()
    first.setFocus()  # 何も変えずに別の欄へ
    QApplication.processEvents()
    assert w.date() is None
