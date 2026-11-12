"""集計・週報タブ（F-04 集計。週報は M4 で追加）。"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDateEdit, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from ..core import aggregate as ag
from ..core import colors
from ..core import timeutil as tu
from .charts import DailyStackChart, Legend, ProgressMeter, TaskBarChart
from .state import AppState
from .widgets import color_icon

RED = QColor("#C62828")
EMPTY_MESSAGE = "記録がありません"


def _qdate(d: _dt.date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _pydate(q: QDate) -> _dt.date:
    return _dt.date(q.year(), q.month(), q.day())


def _heading(text: str) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setBold(True)
    f.setPointSizeF(f.pointSizeF() + 1)
    lab.setFont(f)
    lab.setContentsMargins(0, 12, 0, 2)
    return lab


def _fit_table_height(table: QTableWidget) -> None:
    h = table.horizontalHeader().height() + 4
    for r in range(table.rowCount()):
        h += table.rowHeight(r)
    table.setFixedHeight(h)


def remaining_text(row: ag.ProgressRow) -> tuple[str, bool]:
    """(表示文字, 赤で表示するか)"""
    if not row.task.is_open:
        return "完了", False
    d = row.remaining_days
    if d is None:
        return "—", False
    if d > 0:
        return f"あと {d} 日", False
    if d == 0:
        return "今日まで", False
    return f"{-d} 日超過", True


class SummaryPage(QWidget):
    """集計（F-04）。"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.mode = ag.PERIOD_WEEK
        self.anchor = state.today()
        self._dirty = True

        # 期間の選択（グラフの上に1行）
        bar = QHBoxLayout()
        self.btn_day, self.btn_week, self.btn_custom = (QToolButton(text=t) for t in ("日", "週", "期間指定"))
        grp = QButtonGroup(self)
        for b in (self.btn_day, self.btn_week, self.btn_custom):
            b.setCheckable(True)
            b.setMinimumWidth(44)
            grp.addButton(b)
            bar.addWidget(b)
        bar.addSpacing(12)
        self.btn_prev, self.btn_today, self.btn_next = QPushButton("◀ 前へ"), QPushButton("今日"), QPushButton("次へ ▶")
        for b in (self.btn_prev, self.btn_today, self.btn_next):
            bar.addWidget(b)
        bar.addSpacing(12)
        self.start_edit, self.end_edit = QDateEdit(), QDateEdit()
        for e in (self.start_edit, self.end_edit):
            e.setCalendarPopup(True)
            e.setDisplayFormat("yyyy-MM-dd")
            e.setDate(_qdate(self.anchor))
        bar.addWidget(self.start_edit)
        bar.addWidget(QLabel("〜"))
        bar.addWidget(self.end_edit)
        bar.addSpacing(12)
        self.period_label = QLabel()
        f = self.period_label.font()
        f.setBold(True)
        self.period_label.setFont(f)
        bar.addWidget(self.period_label)
        bar.addStretch()

        # 内容
        self.summary_line = QLabel()
        self.empty_label = QLabel(EMPTY_MESSAGE)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color:#777; font-size: 14px; padding: 24px;")
        self.legend = Legend()
        self.daily = DailyStackChart()
        self.task_chart = TaskBarChart()
        self.cat_table = QTableWidget(0, 3)
        self.cat_table.setHorizontalHeaderLabels(["カテゴリ", "時間", "割合"])
        self.progress_table = QTableWidget(0, 8)
        self.progress_table.setHorizontalHeaderLabels(
            ["タスク", "カテゴリ", "ステータス", "進捗率", "実績時間 / 予定工数", "サブ時間", "完了予定日", "残り日数"])
        for t in (self.cat_table, self.progress_table):
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionMode(QAbstractItemView.NoSelection)
            t.verticalHeader().hide()
            t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            t.setFocusPolicy(Qt.NoFocus)
        self.cat_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        ph = self.progress_table.horizontalHeader()
        ph.setSectionResizeMode(QHeaderView.ResizeToContents)
        ph.setSectionResizeMode(0, QHeaderView.Stretch)
        ph.setSectionResizeMode(3, QHeaderView.Fixed)
        self.progress_table.setColumnWidth(3, 200)

        self.period_box = QWidget()
        pl = QVBoxLayout(self.period_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.summary_line)
        pl.addWidget(_heading("日別のタスク別時間"))
        pl.addWidget(self.legend)
        pl.addWidget(self.daily)
        self.task_heading = _heading("タスク別の合計時間")
        pl.addWidget(self.task_heading)
        pl.addWidget(self.task_chart)
        pl.addWidget(_heading("カテゴリ別の合計時間と割合"))
        pl.addWidget(self.cat_table)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.addWidget(self.period_box)
        cl.addWidget(self.empty_label)
        cl.addWidget(_heading("タスクごとの進捗"))
        note = QLabel("実績時間はメイン時間の累計。予定工数を超えたものは赤字。対象は未完了のタスクと、期間内に作業バーがあるタスク。")
        note.setStyleSheet("color:#666;")
        cl.addWidget(note)
        cl.addWidget(self.progress_table)
        cl.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(scroll, 1)

        self.btn_day.clicked.connect(lambda: self.set_mode(ag.PERIOD_DAY))
        self.btn_week.clicked.connect(lambda: self.set_mode(ag.PERIOD_WEEK))
        self.btn_custom.clicked.connect(lambda: self.set_mode(ag.PERIOD_CUSTOM))
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.btn_today.clicked.connect(self.go_today)
        self.start_edit.dateChanged.connect(lambda _: self.refresh())
        self.end_edit.dateChanged.connect(lambda _: self.refresh())
        for sig in (state.worklogs_changed, state.tasks_changed, state.categories_changed):
            sig.connect(self._mark_dirty)
        self.set_mode(ag.PERIOD_WEEK)

    # --- 期間 ---
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.btn_day.setChecked(mode == ag.PERIOD_DAY)
        self.btn_week.setChecked(mode == ag.PERIOD_WEEK)
        self.btn_custom.setChecked(mode == ag.PERIOD_CUSTOM)
        custom = mode == ag.PERIOD_CUSTOM
        for b in (self.btn_prev, self.btn_today, self.btn_next):
            b.setEnabled(not custom)
        self.start_edit.setEnabled(custom)
        self.end_edit.setEnabled(custom)
        if custom:
            s, e = ag.period_range(ag.PERIOD_WEEK, self.anchor)
            for edit, d in ((self.start_edit, s), (self.end_edit, e)):
                edit.blockSignals(True)
                edit.setDate(_qdate(d))
                edit.blockSignals(False)
        self.refresh()

    def step(self, direction: int) -> None:
        self.anchor += _dt.timedelta(days=direction * (1 if self.mode == ag.PERIOD_DAY else 7))
        self.refresh()

    def go_today(self) -> None:
        self.anchor = self.state.today()
        self.refresh()

    def period(self) -> tuple[_dt.date, _dt.date]:
        return ag.period_range(self.mode, self.anchor, _pydate(self.start_edit.date()),
                               _pydate(self.end_edit.date()))

    # --- 更新 ---
    def _mark_dirty(self) -> None:
        self._dirty = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._dirty:
            self.refresh()

    def _color(self, category: str) -> str:
        if category == ag.ONEOFF_LABEL:
            return colors.ONEOFF_COLOR
        return self.state.category_colors.get(category, colors.UNCATEGORIZED_COLOR)

    def refresh(self) -> None:
        self._dirty = False
        repo = self.state.repo
        start, end = self.period()
        if start == end:
            self.period_label.setText(f"{start:%Y/%m/%d}（{'月火水木金土日'[start.weekday()]}）")
        else:
            self.period_label.setText(f"{start:%Y/%m/%d}〜{end:%Y/%m/%d}（{(end - start).days + 1}日間）")
        tasks = repo.tasks
        tasks_by_id = {t.id: t for t in tasks}
        summary = ag.period_summary(repo.worklogs, tasks, start, end)
        self.period_box.setVisible(not summary.is_empty)
        self.empty_label.setVisible(summary.is_empty)
        if not summary.is_empty:
            sub_total = sum(summary.sub_by_task.values()) + summary.sub_oneoff
            self.summary_line.setText(
                f"稼働時間 {tu.format_hours(summary.working)}　／　単発作業 {tu.format_hours(summary.oneoff)}"
                f"　／　サブ時間（参考） {tu.format_hours(sub_total)}　／　作業バー {summary.count} 件")
            self._fill_daily(repo, tasks, tasks_by_id, start, end)
            self._fill_task_chart(summary, tasks_by_id)
            self._fill_categories(summary)
        self._fill_progress(tasks, start, end)

    def _fill_daily(self, repo, tasks, tasks_by_id, start, end) -> None:
        cats = list(self.state.category_colors)
        stacks = ag.daily_stacks(repo.worklogs, tasks, start, end, cats)
        present = {s.category for st in stacks for s in st.segments}
        order = ag.category_order(tasks, cats)
        self.legend.set_items([(c, self._color(c)) for c in order if c in present])

        def label_of(seg):
            if seg.key == ag.ONEOFF_LABEL:
                return ag.ONEOFF_LABEL
            t = tasks_by_id.get(seg.key)
            return t.name if t else seg.key
        self.daily.set_data(stacks, lambda seg: self._color(seg.category), label_of)

    def _fill_task_chart(self, summary, tasks_by_id) -> None:
        self.task_heading.setText("週のタスク別時間" if self.mode == ag.PERIOD_WEEK else "期間のタスク別時間")
        rows = []
        for key, m in summary.task_ranking():
            if key == ag.ONEOFF_LABEL:
                rows.append((ag.ONEOFF_LABEL, m, colors.ONEOFF_COLOR, summary.sub_oneoff))
            else:
                t = tasks_by_id.get(key)
                rows.append((t.name if t else key, m, self.state.task_color(t), summary.sub_by_task.get(key, 0)))
        self.task_chart.set_data(rows)

    def _fill_categories(self, summary) -> None:
        rows = summary.category_share()
        t = self.cat_table
        t.setRowCount(len(rows) + 1)
        for r, (name, m, share) in enumerate(rows):
            it = QTableWidgetItem(color_icon(self._color(name)), name)
            t.setItem(r, 0, it)
            t.setItem(r, 1, self._num(tu.format_hours(m)))
            t.setItem(r, 2, self._num(f"{share * 100:.1f}%"))
        bold = QFont(t.font())
        bold.setBold(True)
        total = sum(m for _, m, _ in rows)
        for c, text in enumerate(("合計", tu.format_hours(total), "100.0%")):
            it = self._num(text) if c else QTableWidgetItem(text)
            it.setFont(bold)
            t.setItem(len(rows), c, it)
        t.resizeColumnsToContents()
        t.setColumnWidth(0, max(t.columnWidth(0), 160))
        t.setFixedWidth(t.horizontalHeader().length() + 2 * t.frameWidth())
        _fit_table_height(t)

    def _fill_progress(self, tasks, start, end) -> None:
        rows = ag.progress_rows(tasks, self.state.repo.worklogs, start, end, self.state.today())
        t = self.progress_table
        t.clearContents()
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            task = row.task
            t.setItem(r, 0, QTableWidgetItem(task.name))
            cat = QTableWidgetItem(color_icon(self.state.task_color(task)), task.category or ag.UNCATEGORIZED_LABEL)
            t.setItem(r, 1, cat)
            t.setItem(r, 2, QTableWidgetItem(task.status))
            t.setCellWidget(r, 3, ProgressMeter(task.progress, self.state.task_color(task)))
            actual = tu.format_hours(row.actual)
            if task.estimate_hours is not None:
                text = f"{actual} / {task.estimate_hours:g}h"
                if row.over_estimate:
                    text += "（超過）"
            else:
                text = actual
            it = self._num(text)
            if row.over_estimate:
                it.setForeground(RED)
            t.setItem(r, 4, it)
            t.setItem(r, 5, self._num(tu.format_hours(row.sub) if row.sub else "—"))
            t.setItem(r, 6, QTableWidgetItem(task.planned_end.isoformat() if task.planned_end else "—"))
            rem, red = remaining_text(row)
            it = QTableWidgetItem(rem)
            if red:
                it.setForeground(RED)
            t.setItem(r, 7, it)
        _fit_table_height(t)

    @staticmethod
    def _num(text: str) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return it


class SummaryTab(QTabWidget):
    """「集計・週報」タブ。中を「集計」「週報」に分ける。"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.summary = SummaryPage(state)
        self.addTab(self.summary, "集計")
        placeholder = QLabel("週報は次のバージョン（M4）で追加します")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color:#777; font-size: 14px;")
        self.addTab(placeholder, "週報")
