"""チーム一覧（F-08）: 選んだ1日の、メンバーを横に並べたタイムライン（読み取り専用）と進行中タスク。"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QDate, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from ..core import aggregate as ag
from ..core import team
from ..core import timeline as tl
from ..core import timeutil as tu
from .state import AppState
from .timeline_view import GUTTER, MIN_HOUR_PX, WEEKDAYS, paint_bar
from .widgets import color_icon

MIN_COL_W = 110


class TeamCanvas(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.days: list[team.MemberDay] = []
        self.view_start, self.view_end = state.settings.view_range
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(int((self.view_end - self.view_start) / 60 * MIN_HOUR_PX))

    def set_days(self, days) -> None:
        self.days = days
        self.view_start, self.view_end = self.state.settings.view_range
        self.setMinimumWidth(GUTTER + MIN_COL_W * max(1, len(days)))
        self.update()

    def col_width(self) -> float:
        return (self.width() - GUTTER) / max(1, len(self.days))

    def col_x(self, i: int) -> float:
        return GUTTER + i * self.col_width()

    def y_of(self, m: float) -> float:
        return (m - self.view_start) * self.height() / (self.view_end - self.view_start)

    def _rect(self, i: int, s: int, e: int) -> QRectF | None:
        top, bottom = max(s, self.view_start), min(e, self.view_end)
        if bottom <= top:
            return None
        return QRectF(self.col_x(i) + 2, self.y_of(top), self.col_width() - 4, self.y_of(bottom) - self.y_of(top))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#FFFFFF"))
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        for m in range(self.view_start, self.view_end + 1, 30):
            y = self.y_of(m)
            if m % 60 == 0:
                p.setPen(QPen(QColor("#D0D0D0"), 1))
                p.drawLine(QPointF(GUTTER, y), QPointF(self.width(), y))
                if m < self.view_end:
                    p.setPen(QColor("#666666"))
                    p.drawText(QRectF(0, y + 1, GUTTER - 6, 14), Qt.AlignRight | Qt.AlignTop, f"{m // 60}:00")
            else:
                p.setPen(QPen(QColor("#EEEEEE"), 1, Qt.DashLine))
                p.drawLine(QPointF(GUTTER, y), QPointF(self.width(), y))
        p.setPen(QPen(QColor("#D0D0D0"), 1))
        for i in range(len(self.days) + 1):
            p.drawLine(QPointF(self.col_x(i), 0), QPointF(self.col_x(i), self.height()))
        p.setFont(self.font())
        for i, d in enumerate(self.days):
            if not d.member.ok:
                p.setPen(QColor("#C62828"))
                p.drawText(QRectF(self.col_x(i), 20, self.col_width(), 40), Qt.AlignHCenter | Qt.AlignTop,
                           team.LOAD_ERROR_MESSAGE)
                continue
            tasks = {t.id: t for t in d.member.repo.tasks}
            for w in d.worklogs:
                r = self._rect(i, w.start, w.end)
                if r is not None:
                    paint_bar(p, r, w, tasks, self.state, self.font())
        p.end()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        for i, d in enumerate(self.days):
            if not d.member.ok:
                continue
            tasks = {t.id: t for t in d.member.repo.tasks}
            for w in d.worklogs:
                r = self._rect(i, w.start, w.end)
                if r is not None and r.contains(pos):
                    subs = tl.sub_labels(w, tasks)
                    text = (f"{d.member.display_name}\n{tl.main_label(w, tasks)}\n"
                            f"{tu.format_hhmm(w.start)}〜{tu.format_hhmm(w.end)}（{tu.format_hours(w.duration)}）")
                    if subs:
                        text += "\n" + "\n".join(f"＋ {x}" for x in subs)
                    QToolTip.showText(ev.globalPosition().toPoint(), text, self)
                    return
        QToolTip.hideText()


class _Strip(QWidget):
    def __init__(self, canvas: TeamCanvas, footer: bool, parent=None):
        super().__init__(parent)
        self.canvas, self.footer = canvas, footer
        self.setFixedHeight(26)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#F5F5F5"))
        cw = self.canvas.col_width()
        for i, d in enumerate(self.canvas.days):
            if self.footer:
                text = (f"稼働 {tu.format_hours(d.working)}" if d.working else "—") if d.member.ok else ""
                f = QFont(self.font())
            else:
                text = d.member.display_name
                f = QFont(self.font())
                f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#333333"))
            p.drawText(QRectF(self.canvas.col_x(i), 0, cw, self.height()), Qt.AlignCenter, text)
        p.end()


class TeamTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.day = state.today()
        self.members: list[team.Member] = []
        self._loaded = False

        bar = QHBoxLayout()
        self.btn_prev, self.btn_today, self.btn_next = QPushButton("◀ 前日"), QPushButton("今日"), QPushButton("翌日 ▶")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.day_label = QLabel()
        f = self.day_label.font()
        f.setBold(True)
        self.day_label.setFont(f)
        self.btn_reload = QPushButton("更新")
        self.btn_reload.setToolTip("共有フォルダから全員のデータを読み込み直す（自動では更新しません）")
        for w in (self.btn_prev, self.btn_today, self.btn_next, self.date_edit):
            bar.addWidget(w)
        bar.addSpacing(12)
        bar.addWidget(self.day_label)
        bar.addStretch()
        bar.addWidget(QLabel("読み取り専用"))
        bar.addWidget(self.btn_reload)

        self.canvas = TeamCanvas(state)
        self.header, self.footer = _Strip(self.canvas, False), _Strip(self.canvas, True)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)
        il.addWidget(self.header)
        il.addWidget(self.canvas, 1)
        il.addWidget(self.footer)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["メンバー", "進行中のタスク", "進捗率", "完了予定日"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        cap = QLabel("メンバーごとの進行中タスク")
        cap.setStyleSheet("font-weight:bold;")
        ll.addWidget(cap)
        ll.addWidget(self.table)

        split = QSplitter(Qt.Vertical)
        split.addWidget(scroll)
        split.addWidget(lower)
        split.setSizes([480, 220])
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(split, 1)

        self.btn_prev.clicked.connect(lambda: self.set_day(self.day - _dt.timedelta(days=1)))
        self.btn_next.clicked.connect(lambda: self.set_day(self.day + _dt.timedelta(days=1)))
        self.btn_today.clicked.connect(lambda: self.set_day(self.state.today()))
        self.date_edit.dateChanged.connect(lambda q: self.set_day(_dt.date(q.year(), q.month(), q.day())))
        self.btn_reload.clicked.connect(self.reload)
        state.worklogs_changed.connect(self._own_changed)
        state.tasks_changed.connect(self._own_changed)
        state.categories_changed.connect(self.canvas.update)

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._loaded:
            self.reload()

    def _own_changed(self) -> None:
        if self._loaded and self.isVisible():
            self.refresh()

    def reload(self) -> None:
        """全メンバーを読み込み直す（「更新」ボタン）。"""
        self.members = team.load_members(self.state.folder, self.state.own_repo)
        self._loaded = True
        self.state.reload_categories()
        self.refresh()

    def set_day(self, day: _dt.date) -> None:
        self.day = day
        self.refresh()

    def refresh(self) -> None:
        d = self.day
        self.date_edit.blockSignals(True)
        self.date_edit.setDate(QDate(d.year, d.month, d.day))
        self.date_edit.blockSignals(False)
        self.day_label.setText(f"{d:%Y/%m/%d}（{WEEKDAYS[d.weekday()]}）　{len(self.members)}名")
        days = team.team_day(self.members, d)
        self.canvas.set_days(days)
        self.header.update()
        self.footer.update()
        rows = []
        for md in days:
            if not md.member.ok:
                rows.append((md.member.display_name, team.LOAD_ERROR_MESSAGE, None, "", None))
            elif not md.in_progress:
                rows.append((md.member.display_name, "（進行中のタスクはありません）", None, "", None))
            for t in md.in_progress:
                rows.append((md.member.display_name, t.name, t.progress,
                             t.planned_end.isoformat() if t.planned_end else "—", t))
        self.table.setRowCount(len(rows))
        for r, (name, task_name, progress, due, task) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            it = QTableWidgetItem(task_name)
            if task is not None:
                it.setIcon(color_icon(self.state.task_color(task)))
            elif task_name == team.LOAD_ERROR_MESSAGE:
                it.setForeground(QColor("#C62828"))
            self.table.setItem(r, 1, it)
            pr = QTableWidgetItem("" if progress is None else f"{progress}%")
            pr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 2, pr)
            due_item = QTableWidgetItem(due)
            if task is not None and task.planned_end and task.planned_end < self.state.today():
                due_item.setForeground(QColor("#E67E22"))
                due_item.setText(f"{due}（予定超過）")
            self.table.setItem(r, 3, due_item)
