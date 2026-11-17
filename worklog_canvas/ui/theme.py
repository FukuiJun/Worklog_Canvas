"""画面の見た目（白基調・水色・角丸）。

デザイン案「Worklog Canvas 新デザイン（白基調・水色）」のスタイルガイドに合わせた色と、
アプリ全体に当てるスタイルシート。水色は文字に使わない（白地で読みにくいため）。
文字のアクセントは濃い青、主なボタンは淡い水色の地に濃い青の文字。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

WHITE = "#FFFFFF"
BACKGROUND = "#F4F8FB"  # 画面の地（ごく淡い青みの白）
ACCENT = "#4FB6E6"  # 水色: 今日・進捗・ロゴ（文字には使わない）
ACCENT_SOFT = "#DDF1FB"  # 淡い水色: 主なボタン・選択中の地
ACCENT_SOFTER = "#F1F9FD"  # 今日の列
ACCENT_TEXT = "#0B5E8A"  # 濃い青: 選択中の文字・リンク
TEXT = "#1E2A36"
TEXT_SUB = "#3F4F5F"
TEXT_MUTED = "#5B6B7B"
LINE = "#DCE6EE"
LINE_SOFT = "#E8EFF5"
GRID = "#EDF2F6"
ROW = "#F7FAFC"
DANGER_TEXT = "#A21E18"

RADIUS_BAR = 10  # 作業バー
RADIUS_ROW = 14  # リストの行
RADIUS_CARD = 20  # カード


def tint(color: str, amount: float = 0.14) -> QColor:
    """カテゴリの色を白に混ぜた淡い色（作業バーの地）。"""
    c = QColor(color)
    w = 1 - amount
    return QColor(round(255 * w + c.red() * amount), round(255 * w + c.green() * amount),
                  round(255 * w + c.blue() * amount))


STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BACKGROUND}; }}
QWidget {{ color: {TEXT}; }}
QWidget#card {{ background: {WHITE}; border-radius: {RADIUS_CARD}px; }}

QTabWidget::pane {{ border: 0; background: transparent; top: 6px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: #4A5A6A; padding: 7px 18px; margin: 2px 2px 4px 0;
    border-radius: 15px; border: 1px solid transparent;
}}
QTabBar::tab:hover {{ background: #EAF2F8; }}
QTabBar::tab:selected {{ background: {WHITE}; color: {ACCENT_TEXT}; font-weight: bold; border: 1px solid {LINE}; }}

QPushButton, QToolButton {{
    background: {WHITE}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 15px;
    padding: 6px 16px; min-height: 18px;
}}
QPushButton:hover, QToolButton:hover {{ background: #F1F7FB; border-color: #BFE3F5; }}
QPushButton:pressed, QToolButton:pressed {{ background: #E3F1FA; }}
QPushButton:disabled, QToolButton:disabled {{ color: #9AA7B3; background: #F4F7FA; border-color: {LINE_SOFT}; }}
QPushButton:default {{ border-color: #9FD3EE; }}
QPushButton[accent="true"] {{ background: {ACCENT_SOFT}; border: 1px solid {ACCENT_SOFT}; color: {ACCENT_TEXT}; font-weight: bold; }}
QPushButton[accent="true"]:hover {{ background: #CDEBFA; border-color: #CDEBFA; }}
QToolButton#dateClear {{ background: transparent; border: none; border-radius: 13px; padding: 0; min-width: 0; }}
QToolButton#dateClear:hover {{ background: #E6F3FB; }}
QToolButton#dateClear:pressed {{ background: {ACCENT_SOFT}; }}
QRadioButton {{ spacing: 6px; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid #B8C7D3; border-radius: 8px; background: {WHITE}; }}
QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{ border: 1px solid #1E88C8; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #1E88C8, stop:0.5 #1E88C8, stop:0.6 {WHITE}, stop:1 {WHITE}); }}
QRadioButton::indicator:disabled {{ background: #F4F7FA; border-color: #D5DEE6; }}
QToolButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT_TEXT}; font-weight: bold; border-color: #BFE3F5; }}

QLineEdit, QPlainTextEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTimeEdit {{
    background: {WHITE}; border: 1px solid {LINE}; border-radius: 10px; padding: 5px 9px;
    selection-background-color: #BFE3F5; selection-color: {TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QTimeEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled {{ background: #F4F7FA; color: #9AA7B3; }}
QComboBox QAbstractItemView {{
    background: {WHITE}; border: 1px solid {LINE}; border-radius: 8px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {ACCENT_TEXT}; outline: 0;
}}

QTableWidget, QTableView, QListWidget, QTextBrowser {{
    background: {WHITE}; border: 1px solid {LINE_SOFT}; border-radius: {RADIUS_ROW}px;
    gridline-color: {GRID}; alternate-background-color: {ROW};
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; outline: 0;
}}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {WHITE}; color: {TEXT_MUTED}; border: 0; border-bottom: 1px solid {LINE_SOFT};
    padding: 7px 8px;
}}
QTableCornerButton::section {{ background: {WHITE}; border: 0; }}
QListWidget::item {{ padding: 7px 8px; margin: 2px 0; border-radius: 12px; }}
QListWidget::item:hover {{ background: {ROW}; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: #CFDCE6; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: #B7C8D5; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSlider::groove:horizontal {{ height: 6px; background: #E6EEF4; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {WHITE}; border: 2px solid {ACCENT}; width: 12px; height: 12px; margin: -5px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:disabled {{ border-color: #B7C8D5; }}
QSlider::sub-page:horizontal:disabled {{ background: #B7C8D5; }}

QGroupBox {{
    background: {WHITE}; border: 1px solid {LINE_SOFT}; border-radius: {RADIUS_ROW}px;
    margin-top: 16px; padding: 12px 10px 10px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {TEXT}; font-weight: bold; }}

QStatusBar {{ background: {WHITE}; border-top: 1px solid {LINE_SOFT}; }}
QStatusBar::item {{ border: 0; }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: {WHITE}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 8px; }}
QMenu {{ background: {WHITE}; border: 1px solid {LINE}; border-radius: 10px; padding: 4px; }}
QMenu::item {{ padding: 6px 20px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_TEXT}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {ACCENT_SOFT}; border-radius: 8px; }}
QCalendarWidget QToolButton {{ border: 0; background: transparent; color: {ACCENT_TEXT}; font-weight: bold; padding: 4px 8px; }}
QCalendarWidget QAbstractItemView {{ selection-background-color: {ACCENT}; selection-color: {TEXT}; border: 0; }}
"""


def _arrow_images() -> dict[str, str]:
    """▼▲の矢印の画像を作り、そのパスを返す（スタイルシートは画像ファイルでしか矢印を描けないため）。

    画像は起動のたびに一時フォルダへ描いて作る（exe に画像ファイルを同梱しなくてよいように）。
    """
    import tempfile
    from pathlib import Path

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainter, QPen, QPixmap

    folder = Path(tempfile.gettempdir()) / "worklog_canvas_theme"
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, pts, color in (("down", [(3, 5), (6, 8), (9, 5)], "#6B7A89"),
                             ("up", [(3, 7), (6, 4), (9, 7)], "#6B7A89"),
                             ("down_disabled", [(3, 5), (6, 8), (9, 5)], "#B7C3CE")):
        pm = QPixmap(24, 24)  # 2倍で描いて、高解像度の画面でもにじまないように
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(color), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPolyline([QPointF(x * 2, y * 2) for x, y in pts])
        painter.end()
        path = folder / f"{name}.png"
        pm.save(str(path), "PNG")
        out[name] = path.as_posix()
    return out


def _arrow_rules(img: dict[str, str]) -> str:
    return f"""
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: 0; background: transparent;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({img["down"]}); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled, QDateEdit::down-arrow:disabled {{ image: url({img["down_disabled"]}); }}
QSpinBox, QDoubleSpinBox, QTimeEdit {{ padding-right: 22px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: 0; background: transparent;
    margin-top: 3px; margin-right: 4px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: 0; background: transparent;
    margin-bottom: 3px; margin-right: 4px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{ image: url({img["up"]}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{ image: url({img["down"]}); width: 10px; height: 10px; }}
"""


ICON_FILE = Path(__file__).resolve().parent / "resources" / "app_icon.ico"


def app_icon():
    """アプリのアイコン（デスクワーク×カレンダー）。元絵は resources/app_icon.svg。"""
    from PySide6.QtGui import QIcon
    return QIcon(str(ICON_FILE))


def apply(app: QApplication) -> None:
    """アプリ全体に見た目とアイコンを当てる。"""
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")  # どのPCでも同じ見た目にする（スタイルシートの角丸がきれいに出る）
    try:
        arrows = _arrow_rules(_arrow_images())
    except OSError:
        arrows = ""  # 一時フォルダに書けなくても、矢印が標準のままになるだけ
    app.setStyleSheet(STYLESHEET + arrows)


def card(widget) -> None:
    """白い角丸のカードにする（QWidget に背景を描かせる）。"""
    from PySide6.QtCore import Qt
    widget.setObjectName("card")
    widget.setAttribute(Qt.WA_StyledBackground, True)
