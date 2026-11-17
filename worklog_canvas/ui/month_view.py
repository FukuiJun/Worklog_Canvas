"""タイムラインの月表示（Outlook の予定表の「月」のような、1か月をマス目で見る画面）。

各日のマスに、その日の作業バー・予定（予定表ファイル）・定期の予定を時刻順に並べ、入りきらない分は
「+n」にまとめる。日付の右には、その日の稼働時間（メイン時間の合計）を出す。
マスをクリックすると、その日の日表示に切り替える（記録・編集は日表示・週表示で行う）。
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..core import ics
from ..core import recurring as rc
from ..core import timeline as tl
from ..core import timeutil as tu
from . import theme
from .state import AppState

WEEKDAY_NAMES = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
HEADER_H = 30  # 曜日の見出しの高さ
DAY_LABEL_H = 30  # マスの上の日付の行
CHIP_GAP = 3
APPT_COLOR = QColor(92, 107, 192)  # 予定（タイムラインの予定バーと同じ色）
TODAY_COLOR = QColor("#1E88C8")


def _hm(minutes: int) -> str:
    """「8:30」のような短い時刻（月表示のマスは狭いので先頭の0を付けない）。"""
    return f"{minutes // 60}:{minutes % 60:02d}"


@dataclass
class Chip:
    """マスの中の1行（作業バー・予定・定期の予定）。"""
    kind: str  # "worklog" / "appointment" / "recurring"
    start: int  # 並べ替え用（終日の予定は -1）
    text: str
    tooltip: str
    color: QColor


class MonthView(QWidget):
    day_clicked = Signal(object)  # クリックしたマスの日付（datetime.date）

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.month = state.today().replace(day=1)
        self.dates: list[_dt.date] = tl.month_dates(self.month)
        self.appointments: list[ics.Appointment] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(420)
        self.setCursor(Qt.PointingHandCursor)
        self._layout: list[tuple[_dt.date, QRectF, list[tuple[QRectF, Chip | None, int]]]] = []

    # --- 表示する月 ---
    def set_month(self, anchor: _dt.date) -> None:
        self.month = anchor.replace(day=1)
        self.dates = tl.month_dates(self.month)
        self.update()

    @property
    def weeks(self) -> int:
        return len(self.dates) // 7

    # --- マスの中身 ---
    def chips_for(self, day: _dt.date) -> list[Chip]:
        tasks = self.state.tasks_by_id()
        out: list[Chip] = []
        bars = [w for w in self.state.repo.worklogs if w.date == day]
        for w in bars:
            name = tl.main_label(w, tasks)
            span = f"{tu.format_hhmm(w.start)}〜{tu.format_hhmm(w.end)}"
            tip = f"{name}\n{span}（{tu.format_hours(w.duration)}）"
            subs = tl.sub_labels(w, tasks)
            if subs:
                tip += "\n" + "\n".join(f"＋ {s}" for s in subs)
            out.append(Chip("worklog", w.start, f"{_hm(w.start)} {name}", tip,
                            QColor(self.state.worklog_color(w, tasks))))
        if not self.state.viewing_other:  # 予定表ファイルと定期の予定は自分のもの
            for a in self.appointments:
                if day not in a.days():
                    continue
                span = a.span_on(day)
                if span is None:
                    out.append(Chip("appointment", -1, f"終日 {a.title}", f"{a.title}（終日）", APPT_COLOR))
                else:
                    t = f"{tu.format_hhmm(span[0])}〜{tu.format_hhmm(span[1])}"
                    out.append(Chip("appointment", span[0], f"{_hm(span[0])} {a.title}",
                                    f"{a.title}\n{t}（予定）", APPT_COLOR))
            for o in rc.occurrences(self.state.repo.recurring, [day], bars):
                name = tl.item_label(o.item.kind, o.item.task_id, o.item.title, tasks)
                out.append(Chip("recurring", o.start, f"{_hm(o.start)} {name}",
                                f"{name}\n{o.item.describe()}（定期の予定）",
                                QColor(self.state.sub_color(o.item.kind, o.item.task_id, tasks))))
        order = {"appointment": 0, "worklog": 1, "recurring": 2}
        out.sort(key=lambda c: (c.start, order[c.kind]))
        return out

    def day_minutes(self, day: _dt.date) -> int:
        return sum(w.duration for w in self.state.repo.worklogs if w.date == day)

    # --- 配置 ---
    def cell_rect(self, i: int) -> QRectF:
        w = self.width() / 7
        h = (self.height() - HEADER_H) / max(self.weeks, 1)
        row, col = divmod(i, 7)
        return QRectF(col * w, HEADER_H + row * h, w, h)

    def date_at(self, pos: QPointF) -> _dt.date | None:
        for i, d in enumerate(self.dates):
            if self.cell_rect(i).contains(pos):
                return d
        return None

    def _build_layout(self, fm: QFontMetrics) -> None:
        """各マスに入る行（チップ）の位置を決める。入りきらなければ最後の行を「+n」にする。"""
        self._layout = []
        line_h = fm.height() + 8
        for i, d in enumerate(self.dates):
            cell = self.cell_rect(i)
            chips = self.chips_for(d)
            area = cell.adjusted(6, DAY_LABEL_H, -6, -6)
            fit = max(0, int((area.height() + CHIP_GAP) // (line_h + CHIP_GAP)))
            rows: list[tuple[QRectF, Chip | None, int]] = []
            show = chips if len(chips) <= fit else chips[:max(fit - 1, 0)]
            y = area.top()
            for c in show:
                rows.append((QRectF(area.left(), y, area.width(), line_h), c, 0))
                y += line_h + CHIP_GAP
            rest = len(chips) - len(show)
            if rest > 0 and fit > 0:
                rows.append((QRectF(area.left(), y, area.width(), line_h), None, rest))
            self._layout.append((d, cell, rows))

    def chip_at(self, pos: QPointF) -> Chip | None:
        for _d, _cell, rows in self._layout:
            for r, chip, _rest in rows:
                if chip is not None and r.contains(pos):
                    return chip
        return None

    # --- 描画 ---
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.WHITE))
        font = QFont(self.font())
        fm = QFontMetrics(font)
        bold = QFont(font)
        bold.setBold(True)
        today = self.state.today()
        # 曜日の見出し
        w = self.width() / 7
        p.setPen(QColor(theme.TEXT_MUTED))
        for c, name in enumerate(WEEKDAY_NAMES):
            p.drawText(QRectF(c * w + 8, 0, w - 8, HEADER_H), Qt.AlignVCenter | Qt.AlignLeft, name)
        self._build_layout(fm)
        for d, cell, rows in self._layout:
            in_month = d.month == self.month.month
            weekend = d.weekday() >= 5
            if not in_month:
                p.fillRect(cell, QColor("#F7F9FB"))
            elif weekend:
                p.fillRect(cell, QColor("#FBFCFD"))
            # 枠線
            p.setPen(QPen(QColor(theme.LINE_SOFT), 1))
            p.drawLine(cell.topLeft(), cell.topRight())
            if cell.left() > 0:
                p.drawLine(cell.topLeft(), cell.bottomLeft())
            # 日付（月の初日は「11月1日」）
            label = f"{d.month}月{d.day}日" if d.day == 1 else str(d.day)
            num_rect = QRectF(cell.left() + 8, cell.top() + 4, cell.width() - 16, DAY_LABEL_H - 6)
            if d == today:
                p.setFont(bold)
                tw = QFontMetrics(bold).horizontalAdvance(label)
                pill = QRectF(num_rect.left() - 4, num_rect.top() + 1, max(tw + 12, num_rect.height() - 2),
                              num_rect.height() - 2)
                p.setPen(Qt.NoPen)
                p.setBrush(TODAY_COLOR)
                p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
                p.setPen(QColor(theme.WHITE))
                p.drawText(pill, Qt.AlignCenter, label)
                p.setFont(font)
            else:
                p.setPen(QColor(theme.TEXT if in_month else "#9AA7B3"))
                p.drawText(num_rect, Qt.AlignVCenter | Qt.AlignLeft, label)
            minutes = self.day_minutes(d)
            if minutes:
                p.setPen(QColor(theme.TEXT_MUTED))
                p.drawText(num_rect, Qt.AlignVCenter | Qt.AlignRight, tu.format_hours(minutes))
            for r, chip, rest in rows:
                self._paint_chip(p, r, chip, rest, fm, faded=not in_month)
        p.end()

    def _paint_chip(self, p: QPainter, r: QRectF, chip: Chip | None, rest: int, fm: QFontMetrics,
                    faded: bool) -> None:
        if chip is None:  # 入りきらない分
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#EEF2F5"))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor(theme.TEXT_SUB))
            p.drawText(r, Qt.AlignCenter, f"+{rest}")
            return
        if chip.kind == "worklog":
            fill = theme.tint(chip.color.name())
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r, 6, 6)
            p.setBrush(chip.color)
            p.drawRoundedRect(QRectF(r.left(), r.top(), 4, r.height()), 2, 2)
        else:  # 予定・定期の予定は点線の枠（作業バーではないことが分かるように）
            p.setBrush(QColor(theme.WHITE))
            p.setPen(QPen(chip.color if chip.kind == "appointment" else QColor(theme.ACCENT), 1, Qt.DashLine))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor(theme.TEXT_MUTED if faded or chip.kind != "worklog" else theme.TEXT))
        text_r = r.adjusted(9, 0, -4, 0)
        p.drawText(text_r, Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(chip.text, Qt.ElideRight, int(text_r.width())))

    # --- 操作 ---
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            d = self.date_at(ev.position())
            if d is not None:
                self.day_clicked.emit(d)
                return
        super().mousePressEvent(ev)

    def event(self, ev):
        if ev.type() == ev.Type.ToolTip:
            chip = self.chip_at(QPointF(ev.pos()))
            if chip is not None:
                QToolTip.showText(ev.globalPos(), chip.tooltip, self)
            else:
                d = self.date_at(QPointF(ev.pos()))
                QToolTip.showText(ev.globalPos(), f"{d:%Y/%m/%d}　クリックでこの日を表示" if d else "", self)
            return True
        return super().event(ev)

