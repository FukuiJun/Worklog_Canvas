"""集計画面のグラフ（QPainter で描画）。

描き方の約束:
- 棒の太さは24px以下。データ側の端は4px角丸、基準線側は角なし。
- 積み上げの段の間と隣り合う棒の間は、背景色の2pxのすき間で区切る（枠線は描かない）。
- 目盛り線は細い実線で控えめに。文字は文字色で書き、データの色は使わない。
- 凡例は2系列以上なら常に表示。値はツールチップで確認できる。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..core import aggregate as ag
from ..core import timeutil as tu

SURFACE = QColor("#FFFFFF")
GRID = QColor("#E6E6E6")
AXIS = QColor("#BDBDBD")
TEXT = QColor("#212121")
TEXT_MUTED = QColor("#666666")
GAP = 2
BAR_MAX = 24
RADIUS = 4


def _end_rounded(rect: QRectF, round_top: bool = False, round_right: bool = False) -> QPainterPath:
    """データ側の端だけ角丸にした矩形（縦棒は上、横棒は右）。"""
    path = QPainterPath()
    r = min(RADIUS, rect.width() / 2, rect.height() / 2)
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    if round_top:
        path.moveTo(x0, y1)
        path.lineTo(x0, y0 + r)
        path.quadTo(x0, y0, x0 + r, y0)
        path.lineTo(x1 - r, y0)
        path.quadTo(x1, y0, x1, y0 + r)
        path.lineTo(x1, y1)
        path.closeSubpath()
    elif round_right:
        path.moveTo(x0, y0)
        path.lineTo(x1 - r, y0)
        path.quadTo(x1, y0, x1, y0 + r)
        path.lineTo(x1, y1 - r)
        path.quadTo(x1, y1, x1 - r, y1)
        path.lineTo(x0, y1)
        path.closeSubpath()
    else:
        path.addRect(rect)
    return path


@dataclass
class _Hit:
    rect: QRectF
    text: str


class _ChartBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hits: list[_Hit] = []

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        for h in self._hits:
            if h.rect.adjusted(-2, -2, 2, 2).contains(pos):
                QToolTip.showText(ev.globalPosition().toPoint(), h.text, self)
                return
        QToolTip.hideText()

    def small_font(self) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 0.5))
        return f


class DailyStackChart(_ChartBase):
    """日別のタスク別時間（積み上げ縦棒）。各日の稼働時間を棒の上に表示する。"""

    LEFT, RIGHT, TOP, BOTTOM = 44, 12, 22, 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(260)
        self.stacks: list[ag.DayStack] = []
        self.color_of = lambda seg: "#9E9E9E"
        self.label_of = lambda seg: seg.key

    def set_data(self, stacks, color_of, label_of) -> None:
        self.stacks, self.color_of, self.label_of = stacks, color_of, label_of
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), SURFACE)
        self._hits = []
        n = len(self.stacks)
        if n == 0:
            p.end()
            return
        plot = QRectF(self.LEFT, self.TOP, self.width() - self.LEFT - self.RIGHT,
                      self.height() - self.TOP - self.BOTTOM)
        max_m = max((s.working for s in self.stacks), default=0)
        ticks = ag.nice_ticks(max_m / 60)
        top_h = ticks[-1]
        y_of = lambda hours: plot.bottom() - hours / top_h * plot.height()  # noqa: E731
        p.setFont(self.small_font())
        fm = QFontMetrics(p.font())
        for t in ticks:
            y = y_of(t)
            p.setPen(GRID if t else AXIS)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(TEXT_MUTED)
            p.drawText(QRectF(0, y - 8, self.LEFT - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{t:g}h")
        slot = plot.width() / n
        bw = min(BAR_MAX, slot * 0.6)
        label_every = max(1, int(-(-48 // slot)))  # 日付ラベルが重ならない間隔
        weekdays = "月火水木金土日"
        for i, s in enumerate(self.stacks):
            cx = plot.left() + slot * (i + 0.5)
            y = plot.bottom()
            for k, seg in enumerate(s.segments):
                h = seg.minutes / 60 / top_h * plot.height()
                top_seg = k == len(s.segments) - 1
                r = QRectF(cx - bw / 2, y - h, bw, h - (0 if top_seg else GAP) if h > GAP else h)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self.color_of(seg)))
                p.drawPath(_end_rounded(r, round_top=top_seg))
                self._hits.append(_Hit(QRectF(cx - slot / 2, y - h, slot, h),
                                       f"{s.date:%m/%d}　{self.label_of(seg)}\n{tu.format_hours(seg.minutes)}"
                                       f"（{seg.category}）"))
                y -= h
            if s.working:
                p.setPen(TEXT)
                p.drawText(QRectF(cx - slot / 2, y - 18, slot, 16), Qt.AlignHCenter | Qt.AlignBottom,
                           tu.format_hours(s.working))
            if i % label_every == 0:
                p.setPen(TEXT_MUTED)
                text = f"{s.date.month}/{s.date.day}({weekdays[s.date.weekday()]})"
                p.drawText(QRectF(cx - 40, plot.bottom() + 4, 80, fm.height() + 2), Qt.AlignHCenter | Qt.AlignTop,
                           text)
        p.end()


class TaskBarChart(_ChartBase):
    """タスク別の合計時間（横棒、降順）。単発作業は1本にまとめる。"""

    ROW = 26
    BAR = 16
    LABEL_W = 260

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple[str, int, str, int]] = []  # (表示名, 分, 色, サブ時間の分)
        self.setFixedHeight(40)

    def set_data(self, rows) -> None:
        self.rows = rows
        self.setFixedHeight(max(40, len(rows) * self.ROW + 12))
        self.update()

    def sizeHint(self):
        return QSize(600, self.height())

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), SURFACE)
        self._hits = []
        if not self.rows:
            p.end()
            return
        fm = QFontMetrics(self.font())
        max_m = max(m for _, m, _, _ in self.rows)
        value_w = 150
        x0 = self.LABEL_W + 8
        plot_w = max(40, self.width() - x0 - value_w)
        p.setPen(AXIS)
        p.drawLine(QPointF(x0, 4), QPointF(x0, len(self.rows) * self.ROW + 6))
        for i, (label, m, color, sub) in enumerate(self.rows):
            y = 6 + i * self.ROW
            p.setPen(TEXT)
            p.drawText(QRectF(0, y, self.LABEL_W, self.ROW), Qt.AlignRight | Qt.AlignVCenter,
                       fm.elidedText(label, Qt.ElideMiddle, self.LABEL_W))
            w = m / max_m * plot_w if max_m else 0
            r = QRectF(x0, y + (self.ROW - self.BAR) / 2, max(w, 1), self.BAR)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawPath(_end_rounded(r, round_right=True))
            p.setPen(TEXT)
            value = tu.format_hours(m)
            p.drawText(QRectF(r.right() + 6, y, value_w, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, value)
            if sub:
                p.setPen(TEXT_MUTED)
                p.drawText(QRectF(r.right() + 10 + fm.horizontalAdvance(value), y, value_w, self.ROW),
                           Qt.AlignLeft | Qt.AlignVCenter, f"（サブ {tu.format_hours(sub)}）")
            tip = f"{label}\nメイン時間 {tu.format_hours(m)}"
            if sub:
                tip += f"／サブ時間 {tu.format_hours(sub)}"
            self._hits.append(_Hit(QRectF(0, y, self.width(), self.ROW), tip))
        p.end()


class Legend(QWidget):
    """凡例（色の四角と名前）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[tuple[str, str]] = []
        self.setFixedHeight(22)

    def set_items(self, items: list[tuple[str, str]]) -> None:
        self.items = items
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = QFontMetrics(self.font())
        x = 44
        for name, color in self.items:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, 6, 10, 10), 2, 2)
            p.setPen(TEXT)
            p.drawText(QPointF(x + 14, 6 + fm.ascent() - 1), name)
            x += 14 + fm.horizontalAdvance(name) + 16
        p.end()


class ProgressMeter(QWidget):
    """進捗率のメーター（表のセル用）。塗りはカテゴリ色、残りは薄い灰色。"""

    def __init__(self, value: int, color: str, parent=None):
        super().__init__(parent)
        self.value, self.color = value, color
        self.setMinimumWidth(140)
        self.setToolTip(f"進捗率 {value}%")

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = QFontMetrics(self.font())
        text_w = fm.horizontalAdvance("100%") + 8
        track = QRectF(6, self.height() / 2 - 4, self.width() - text_w - 12, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E8E8E8"))
        p.drawRoundedRect(track, 4, 4)
        if self.value:
            fill = QRectF(track.left(), track.top(), track.width() * self.value / 100, track.height())
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(fill, 4, 4)
        p.setPen(TEXT)
        p.drawText(QRectF(track.right() + 6, 0, text_w, self.height()), Qt.AlignRight | Qt.AlignVCenter,
                   f"{self.value}%")
        p.end()
