"""タイムライン画面（F-02）。"""
from __future__ import annotations

import datetime as _dt

from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QCursor, QDrag, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMenu,
    QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from ..core import aggregate as ag
from ..core import applog
from ..core import ics
from ..core import timeline as tl
from ..core import timeutil as tu
from ..core.models import KIND_ONEOFF, KIND_TASK, SubItem, ValidationError, Worklog
from ..core.overlap import OVERLAP_MESSAGE, OverlapError, find_overlaps
from .entry_popup import EntryPopup
from .state import AppState
from . import theme
from .widgets import color_icon, text_color_for
from .worklog_dialog import WorklogDialog

TASK_MIME = "application/x-worklog-canvas-task"
WEEKDAYS = "月火水木金土日"
GUTTER = 52  # 時刻ラベルの幅
MIN_HOUR_PX = 40
EDGE_PX = 6  # 上端・下端の伸縮つまみの高さ
DRAG_THRESHOLD = 4
SUB_STRIP_W = 6
APPT_COLOR = QColor(92, 107, 192)  # 予定バー（斜線模様の半透明）
APPT_STRIP_W = 5  # 作業バーの上にも見える、予定の目印（列の左端）
log = applog.get()


def ics_path_from(mime) -> str | None:
    """ドラッグされたものが .ics ファイルならそのパス。"""
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".ics"):
                return url.toLocalFile()
    return None


def day_label(d: _dt.date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def paint_bar(p: QPainter, r: QRectF, w: Worklog, tasks, state: AppState, font: QFont, selected=False, drop=False,
          faded=False) -> None:
    """作業バーを1本描く（タイムラインとチーム一覧で共用）。"""
    color = QColor(state.worklog_color(w, tasks))  # カテゴリの色（点に使う）
    fill = theme.tint(color.name())  # 地はカテゴリの淡い色
    if faded:
        fill.setAlpha(110)
    r = r.adjusted(1, 1.5, -1, -1.5)  # 隣のバーとの間に白いすき間
    pen = Qt.NoPen
    if selected:
        pen = QPen(QColor(theme.ACCENT_TEXT), 2)
    if drop:
        pen = QPen(QColor(theme.ACCENT), 2.5, Qt.DashLine)
    p.setPen(pen)
    p.setBrush(fill)
    p.drawRoundedRect(r, theme.RADIUS_BAR, theme.RADIUS_BAR)
    # サブタスクの色（右端の小さな丸い帯）
    p.setPen(Qt.NoPen)
    for k, s in enumerate(w.subs):
        sx = r.right() - 5 - (k + 1) * (SUB_STRIP_W + 2)
        if sx <= r.left() + 24 or r.height() < 12:
            break
        p.setBrush(QColor(state.sub_color(s.kind, s.task_id, tasks)))
        p.drawRoundedRect(QRectF(sx, r.top() + 5, SUB_STRIP_W, r.height() - 10), 3, 3)
    if faded:
        return
    # カテゴリの点
    dot = 8 if r.height() >= 14 else 6
    p.setBrush(color)
    fm0 = QFontMetrics(p.font())
    dot_y = r.top() + 2 + (min(fm0.height(), r.height() - 4) - dot) / 2 if r.height() >= fm0.height() * 2 + 4 \
        else r.center().y() - dot / 2
    p.drawEllipse(QRectF(r.left() + 7, dot_y, dot, dot))
    # 文字
    left_pad = 7 + dot + 5
    text_w = r.width() - left_pad - 6 - len(w.subs) * (SUB_STRIP_W + 2)
    if text_w < 12 or r.height() < 10:
        return
    p.setPen(QColor(theme.TEXT))
    fm = QFontMetrics(p.font())
    lh = fm.height()
    lines = []
    name = tl.main_label(w, tasks)
    dur = tu.format_hours(w.duration)
    lines.append((f"{name}", True))
    lines.append((f"{dur}  {tu.format_hhmm(w.start)}〜{tu.format_hhmm(w.end)}", False))
    for sub in tl.sub_labels(w, tasks):
        lines.append((f"＋ {sub}", False))
    y = r.top() + 2
    bold = QFont(p.font())
    bold.setBold(True)
    if r.height() < lh * 2 + 4:  # 低いバーは1行にまとめる
        one = f"{name} {dur}" + (f"（＋{len(w.subs)}）" if w.subs else "")
        p.drawText(QRectF(r.left() + left_pad, r.top(), text_w, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(one, Qt.ElideRight, int(text_w)))
        return
    fit = int((r.height() - 2) // lh)
    if len(lines) > fit >= 3:  # 入りきらないサブタスクは件数で示す
        hidden = len(lines) - (fit - 1)
        lines = lines[:fit - 1] + [(f"＋ 他 {hidden} 件", False)]
    for text, is_bold in lines:
        if y + lh > r.bottom():
            break
        p.setFont(bold if is_bold else font)
        p.setPen(QColor(theme.TEXT if is_bold else theme.TEXT_SUB))
        fmx = QFontMetrics(p.font())
        p.drawText(QRectF(r.left() + left_pad, y, text_w, lh), Qt.AlignLeft | Qt.AlignVCenter,
                   fmx.elidedText(text, Qt.ElideRight, int(text_w)))
        y += lh
    p.setFont(font)


# ===========================================================================
class TimelineCanvas(QWidget):
    """日の列と作業バーを描き、マウス操作を受け付ける。"""

    geometry_changed = Signal()
    selection_changed = Signal()
    ics_dropped = Signal(str)

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.dates: list[_dt.date] = [state.today()]
        self.view_start, self.view_end = state.settings.view_range
        self.selected_id: str | None = None
        self._drag: dict | None = None  # 進行中のドラッグ
        self._ghost: tuple[int, int, int] | None = None  # (列, 開始分, 終了分) 作成中の範囲
        self._drop_target: str | None = None  # ドロップ先としてハイライトする作業バー
        self.appointments: list[ics.Appointment] = []  # 表示中の日にかかる予定（予定表ファイルから）
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._update_min_height()
        state.settings_changed.connect(self.apply_settings)
        state.repo_switched.connect(self._repo_switched)

    def apply_settings(self) -> None:
        self.view_start, self.view_end = self.state.settings.view_range
        self._update_min_height()
        self.update()
        self.geometry_changed.emit()

    def _repo_switched(self) -> None:
        self.selected_id = None
        self._drag = self._ghost = None
        self.update()

    # --- 座標 ---------------------------------------------------------------
    def _update_min_height(self) -> None:
        hours = (self.view_end - self.view_start) / 60
        self.setMinimumHeight(int(hours * MIN_HOUR_PX))

    def set_dates(self, dates: list[_dt.date]) -> None:
        self.dates = dates
        self.update()
        self.geometry_changed.emit()

    @property
    def ppm(self) -> float:
        return self.height() / (self.view_end - self.view_start)

    def col_width(self) -> float:
        return (self.width() - GUTTER) / max(1, len(self.dates))

    def col_x(self, i: int) -> float:
        return GUTTER + i * self.col_width()

    def column_at(self, x: float, clamp: bool = False) -> int | None:
        i = int((x - GUTTER) // self.col_width()) if x >= GUTTER else -1
        if clamp:
            return max(0, min(len(self.dates) - 1, i))
        return i if 0 <= i < len(self.dates) else None

    def minute_at(self, y: float) -> float:
        return self.view_start + y / self.ppm

    def y_of(self, minutes: float) -> float:
        return (minutes - self.view_start) * self.ppm

    def bar_rect(self, w: Worklog, col: int | None = None) -> QRectF | None:
        if col is None:
            if w.date not in self.dates:
                return None
            col = self.dates.index(w.date)
        top, bottom = max(w.start, self.view_start), min(w.end, self.view_end)
        if bottom <= top:
            return None
        x = self.col_x(col) + 2
        return QRectF(x, self.y_of(top), self.col_width() - 4, self.y_of(bottom) - self.y_of(top))

    def visible_worklogs(self) -> list[Worklog]:
        ds = set(self.dates)
        return [w for w in self.state.repo.worklogs if w.date in ds]

    def hit(self, pos: QPointF) -> tuple[Worklog, str] | None:
        """pos にある作業バーと、つかんだ場所（"top" / "bottom" / "body"）。"""
        for w in self.visible_worklogs():
            r = self.bar_rect(w)
            if r is not None and r.contains(pos):
                edge = min(EDGE_PX, r.height() / 4)
                if pos.y() - r.top() <= edge and w.start >= self.view_start:
                    return w, "top"
                if r.bottom() - pos.y() <= edge and w.end <= self.view_end:
                    return w, "bottom"
                return w, "body"
        return None

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.geometry_changed.emit()

    # --- 予定バー（F-05） ---
    def show_appointments(self) -> bool:
        return not self.state.viewing_other  # 予定表ファイルは自分のもの。他メンバーの閲覧中は出さない

    def appointment_rects(self):
        """(予定, 日付, 矩形) の一覧。終日の予定は見出しに出すので含めない。"""
        if not self.show_appointments():
            return []
        out = []
        for col, d in enumerate(self.dates):
            for a in self.appointments:
                span = a.span_on(d)
                if span is None:
                    continue
                top, bottom = max(span[0], self.view_start), min(span[1], self.view_end)
                if bottom <= top:
                    continue
                out.append((a, d, QRectF(self.col_x(col) + 1, self.y_of(top), self.col_width() - 2,
                                         self.y_of(bottom) - self.y_of(top))))
        return out

    def appointment_at(self, pos: QPointF):
        for a, d, r in self.appointment_rects():
            if r.contains(pos):
                return a, d
        return None

    def all_day_on(self, d: _dt.date) -> list[ics.Appointment]:
        if not self.show_appointments():
            return []
        return [a for a in self.appointments if a.all_day and d in a.days()]

    def _paint_appointments(self, p: QPainter, strips_only: bool = False) -> None:
        for a, d, r in self.appointment_rects():
            if strips_only:  # 作業バーの上にも見える目印（白地に斜線。どの色のバーの上でも見える）
                strip = QRectF(r.left() + 1, r.top() + 1, APPT_STRIP_W, r.height() - 2)
                p.fillRect(strip, QColor("#FFFFFF"))
                p.fillRect(strip, QBrush(APPT_COLOR.darker(130), Qt.BDiagPattern))
                p.setPen(QPen(APPT_COLOR.darker(130), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRect(strip)
                continue
            fill = QColor(APPT_COLOR)
            fill.setAlpha(28)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRect(r)
            hatch = QColor(APPT_COLOR)
            hatch.setAlpha(110)
            p.setBrush(QBrush(hatch, Qt.BDiagPattern))
            p.drawRect(r)
            p.setPen(QPen(APPT_COLOR, 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            if r.height() >= 12:
                p.setPen(QColor("#283593"))
                fm = QFontMetrics(p.font())
                text = f"{a.title}  {a.start:%H:%M}〜{a.end:%H:%M}"
                p.drawText(r.adjusted(APPT_STRIP_W + 3, 1, -3, 0), Qt.AlignLeft | Qt.AlignTop,
                           fm.elidedText(text, Qt.ElideRight, int(r.width() - APPT_STRIP_W - 6)))

    def convert_appointment(self, a: ics.Appointment, d: _dt.date) -> bool:
        """予定バーを作業バーにする（取込元=Outlook、単発作業、タイトル=件名）。"""
        try:
            w = ics.to_worklog(a, d)
        except ValueError as e:
            self._error(str(e))
            return False
        if self._run(self.state.editor.add, w, "作業バーにする"):
            self.selected_id = self.state.repo.worklogs[-1].id
            self.update()
            return True
        return False

    # --- 描画 ---------------------------------------------------------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.WHITE))
        today = self.state.today()
        cw = self.col_width()
        for i, d in enumerate(self.dates):
            x = self.col_x(i)
            if d == today:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.ACCENT_SOFTER))
                p.drawRoundedRect(QRectF(x + 1, 0, cw - 2, self.height()), theme.RADIUS_ROW, theme.RADIUS_ROW)
            elif d.weekday() >= 5:
                p.fillRect(QRectF(x, 0, cw, self.height()), QColor("#FAFBFC"))
        # 時刻の線
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        for m in range(self.view_start, self.view_end + 1, 30):
            y = self.y_of(m)
            if m % 60 == 0:
                p.setPen(QPen(QColor(theme.GRID), 1))
                p.drawLine(QPointF(GUTTER, y), QPointF(self.width(), y))
                if m < self.view_end:
                    p.setPen(QColor("#6B7A89"))
                    p.drawText(QRectF(0, y + 1, GUTTER - 6, 14), Qt.AlignRight | Qt.AlignTop,
                               f"{m // 60}:00")
            else:
                p.setPen(QPen(QColor("#F3F6F9"), 1, Qt.DashLine))
                p.drawLine(QPointF(GUTTER, y), QPointF(self.width(), y))
        p.setPen(QPen(QColor(theme.GRID), 1))
        for i in range(len(self.dates) + 1):
            x = self.col_x(i)
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        # 予定バー（作業バーの下）
        p.setFont(self.font())
        self._paint_appointments(p)
        self._paint_occurrences(p)
        # 作業バー
        tasks = self.state.tasks_by_id()
        p.setFont(self.font())
        dragging_id = self._drag["orig"].id if self._drag and self._drag.get("active") and \
            self._drag["mode"] != "create" else None
        for w in self.visible_worklogs():
            if w.id == dragging_id:
                self._paint_bar(p, w, tasks, faded=True)
            else:
                self._paint_bar(p, w, tasks)
        if self._drag and self._drag.get("active") and self._drag.get("preview") is not None:
            self._paint_bar(p, self._drag["preview"], tasks, preview=True)
        self._paint_appointments(p, strips_only=True)
        if self._ghost:
            col, s, e = self._ghost
            r = QRectF(self.col_x(col) + 2, self.y_of(s), cw - 4, self.y_of(e) - self.y_of(s))
            p.setPen(QPen(QColor(theme.ACCENT), 1.5, Qt.DashLine))
            p.setBrush(QColor(79, 182, 230, 45))
            p.drawRoundedRect(r, theme.RADIUS_BAR, theme.RADIUS_BAR)
            p.setPen(QColor(theme.ACCENT_TEXT))
            p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop,
                       f"{tu.format_hhmm(s)}〜{tu.format_hhmm(e)}  {tu.format_hours(e - s)}")
        p.end()

    def _paint_bar(self, p: QPainter, w: Worklog, tasks, faded=False, preview=False) -> None:
        r = self.bar_rect(w)
        if r is None:
            return
        paint_bar(p, r, w, tasks, self.state, self.font(), selected=(w.id == self.selected_id or preview),
                  drop=(w.id == self._drop_target), faded=faded)

    # --- 通知 ---------------------------------------------------------------
    def _error(self, message: str) -> None:
        QToolTip.showText(QCursor.pos(), message, self)
        self.state.error.emit(message)

    def _run(self, fn, *args) -> bool:
        if self.state.readonly:
            self._error("閲覧モードでは編集できません")
            return False
        try:
            fn(*args)
        except (OverlapError, ValidationError) as e:
            self._error(str(e))
            return False
        except OSError as e:
            self._error(f"保存できませんでした: {e}")
            return False
        self.state.worklogs_changed.emit()
        return True

    # --- マウス ---------------------------------------------------------------
    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)
        self.setFocus()
        pos = ev.position()
        h = self.hit(pos)
        if h:
            w, zone = h
            self.selected_id = w.id
            self.selection_changed.emit()
            if not self.state.readonly:
                self._drag = {"mode": {"top": "top", "bottom": "bottom"}.get(zone, "move"), "orig": w,
                              "press": pos, "offset": self.minute_at(pos.y()) - w.start, "active": False,
                              "preview": None}
        else:
            if self.selected_id:
                self.selected_id = None
                self.selection_changed.emit()
            col = self.column_at(pos.x())
            if col is not None and not self.state.readonly:
                self._drag = {"mode": "create", "col": col, "press": pos,
                              "anchor": self.minute_at(pos.y()), "active": False}
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if not self._drag:
            self._update_cursor(pos)
            if self.hit(pos) is None:
                hit = self.appointment_at(pos)
                if hit:
                    a = hit[0]
                    QToolTip.showText(ev.globalPosition().toPoint(),
                                      f"予定：{a.title}\n{a.start:%m/%d %H:%M}〜{a.end:%H:%M}\n"
                                      "右クリック →「作業バーにする」", self)
            return
        d = self._drag
        if not d["active"]:
            if (pos - d["press"]).manhattanLength() < DRAG_THRESHOLD:
                return
            d["active"] = True
        m = self.minute_at(max(0.0, min(pos.y(), self.height())))
        if d["mode"] == "create":
            rng = tl.create_range(d["anchor"], m)
            self._ghost = (d["col"], *rng) if rng else None
        elif d["mode"] == "move":
            col = self.column_at(pos.x(), clamp=True)
            d["preview"] = tl.moved(d["orig"], self.dates[col], m - d["offset"])
        elif d["mode"] == "top":
            d["preview"] = tl.resized_top(d["orig"], m)
        elif d["mode"] == "bottom":
            d["preview"] = tl.resized_bottom(d["orig"], m)
        if d.get("preview") is not None:
            pv = d["preview"]
            QToolTip.showText(ev.globalPosition().toPoint(),
                              f"{tu.format_hhmm(pv.start)}〜{tu.format_hhmm(pv.end)}（{tu.format_hours(pv.duration)}）",
                              self)
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton or not self._drag:
            return super().mouseReleaseEvent(ev)
        d, self._drag = self._drag, None
        if not d["active"]:
            self.update()
            return
        if d["mode"] == "create":
            ghost = self._ghost
            if ghost:
                self._create_from_ghost(ghost, ev.globalPosition().toPoint())
            self._ghost = None
        else:
            new = d.get("preview")
            o = d["orig"]
            if new is not None and (new.date, new.start, new.end) != (o.date, o.start, o.end):
                label = "移動" if d["mode"] == "move" else "伸縮"
                self._run(self.state.editor.update, new, label)
        self.update()

    def _update_cursor(self, pos: QPointF) -> None:
        h = self.hit(pos)
        if h and not self.state.readonly:
            self.setCursor(Qt.SizeVerCursor if h[1] in ("top", "bottom") else Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def _day_bars(self, date: _dt.date, exclude: str | None = None) -> list[Worklog]:
        return [w for w in self.state.repo.worklogs_on(date) if w.id != exclude]

    def _create_from_ghost(self, ghost, global_pos: QPoint) -> None:
        col, s, e = ghost
        date = self.dates[col]
        if find_overlaps(s, e, [(w.id, w.start, w.end) for w in self._day_bars(date)]):
            self._error(OVERLAP_MESSAGE)  # Q-13
            return
        self.update()
        popup = EntryPopup(self.state.repo.tasks, self.state.task_color, s, e, self)
        popup.move(self._popup_pos(global_pos, popup.sizeHint()))
        if popup.exec() and popup.result_value:
            r = popup.result_value
            w = Worklog("", date, s, e, kind=r.kind, task_id=r.task_id, title=r.title)
            if self._run(self.state.editor.add, w, "作成"):
                self.selected_id = self.state.editor.repo.worklogs[-1].id

    def _popup_pos(self, global_pos: QPoint, size: QSize) -> QPoint:
        screen = self.screen().availableGeometry() if self.screen() else None
        x, y = global_pos.x() + 12, global_pos.y() - 20
        if screen is not None:
            x = min(x, screen.right() - size.width())
            y = min(max(y, screen.top()), screen.bottom() - size.height())
        return QPoint(x, y)

    def mouseDoubleClickEvent(self, ev):
        h = self.hit(ev.position())
        if h and not self.state.readonly:
            self.open_editor(h[0].id)

    def open_editor(self, worklog_id: str) -> None:
        w = self.state.repo.get_worklog(worklog_id)
        dlg = WorklogDialog(self.state, w, self)
        dlg.exec()
        self.update()

    def contextMenuEvent(self, ev):
        menu = self.build_context_menu(QPointF(ev.pos()))
        if menu is not None:
            menu.exec(ev.globalPos())

    def build_context_menu(self, pos: QPointF) -> QMenu | None:
        """右クリックのメニュー。作業バー・定期の予定・Outlookの予定・空き時間で中身が変わる。"""
        if self.state.readonly:
            return None
        menu = QMenu(self)

        def act(text, fn, enabled=True, name=None):
            a = QAction(text, menu)
            a.setEnabled(enabled)
            a.triggered.connect(fn)
            if name:
                a.setObjectName(name)
            menu.addAction(a)
            return a

        h = self.hit(pos)
        if h:  # 作業バー
            w = h[0]
            self.selected_id = w.id
            self.update()
            act("編集…", lambda: self.open_editor(w.id), name="edit")
            act("削除", self.delete_selected, name="delete")
            return menu
        occ = self.occurrence_at(pos)
        if occ:  # 定期の予定
            act("作業バーにする", lambda: self.confirm_occurrence(occ), name="confirm")
            act("表示中の定期の予定をまとめて記録…", self.confirm_all_occurrences, name="confirm_all")
            menu.addSeparator()
            act("この定期タスクを編集…", lambda: self.edit_recurring(occ.item.id), name="edit_recurring")
            act("この定期タスクを削除…", lambda: self.delete_recurring(occ.item.id), name="delete_recurring")
            return menu
        appt = self.appointment_at(pos)
        if appt:  # Outlookの予定
            act("作業バーにする", lambda: self.convert_appointment(*appt), name="convert")
            menu.addSeparator()
        col = self.column_at(pos.x())
        if col is None:
            return menu if menu.actions() else None
        date = self.dates[col]
        res = tl.resolve_drop(self._day_bars(date), self.minute_at(pos.y()))
        can = isinstance(res, tl.DropCreate)
        s, e = (res.start, res.end) if can else (0, 0)
        when = f"{date.month}/{date.day} {tu.format_hhmm(s)}〜{tu.format_hhmm(e)}" if can else "15分以上の空きがありません"
        title = QAction(f"ここに追加（{when}）", menu)
        title.setEnabled(False)
        menu.addAction(title)
        # 既存タスク（未完了のタスクから選ぶ）
        sub = menu.addMenu("既存タスク")
        sub.setObjectName("existing")
        sub.setEnabled(can)
        tasks = tl.sort_open_tasks(self.state.repo.tasks)
        for t in tasks:
            a = QAction(color_icon(self.state.task_color(t)), t.name, sub)
            a.setData(t.id)
            a.triggered.connect(lambda _c=False, tid=t.id: self.add_task_bar(tid, date, s, e))
            sub.addAction(a)
        if not tasks:
            none = QAction("（未完了のタスクがありません）", sub)
            none.setEnabled(False)
            sub.addAction(none)
        act("一時タスク（単発作業）…", lambda: self.add_oneoff_bar(date, s, e), can, name="oneoff")
        act("新しいタスクを作って追加…", lambda: self.add_new_task_bar(date, s, e), can, name="new_task")
        menu.addSeparator()
        act("定期タスクとして登録…", lambda: self.register_recurring(date, s, e or s + 60), True, name="recurring")
        return menu

    # --- 右クリックからの追加 ---
    def add_task_bar(self, task_id: str, date: _dt.date, s: int, e: int) -> bool:
        w = Worklog("", date, s, e, kind=KIND_TASK, task_id=task_id)
        if self._run(self.state.editor.add, w, "作成"):
            self.selected_id = self.state.repo.worklogs[-1].id
            self.update()
            return True
        return False

    def add_oneoff_bar(self, date: _dt.date, s: int, e: int) -> bool:
        title, ok = QInputDialog.getText(self, "一時タスク（単発作業）",
                                         f"{date.month}/{date.day} {tu.format_hhmm(s)}〜{tu.format_hhmm(e)} に記録する作業のタイトル")
        title = (title or "").strip()
        if not ok or not title:
            return False
        w = Worklog("", date, s, e, kind=KIND_ONEOFF, title=title)
        if self._run(self.state.editor.add, w, "作成"):
            self.selected_id = self.state.repo.worklogs[-1].id
            self.update()
            return True
        return False

    def add_new_task_bar(self, date: _dt.date, s: int, e: int) -> bool:
        from .task_dialog import TaskDialog
        dlg = TaskDialog(self.state, None, self)
        dlg.setWindowTitle("新しいタスクを作って追加")
        if not dlg.exec() or dlg.saved is None:
            return False
        return self.add_task_bar(dlg.saved.id, date, s, e)

    def register_recurring(self, date: _dt.date, s: int, e: int) -> bool:
        from ..core import recurring as rc
        from .recurring_dialog import RecurringDialog
        initial = rc.RecurringItem(id="", start=s, end=min(e, tu.DAY_MINUTES), pattern=rc.WEEKLY,
                                   weekdays=[date.weekday()], start_date=date)
        return bool(RecurringDialog(self.state, None, self, initial=initial).exec())

    def edit_recurring(self, rid: str) -> bool:
        from .recurring_dialog import RecurringDialog
        return bool(RecurringDialog(self.state, self.state.repo.get_recurring(rid), self).exec())

    def delete_recurring(self, rid: str) -> bool:
        """定期の予定（繰り返しの時間帯）を削除する。記録済みの作業バーは消さない。"""
        from .recurring_dialog import item_label
        it = self.state.repo.get_recurring(rid)
        if QMessageBox.question(self, "定期タスクの削除",
                                f"「{item_label(self.state, it)}（{it.describe()}）」の繰り返しを削除しますか？\n"
                                "記録済みの作業バーは消えません。") != QMessageBox.Yes:
            return False
        self.state.repo.delete_recurring(rid)
        self.state.worklogs_changed.emit()
        return True

    # --- 定期の予定（F-09） ---
    def occurrences(self):
        from ..core import recurring as rc
        if self.state.viewing_other or not self.state.repo.recurring:
            return []  # 他メンバーの閲覧中は出さない
        return rc.occurrences(self.state.repo.recurring, self.dates, self.visible_worklogs())

    def occurrence_rects(self):
        out = []
        for o in self.occurrences():
            top, bottom = max(o.start, self.view_start), min(o.end, self.view_end)
            if bottom <= top:
                continue
            col = self.dates.index(o.date)
            out.append((o, QRectF(self.col_x(col) + 2, self.y_of(top) + 1.5, self.col_width() - 4,
                                  self.y_of(bottom) - self.y_of(top) - 3)))
        return out

    def occurrence_at(self, pos: QPointF):
        for o, r in self.occurrence_rects():
            if r.contains(pos):
                return o
        return None

    def _paint_occurrences(self, p: QPainter) -> None:
        tasks = self.state.tasks_by_id()
        for o, r in self.occurrence_rects():
            it = o.item
            p.setPen(QPen(QColor(theme.ACCENT), 1.4, Qt.DashLine))
            p.setBrush(QColor(theme.ACCENT_SOFTER))
            p.drawRoundedRect(r, theme.RADIUS_BAR, theme.RADIUS_BAR)
            if r.height() < 10:
                continue
            p.setPen(QColor(theme.ACCENT_TEXT))
            fm = QFontMetrics(p.font())
            name = tl.item_label(it.kind, it.task_id, it.title, tasks)
            text = f"定期　{name}　{tu.format_hhmm(it.start)}〜{tu.format_hhmm(it.end)}"
            p.drawText(r.adjusted(8, 2, -6, 0), Qt.AlignLeft | Qt.AlignTop,
                       fm.elidedText(text, Qt.ElideRight, int(r.width() - 14)))

    def confirm_occurrence(self, occ) -> bool:
        if self._run(self.state.editor.add, occ.item.to_worklog(occ.date), "定期の予定を記録"):
            self.selected_id = self.state.repo.worklogs[-1].id
            self.update()
            return True
        return False

    def confirm_all_occurrences(self, ask: bool = True) -> int:
        occ = self.occurrences()
        if not occ:
            self.state.info.emit("記録していない定期の予定はありません")
            return 0
        if ask and QMessageBox.question(self, "定期の予定をまとめて記録",
                                        f"表示中の定期の予定 {len(occ)} 件を、作業バーとして記録しますか？\n"
                                        "（休んだ日の分は、記録後に削除してください）") != QMessageBox.Yes:
            return 0
        n = 0
        for o in occ:
            try:
                self.state.editor.add(o.item.to_worklog(o.date), "定期の予定を記録")
                n += 1
            except (OverlapError, ValidationError, KeyError):
                continue
        self.state.worklogs_changed.emit()
        self.state.info.emit(f"定期の予定 {n} 件を記録しました")
        self.update()
        return n

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected_id and not self.state.readonly:
            self.delete_selected()
            return
        if ev.key() == Qt.Key_Escape and self._drag:
            self._drag, self._ghost = None, None
            self.update()
            return
        super().keyPressEvent(ev)

    def delete_selected(self) -> None:
        if self.selected_id and self._run(self.state.editor.delete, self.selected_id, "削除"):
            self.selected_id = None
            self.selection_changed.emit()
        self.update()

    # --- タスク一覧パネルからのドロップ --------------------------------------
    def _drop_info(self, pos: QPointF):
        col = self.column_at(pos.x())
        if col is None:
            return None, None
        date = self.dates[col]
        return date, tl.resolve_drop(self._day_bars(date), self.minute_at(pos.y()))

    def dragEnterEvent(self, ev):
        if ics_path_from(ev.mimeData()) and not self.state.viewing_other:
            ev.acceptProposedAction()
            return
        if ev.mimeData().hasFormat(TASK_MIME) and not self.state.readonly:
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ics_path_from(ev.mimeData()) and not self.state.viewing_other:
            ev.acceptProposedAction()
            return
        if not ev.mimeData().hasFormat(TASK_MIME) or self.state.readonly:
            return
        date, res = self._drop_info(ev.position())
        self._ghost, self._drop_target = None, None
        if isinstance(res, tl.DropCreate):
            self._ghost = (self.dates.index(date), res.start, res.end)
        elif isinstance(res, tl.DropOnBar):
            self._drop_target = res.worklog_id
        ev.acceptProposedAction()
        self.update()

    def dragLeaveEvent(self, ev):
        self._ghost, self._drop_target = None, None
        self.update()

    def dropEvent(self, ev):
        self._ghost, self._drop_target = None, None
        path = ics_path_from(ev.mimeData())
        if path:
            ev.acceptProposedAction()
            self.ics_dropped.emit(path)
            return
        task_id = bytes(ev.mimeData().data(TASK_MIME)).decode("utf-8")
        date, res = self._drop_info(ev.position())
        ev.acceptProposedAction()
        self.drop_task(task_id, date, res)
        self.update()

    def drop_task(self, task_id: str, date: _dt.date | None, res) -> None:
        if isinstance(res, tl.DropOnBar):
            w = self.state.repo.get_worklog(res.worklog_id)
            new = tl.with_sub(w, SubItem(KIND_TASK, task_id=task_id))
            if self._run(self.state.editor.update, new, "サブタスクを追加"):
                self.selected_id = w.id
        elif isinstance(res, tl.DropCreate):
            w = Worklog("", date, res.start, res.end, kind=KIND_TASK, task_id=task_id)
            if self._run(self.state.editor.add, w, "作成"):
                self.selected_id = self.state.repo.worklogs[-1].id
        elif date is not None:
            self._error("ここには15分以上の空きがないため、作業バーを作れません")


# ===========================================================================
class _ColumnStrip(QWidget):
    """キャンバスの列に合わせて文字を描く帯（見出し・稼働時間）。"""

    def __init__(self, canvas: TimelineCanvas, height: int, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setFixedHeight(height)
        canvas.geometry_changed.connect(self.update)

    def texts(self) -> list[tuple[str, bool]]:
        raise NotImplementedError

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.WHITE))
        cw = self.canvas.col_width()
        for i, (text, strong) in enumerate(self.texts()):
            if text and text != "—":  # 稼働時間は淡い丸い地に
                r = QRectF(self.canvas.col_x(i) + 6, 3, cw - 12, self.height() - 6)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.BACKGROUND))
                p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT if text != "—" else "#9AA7B3"))
            p.drawText(QRectF(self.canvas.col_x(i), 0, cw, self.height()), Qt.AlignCenter, text)
        p.end()


class TimelineHeader(_ColumnStrip):
    """日付の見出し。終日の予定は、その日の列の上部に件名だけ表示する（F-05）。"""

    BASE = 28
    LINE = 16
    MAX_LINES = 2

    def texts(self):
        today = self.canvas.state.today()
        return [(day_label(d), d == today) for d in self.canvas.dates]

    def update_height(self) -> None:
        n = max((len(self.canvas.all_day_on(d)) for d in self.canvas.dates), default=0)
        self.setFixedHeight(self.BASE + self.LINE * min(n, self.MAX_LINES) + (3 if n else 0))
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.WHITE))
        cw = self.canvas.col_width()
        today = self.canvas.state.today()
        for i, d in enumerate(self.canvas.dates):
            x = self.canvas.col_x(i)
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            if d == today:  # 今日は淡い水色の丸い地に濃い青の文字
                tw = QFontMetrics(f).horizontalAdvance(day_label(d)) + 24
                pill = QRectF(x + (cw - tw) / 2, 3, tw, self.BASE - 6)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.ACCENT_SOFT))
                p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
                p.setPen(QColor(theme.ACCENT_TEXT))
            else:
                p.setPen(QColor(theme.TEXT if d.weekday() < 5 else theme.TEXT_MUTED))
            p.drawText(QRectF(x, 0, cw, self.BASE), Qt.AlignCenter, day_label(d))
            p.setFont(self.font())
            fm = QFontMetrics(self.font())
            items = self.canvas.all_day_on(d)
            shown = items if len(items) <= self.MAX_LINES else items[:self.MAX_LINES - 1]
            for k, a in enumerate(shown):
                r = QRectF(x + 2, self.BASE + k * self.LINE, cw - 4, self.LINE - 1)
                fill = QColor(APPT_COLOR)
                fill.setAlpha(40)
                p.fillRect(r, fill)
                p.fillRect(r, QBrush(APPT_COLOR.lighter(130), Qt.BDiagPattern))
                p.setPen(QColor("#283593"))
                p.drawText(r.adjusted(4, 0, -2, 0), Qt.AlignLeft | Qt.AlignVCenter,
                           fm.elidedText(a.title, Qt.ElideRight, int(r.width() - 6)))
            if len(items) > self.MAX_LINES:
                r = QRectF(x + 2, self.BASE + (self.MAX_LINES - 1) * self.LINE, cw - 4, self.LINE - 1)
                p.setPen(QColor("#283593"))
                p.drawText(r.adjusted(4, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                           f"他 {len(items) - self.MAX_LINES + 1} 件の終日の予定")
        p.end()

    def event(self, ev):
        if ev.type() == ev.Type.ToolTip:
            col = self.canvas.column_at(ev.pos().x())
            if col is not None:
                items = self.canvas.all_day_on(self.canvas.dates[col])
                if items:
                    QToolTip.showText(ev.globalPos(), "終日の予定：\n" + "\n".join(a.title for a in items), self)
                    return True
        return super().event(ev)


class TimelineFooter(_ColumnStrip):
    """各日の列の下に、その日の稼働時間を表示する。"""

    def texts(self):
        repo = self.canvas.state.repo
        out = []
        for d in self.canvas.dates:
            m = ag.working_minutes(repo.worklogs_on(d))
            out.append((f"稼働 {tu.format_hours(m)}" if m else "—", False))
        return out


# ===========================================================================
class TaskPanel(QListWidget):
    """未完了タスクの一覧。タイムラインへドラッグできる。"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragOnly)
        self.setWordWrap(True)
        self.setSpacing(1)
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        for t in tl.sort_open_tasks(self.state.repo.tasks):
            item = QListWidgetItem(color_icon(self.state.task_color(t), 14), t.name)
            item.setData(Qt.UserRole, t.id)
            due = f"　完了予定 {t.planned_end:%m/%d}" if t.planned_end else ""
            item.setToolTip(f"{t.id}　{t.category or '（カテゴリなし）'}　{t.status}　{t.progress}%{due}\n"
                            "タイムラインの空き時間へドラッグすると1時間の作業バーを作成、"
                            "作業バーの上へドラッグするとサブタスクに追加")
            self.addItem(item)

    def mimeTypes(self):
        return [TASK_MIME]

    def mimeData(self, items):
        md = QMimeData()
        if items:
            md.setData(TASK_MIME, items[0].data(Qt.UserRole).encode("utf-8"))
        return md

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None or self.state.readonly:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData([item]))
        drag.exec(Qt.CopyAction)


# ===========================================================================
class TimelineTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.mode = state.settings.view_mode if state.settings.view_mode in ("day", "week") else "week"
        self.anchor = state.today()

        # 上部の操作
        bar = QHBoxLayout()
        self.btn_prev = QPushButton("◀ 前へ")
        self.btn_today = QPushButton("今日")
        self.btn_next = QPushButton("次へ ▶")
        self.period_label = QLabel()
        f = self.period_label.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1)
        self.period_label.setFont(f)
        self.btn_day = QToolButton(text="日")
        self.btn_week = QToolButton(text="週")
        grp = QButtonGroup(self)
        for b in (self.btn_day, self.btn_week):
            b.setCheckable(True)
            b.setMinimumWidth(40)
            grp.addButton(b)
        self.btn_import = QPushButton("予定を取り込む")
        self.btn_import.setProperty("accent", True)
        self.btn_import.setToolTip("Outlookから保存した予定表ファイル（.ics）を選ぶ。タイムラインへドラッグ＆ドロップしても読み込めます")
        self.btn_reload = QPushButton("再読み込み")
        self.btn_reload.setToolTip("前回読み込んだ予定表ファイルを読み直す")
        self.ics_file: ics.IcsFile | None = None
        for wdg in (self.btn_prev, self.btn_today, self.btn_next):
            bar.addWidget(wdg)
        bar.addSpacing(12)
        bar.addWidget(self.period_label)
        bar.addSpacing(12)
        bar.addWidget(self.btn_day)
        bar.addWidget(self.btn_week)
        bar.addStretch()
        bar.addWidget(self.btn_import)
        bar.addWidget(self.btn_reload)

        # 左: タスク一覧パネル
        left = QWidget()
        theme.card(left)
        left.setFixedWidth(290)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 14, 14, 14)
        ll.setSpacing(4)
        cap = QLabel("未完了のタスク")
        cap.setStyleSheet("font-weight: bold; font-size: 13px;")
        hint = QLabel("タイムラインへドラッグして記録")
        hint.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        ll.addWidget(cap)
        ll.addWidget(hint)
        self.panel = TaskPanel(state)
        self.panel.setStyleSheet("QListWidget { border: 0; }")
        self.panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ll.addWidget(self.panel)

        # 右: タイムライン
        self.canvas = TimelineCanvas(state)
        self.header = TimelineHeader(self.canvas, 28)
        self.footer = TimelineFooter(self.canvas, 26)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll = scroll
        right = QWidget()
        theme.card(right)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(4)
        rl.addWidget(self.header)
        rl.addWidget(scroll, 1)
        rl.addWidget(self.footer)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(left)
        body.addWidget(right, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(12)
        lay.addLayout(bar)
        lay.addLayout(body, 1)

        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.btn_today.clicked.connect(self.go_today)
        self.btn_day.clicked.connect(lambda: self.set_mode("day"))
        self.btn_week.clicked.connect(lambda: self.set_mode("week"))
        state.worklogs_changed.connect(self.refresh_canvas)
        state.tasks_changed.connect(self.refresh_all)
        state.categories_changed.connect(self.refresh_all)
        state.repo_switched.connect(lambda: self._update_appointments(announce=False))
        self.btn_import.clicked.connect(self.choose_ics)
        self.btn_reload.clicked.connect(self.reload_ics)
        self.canvas.ics_dropped.connect(self.load_ics)
        if state.settings.ics_path:  # 前回の予定表ファイルから再表示（5.3）
            self._open_ics(state.settings.ics_path, announce_errors=False)
        self.set_mode(self.mode)

    # --- 予定表ファイル（F-05） ---
    def choose_ics(self) -> None:
        start = str(Path(self.state.settings.ics_path).parent) if self.state.settings.ics_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "予定表ファイル（.ics）を選ぶ", start,
                                              "予定表ファイル (*.ics);;すべて (*)")
        if path:
            self.load_ics(path)

    def load_ics(self, path: str) -> bool:
        """予定表ファイルを読み込む。読めなければメッセージを出し、予定バーは変更しない。"""
        if not self._open_ics(path, announce_errors=True):
            return False
        self.state.settings.ics_path = str(path)
        try:
            self.state.settings.save()
        except OSError:
            pass
        self._update_appointments(announce=True)
        return True

    def reload_ics(self) -> None:
        path = self.state.settings.ics_path
        if not path:
            self.state.error.emit("予定表ファイルがまだ読み込まれていません。「予定を取り込む」で選んでください")
            return
        if self._open_ics(path, announce_errors=True):
            self._update_appointments(announce=True)

    def _open_ics(self, path: str, announce_errors: bool) -> bool:
        try:
            f = ics.IcsFile(path)
        except FileNotFoundError:
            log.warning("予定表ファイルが見つかりません")
            self.ics_file = None
            self._update_appointments(announce=False)
            # 起動直後は画面の準備ができてから表示する（画面下部に表示、9章）
            QTimer.singleShot(0, lambda: self.state.error.emit(ics.NOT_FOUND_MESSAGE))
            return False
        except ics.IcsFormatError as e:
            log.warning("予定表ファイルを読み取れませんでした（%s）", e.detail)
            if announce_errors:
                QMessageBox.warning(self, "予定を取り込む", ics.FORMAT_ERROR_MESSAGE)
            self.state.error.emit(ics.FORMAT_ERROR_MESSAGE)
            return False
        except OSError as e:
            log.warning("予定表ファイルを開けませんでした: %s", e)
            self.state.error.emit(f"{ics.FORMAT_ERROR_MESSAGE}（{e.strerror or e}）")
            return False
        self.ics_file = f
        log.info("予定表ファイルを読み込みました（読み飛ばし %d 件）", f.bad_events)
        return True

    def _update_appointments(self, announce: bool = True) -> None:
        """表示中の日にかかる予定を、読み込んだ予定表ファイルから展開する（週を切り替えたときも同じファイルから）。"""
        dates = self.canvas.dates
        appts: list[ics.Appointment] = []
        if self.ics_file is not None and dates:
            weeks = sorted({tu.week_start(d) for d in dates})
            skipped = 0
            found_in_week = 0
            for w in weeks:
                r = self.ics_file.week(w)
                skipped += r.skipped
                found_in_week += len(r.appointments)
                appts += [a for a in r.appointments if any(d in dates for d in a.days())]
            if announce and not self.state.viewing_other:
                if skipped:
                    self.state.error.emit(f"{skipped}件の予定を読み飛ばしました")
                elif found_in_week == 0:
                    self.state.info.emit(ics.EMPTY_WEEK_MESSAGE)
        self.canvas.appointments = appts
        self.canvas.update()
        self.header.update_height()

    # --- 表示の切り替え ---
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.btn_day.setChecked(mode == "day")
        self.btn_week.setChecked(mode == "week")
        self._apply_dates()

    def step(self, direction: int) -> None:
        self.anchor = tl.step_anchor(self.anchor, self.mode, direction)
        self._apply_dates()

    def go_today(self) -> None:
        self.anchor = self.state.today()
        self._apply_dates()

    def _apply_dates(self) -> None:
        dates = tl.visible_dates(self.anchor, self.mode)
        if len(dates) == 1:
            d = dates[0]
            self.period_label.setText(f"{d:%Y/%m/%d}（{WEEKDAYS[d.weekday()]}）")
        else:
            self.period_label.setText(f"{dates[0]:%Y/%m/%d}〜{dates[-1]:%m/%d}")
        self.canvas.set_dates(dates)
        self.footer.update()
        if hasattr(self, "ics_file"):
            self._update_appointments(announce=self.ics_file is not None)

    def refresh_canvas(self) -> None:
        self.canvas.update()
        self.footer.update()

    def refresh_all(self) -> None:
        self.panel.refresh()
        self.refresh_canvas()

        self.refresh_canvas()

    def undo(self) -> None:
        if self.state.readonly:
            return
        try:
            label = self.state.editor.undo()
        except (OverlapError, ValidationError, KeyError, ValueError) as e:
            self.state.error.emit(f"元に戻せませんでした: {e}")
            self.state.worklogs_changed.emit()
            return
        except OSError as e:
            self.state.error.emit(f"保存できませんでした: {e}")
            return
        if label is None:
            self.state.info.emit("元に戻す操作はありません")
        else:
            self.canvas.selected_id = None
            self.state.info.emit(f"「{label}」を元に戻しました")
            self.state.worklogs_changed.emit()
