"""週報（F-06）。集計（build_report）、テキスト（report_text）、Excel出力（write_xlsx）。

画面に依存しないので、画面なしでテストできる。
"""
from __future__ import annotations

import datetime as _dt
import os
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from . import aggregate as ag
from . import colors
from . import timeutil as tu
from .models import KIND_ONEOFF, STATUS_DONE, STATUS_IN_PROGRESS, Task, WeeklyNote, Worklog

EMPTY_MESSAGE = "対象週の記録がありません"
LOCKED_MESSAGE = "ファイルを閉じてから再度実行してください"
ROWS_PER_FIRST_PAGE = 20
NEXT_WEEK_AUTO_COUNT = 5
WEEKDAYS = "月火水木金土日"
_STATUS_ORDER = {"完了": 0, "進行中": 1, "保留": 2, "未着手": 3}


class ReportEmptyError(ValueError):
    def __init__(self):
        super().__init__(EMPTY_MESSAGE)


class ReportLockedError(PermissionError):
    def __init__(self, path: Path):
        super().__init__(LOCKED_MESSAGE)
        self.path = path


@dataclass
class TaskRow:
    task_id: str
    category: str
    name: str
    status: str
    week_main: int  # 今週の時間（メイン、分）
    week_sub: int  # 今週のサブ時間（分）
    total_main: int  # 累計時間（メイン、週末まで、分）
    progress_start: int  # 週初（前週末時点）の進捗率
    progress_end: int  # 週末時点の進捗率
    planned_end: _dt.date | None
    deadline: _dt.date | None


@dataclass
class OneoffRow:
    date: _dt.date
    start: int
    end: int
    title: str
    is_sub: bool  # サブタスクとして記録した単発作業か

    @property
    def minutes(self) -> int:
        return self.end - self.start


@dataclass
class DayRow:
    date: _dt.date
    working: int
    by_category: dict[str, int]


@dataclass
class WeeklyReport:
    display_name: str
    week_start: _dt.date
    created: _dt.date
    working: int
    done_count: int
    in_progress_count: int
    rows: list[TaskRow]
    oneoffs: list[OneoffRow]
    days: list[DayRow]
    categories: list[str]  # 日別の積み上げの順（記録のあるカテゴリのみ）
    next_week: str
    next_week_auto: bool
    reflection: str
    worklog_count: int = 0
    category_colors: dict[str, str] = field(default_factory=dict)

    @property
    def week_end(self) -> _dt.date:
        return self.week_start + _dt.timedelta(days=6)

    @property
    def is_empty(self) -> bool:
        return self.worklog_count == 0 and not self.rows

    @property
    def period_text(self) -> str:
        """例: 2026/11/09〜11/15"""
        s, e = self.week_start, self.week_end
        tail = f"{e:%m/%d}" if s.year == e.year else f"{e:%Y/%m/%d}"
        return f"{s:%Y/%m/%d}〜{tail}"

    @property
    def oneoff_main_total(self) -> int:
        return sum(o.minutes for o in self.oneoffs if not o.is_sub)

    @property
    def oneoff_sub_total(self) -> int:
        return sum(o.minutes for o in self.oneoffs if o.is_sub)

    @property
    def filename(self) -> str:
        return f"週報_{self.display_name}_{self.week_start:%Y%m%d}.xlsx"


def _hours(minutes: int) -> float:
    return minutes / 60


def next_week_candidates(tasks: Iterable[Task], n: int = NEXT_WEEK_AUTO_COUNT) -> list[Task]:
    """未完了タスクを完了予定日の近い順に n 件（完了予定日が未設定のものは後ろ）。"""
    open_tasks = [t for t in tasks if t.is_open]
    open_tasks.sort(key=lambda t: (t.planned_end or _dt.date.max, t.id))
    return open_tasks[:n]


def _auto_next_week(tasks: Iterable[Task]) -> str:
    lines = []
    for t in next_week_candidates(tasks):
        due = f"完了予定 {t.planned_end:%m/%d}" if t.planned_end else "完了予定 未設定"
        lines.append(f"・{t.name}（{due}）")
    return "\n".join(lines)


def build_report(tasks: list[Task], worklogs: list[Worklog], note: WeeklyNote | None, display_name: str,
                 week_start: _dt.date, today: _dt.date, categories: Iterable[str] = (),
                 category_colors: Mapping[str, str] | None = None) -> WeeklyReport:
    """週報の内容を集計する。

    対象タスク: 対象週に作業バー（メインまたはサブ）があるタスク、対象週に進捗率が変わったタスク、
    対象週に完了したタスク（完了日が対象週内）。
    """
    week_start = tu.week_start(week_start)
    week_end = week_start + _dt.timedelta(days=6)
    in_week = ag.filter_period(worklogs, week_start, week_end)
    until_end = [w for w in worklogs if w.date <= week_end]
    main_w = ag.minutes_by_task(in_week)
    sub_w = ag.sub_minutes_by_task(in_week)
    main_total = ag.minutes_by_task(until_end)

    rows = []
    for t in tasks:
        progress_changed = any(week_start <= e.date <= week_end for e in t.history)
        done_in_week = t.done_date is not None and week_start <= t.done_date <= week_end
        if not (t.id in main_w or t.id in sub_w or progress_changed or done_in_week):
            continue
        rows.append(TaskRow(
            task_id=t.id, category=t.category or ag.UNCATEGORIZED_LABEL, name=t.name, status=t.status,
            week_main=main_w.get(t.id, 0), week_sub=sub_w.get(t.id, 0), total_main=main_total.get(t.id, 0),
            progress_start=ag.progress_on(t, week_start - _dt.timedelta(days=1)),
            progress_end=ag.progress_on(t, week_end) if t.history else t.progress,
            planned_end=t.planned_end, deadline=t.deadline))
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r.status, 9), -r.week_main, r.task_id))

    oneoffs = []
    for w in sorted(in_week, key=lambda w: (w.date, w.start, w.id)):
        if w.kind == KIND_ONEOFF:
            oneoffs.append(OneoffRow(w.date, w.start, w.end, w.title, False))
        for s in w.subs:
            if s.kind == KIND_ONEOFF:
                oneoffs.append(OneoffRow(w.date, w.start, w.end, s.title, True))

    summaries = ag.daily_summary(worklogs, tasks, week_start, week_end)
    order = ag.category_order(tasks, categories)
    present = {c for d in summaries for c, m in d.by_category.items() if m}
    cats = [c for c in order if c in present]
    days = [DayRow(d.date, d.working, {c: d.by_category.get(c, 0) for c in cats}) for d in summaries]

    note_text = (note.next_week if note else "").strip()
    return WeeklyReport(
        display_name=display_name, week_start=week_start, created=today,
        working=ag.working_minutes(in_week),
        done_count=sum(1 for t in tasks if t.done_date and week_start <= t.done_date <= week_end),
        in_progress_count=sum(1 for t in tasks if t.status == STATUS_IN_PROGRESS),
        rows=rows, oneoffs=oneoffs, days=days, categories=cats,
        next_week=note_text or _auto_next_week(tasks), next_week_auto=not note_text,
        reflection=(note.reflection if note else "").strip(),
        worklog_count=len(in_week),
        category_colors=dict(category_colors or {}),
    )


# --- テキスト（「テキストをコピー」: 3・4・6・7） ---------------------------------
def _date_label(d: _dt.date) -> str:
    return f"{d:%m/%d}({WEEKDAYS[d.weekday()]})"


def _progress_label(r: TaskRow) -> str:
    return f"{r.progress_start}%→{r.progress_end}%"


def report_text(rep: WeeklyReport) -> str:
    out = [f"■タスク実績（{rep.period_text}）"]
    if not rep.rows:
        out.append("（なし）")
    for r in rep.rows:
        parts = [f"今週 {tu.format_hours(r.week_main)}"]
        if r.week_sub:
            parts.append(f"サブ {tu.format_hours(r.week_sub)}")
        parts.append(f"累計 {tu.format_hours(r.total_main)}")
        parts.append(f"進捗 {_progress_label(r)}")
        if r.planned_end:
            parts.append(f"完了予定 {r.planned_end:%m/%d}")
        if r.deadline:
            parts.append(f"期限 {r.deadline:%m/%d}")
        out.append(f"・[{r.status}] {r.name}（{r.category}）　" + "／".join(parts))
    out.append("")
    out.append("■単発作業")
    if not rep.oneoffs:
        out.append("（なし）")
    for o in rep.oneoffs:
        sub = "（サブ）" if o.is_sub else ""
        out.append(f"・{_date_label(o.date)} {tu.format_hhmm(o.start)}〜{tu.format_hhmm(o.end)} {o.title}{sub}")
    if rep.oneoffs:
        total = f"合計 {tu.format_hours(rep.oneoff_main_total)}"
        if rep.oneoff_sub_total:
            total += f"（サブとして記録した分 {tu.format_hours(rep.oneoff_sub_total)} は含まない）"
        out.append(total)
    out.append("")
    out.append("■来週の予定")
    out.append(rep.next_week or "（なし）")
    out.append("")
    out.append("■所感・課題")
    out.append(rep.reflection or "（なし）")
    return "\n".join(out) + "\n"


# --- Excel 出力 -----------------------------------------------------------------
FONT_NAME = "Meiryo UI"
HOURS_FORMAT = '0.0#"h"'
COLUMN_WIDTHS = {"A": 13, "B": 34, "C": 10, "D": 10, "E": 10, "F": 10, "G": 15, "H": 11, "I": 11}
LINE_HEIGHT = 15  # 1行の高さ（ポイント）


def _text_width(text: str) -> float:
    """列幅の単位での文字列の幅（全角は約1.8、半角は1）。"""
    return sum(1.8 if unicodedata.east_asian_width(ch) in "WFA" else 1.0 for ch in text)


def _line_count(text: str, col_width: float) -> int:
    usable = max(1.0, col_width - 1.0)
    return sum(max(1, -(-int(_text_width(line) + 0.999) // int(usable))) for line in (text or " ").split("\n"))
TABLE_HEADER = ["カテゴリ", "タスク名", "ステータス", "今週の時間(h)", "今週のサブ時間(h)", "累計時間(h)",
                "進捗率（週初→週末）", "完了予定日", "期限"]


def write_xlsx(rep: WeeklyReport, path: str | Path) -> Path:
    """週報をExcelファイルに保存する。保存先が開かれていて書けない場合は ReportLockedError。"""
    if rep.is_empty:
        raise ReportEmptyError()
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.formatting.rule import DataBarRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.pagebreak import Break

    path = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = "週報"
    for col, w in COLUMN_WIDTHS.items():
        ws.column_dimensions[col].width = w

    base = Font(name=FONT_NAME, size=10)
    bold = Font(name=FONT_NAME, size=10, bold=True)
    muted = Font(name=FONT_NAME, size=9, color="666666")
    thin = Side(style="thin", color="BFBFBF")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="F2F2F2")
    section_border = Border(bottom=Side(style="medium", color="404040"))
    wrap = Alignment(wrap_text=True, vertical="top")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def put(row, col, value, font=base, fmt=None, align=None, border=None, fill=None):
        c = ws.cell(row=row, column=col, value=value)
        c.font = font
        if fmt:
            c.number_format = fmt
        if align:
            c.alignment = align
        if border:
            c.border = border
        if fill:
            c.fill = fill
        return c

    def section(row, title):
        put(row, 1, title, Font(name=FONT_NAME, size=11, bold=True))
        for col in range(1, 10):
            ws.cell(row=row, column=col).border = section_border
        return row + 1

    def header_row(row, labels, cols=None):
        for i, label in enumerate(labels):
            put(row, (cols[i] if cols else i + 1), label, bold, align=center, border=box, fill=head_fill)
        ws.row_dimensions[row].height = 30

    # 1. ヘッダー
    put(1, 1, "週報", Font(name=FONT_NAME, size=16, bold=True))
    put(2, 1, "氏名", muted)
    put(2, 2, rep.display_name, bold)
    put(2, 3, "対象期間", muted)
    ws.merge_cells(start_row=2, start_column=4, end_row=2, end_column=6)
    put(2, 4, rep.period_text, bold)
    put(2, 7, "作成日", muted, align=Alignment(horizontal="right"))
    put(2, 8, rep.created.strftime("%Y/%m/%d"), base)

    # 2. サマリー
    row = section(4, "サマリー")
    put(row, 1, "稼働時間の合計", muted)
    put(row, 2, _hours(rep.working), bold, HOURS_FORMAT, Alignment(horizontal="left"))
    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
    put(row, 3, "完了タスク数", muted, align=Alignment(horizontal="right"))
    put(row, 5, rep.done_count, bold, '0"件"', Alignment(horizontal="left"))
    ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
    put(row, 6, "進行中タスク数", muted, align=Alignment(horizontal="right"))
    put(row, 8, rep.in_progress_count, bold, '0"件"', Alignment(horizontal="left"))

    # 3. タスク実績表
    row = section(row + 2, "タスク実績")
    header_row(row, TABLE_HEADER)
    header_at = row
    row += 1
    first_data = row
    break_after = None
    for i, r in enumerate(rep.rows):
        if i == ROWS_PER_FIRST_PAGE:  # 20行を超えたら2ページ目に続ける（見出しを繰り返す）
            break_after = row - 1
            header_row(row, TABLE_HEADER)
            row += 1
        put(row, 1, r.category, align=wrap, border=box)
        put(row, 2, r.name, align=wrap, border=box)
        put(row, 3, r.status, align=Alignment(horizontal="center", vertical="top"), border=box)
        put(row, 4, _hours(r.week_main), fmt=HOURS_FORMAT, border=box, align=Alignment(vertical="top"))
        put(row, 5, _hours(r.week_sub), fmt=HOURS_FORMAT, border=box, align=Alignment(vertical="top"))
        put(row, 6, _hours(r.total_main), fmt=HOURS_FORMAT, border=box, align=Alignment(vertical="top"))
        # 値は週末の進捗率（数値）。週初の値は表示形式に入れ、セル内の横棒（データバー）は週末の値で描く。
        put(row, 7, r.progress_end, fmt=f'"{r.progress_start}%→"0"%"', border=box,
            align=Alignment(horizontal="right", vertical="top"))
        put(row, 8, r.planned_end, fmt="yyyy/mm/dd", border=box, align=Alignment(vertical="top"))
        put(row, 9, r.deadline, fmt="yyyy/mm/dd", border=box, align=Alignment(vertical="top"))
        # 折り返す行は高さを明示する（表示ソフトによって後の図の位置がずれないように）
        lines = max(_line_count(r.name, COLUMN_WIDTHS["B"]), _line_count(r.category, COLUMN_WIDTHS["A"]))
        ws.row_dimensions[row].height = lines * LINE_HEIGHT + 3
        row += 1
    last_data = row - 1
    if rep.rows:
        ws.conditional_formatting.add(
            f"G{first_data}:G{last_data}",
            DataBarRule(start_type="num", start_value=0, end_type="num", end_value=100, color="7FB2E5"))
    else:
        put(row, 1, "（なし）", muted)
        row += 1
    if break_after:
        ws.row_breaks.append(Break(id=break_after))

    # 4. 単発作業
    row = section(row + 1, "単発作業")
    header_row(row, ["日付", "時間帯", "タイトル", "区分", "時間(h)"], cols=[1, 2, 3, 7, 8])
    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=6)
    row += 1
    for o in rep.oneoffs:
        put(row, 1, _date_label(o.date), border=box)
        put(row, 2, f"{tu.format_hhmm(o.start)}〜{tu.format_hhmm(o.end)}", border=box)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=6)
        put(row, 3, o.title, border=box)
        put(row, 7, "サブ" if o.is_sub else "メイン", border=box, align=Alignment(horizontal="center"))
        put(row, 8, _hours(o.minutes), fmt=HOURS_FORMAT, border=box)
        row += 1
    if not rep.oneoffs:
        put(row, 1, "（なし）", muted)
        row += 1
    put(row, 7, "合計", bold, align=Alignment(horizontal="center"))
    put(row, 8, _hours(rep.oneoff_main_total), bold, HOURS_FORMAT)
    if rep.oneoff_sub_total:
        put(row, 2, f"合計はメインの単発作業のみ（サブとして記録した分 {tu.format_hours(rep.oneoff_sub_total)} は含まない）",
            muted)
    row += 1

    # 5. 日別の時間（表＋カテゴリ別の積み上げ棒グラフ）
    row = section(row + 1, "日別の時間")
    labels = ["日付", "稼働時間(h)"] + rep.categories
    header_row(row, labels)
    table_head = row
    row += 1
    for d in rep.days:
        put(row, 1, _date_label(d.date), border=box)
        put(row, 2, _hours(d.working), fmt=HOURS_FORMAT, border=box)
        for j, c in enumerate(rep.categories):
            put(row, 3 + j, _hours(d.by_category.get(c, 0)), fmt=HOURS_FORMAT, border=box)
        row += 1
    if rep.categories:
        chart = BarChart()
        chart.type = "col"
        chart.grouping = "stacked"
        chart.overlap = 100
        chart.gapWidth = 60
        chart.height = 6.0
        chart.width = 17.5
        chart.legend.position = "b"
        chart.y_axis.title = "時間(h)"
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        data = Reference(ws, min_col=3, max_col=2 + len(rep.categories), min_row=table_head, max_row=row - 1)
        cats_ref = Reference(ws, min_col=1, min_row=table_head + 1, max_row=row - 1)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats_ref)
        for s, c in zip(chart.series, rep.categories):
            if c == ag.ONEOFF_LABEL:
                color = colors.ONEOFF_COLOR
            else:
                color = rep.category_colors.get(c, colors.UNCATEGORIZED_COLOR)
            s.graphicalProperties.solidFill = color.lstrip("#").upper()
            s.graphicalProperties.line.noFill = True
        ws.add_chart(chart, f"A{row + 1}")
        row += 13  # グラフの高さ分

    # 6. 来週の予定 / 7. 所感・課題
    def text_block(row, title, text, note=None):
        row = section(row + 1, title)
        if note:
            put(row, 1, note, muted)
            row += 1
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        put(row, 1, text or "（なし）", align=wrap)
        lines = _line_count(text or " ", sum(COLUMN_WIDTHS.values()))
        ws.row_dimensions[row].height = max(18, lines * LINE_HEIGHT + 4)
        return row + 1

    row = text_block(row, "来週の予定", rep.next_week,
                     "（入力がないため、未完了タスクを完了予定日の近い順に表示）" if rep.next_week_auto else None)
    row = text_block(row, "所感・課題", rep.reflection)

    # 印刷設定: A4縦。タスク20行以下は1ページ、超える場合は横幅だけ合わせて2ページ目へ。
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1 if len(rep.rows) <= ROWS_PER_FIRST_PAGE else 0
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
    ws.print_options.horizontalCentered = True
    ws.print_area = f"A1:{chr(ord('A') + max(8, len(labels) - 1))}{row}"
    ws.sheet_view.showGridLines = False
    ws.oddFooter.center.text = "&P / &N"

    # 一時ファイルに書いてから置き換える（保存先がExcelで開かれていると置き換えに失敗する）
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".週報.", suffix=".xlsx", dir=path.parent)
    os.close(fd)
    try:
        wb.save(tmp)
        try:
            os.replace(tmp, path)
        except PermissionError as e:
            raise ReportLockedError(path) from e
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path
