"""週報（F-06）: 所感・課題と来週の予定の入力、プレビュー、Excel保存、テキストのコピー。"""
from __future__ import annotations

import datetime as _dt
import html
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTextBrowser,
    QVBoxLayout, QWidget,
)

from ..core import timeutil as tu
from ..core import weekly_report as wr
from ..core.models import WEEKLY_NOTE_MAX, ValidationError, WeeklyNote
from .state import AppState
from .widgets import error_label, show_error

SAVE_DELAY_MS = 800


def _limited(edit: QPlainTextEdit, counter: QLabel) -> None:
    """400文字を超えた分は入力させない。"""
    text = edit.toPlainText()
    if len(text) > WEEKLY_NOTE_MAX:
        cur = edit.textCursor()
        pos = min(cur.position(), WEEKLY_NOTE_MAX)
        edit.blockSignals(True)
        edit.setPlainText(text[:WEEKLY_NOTE_MAX])
        cur = edit.textCursor()
        cur.setPosition(pos)
        edit.setTextCursor(cur)
        edit.blockSignals(False)
    counter.setText(f"{len(edit.toPlainText())} / {WEEKLY_NOTE_MAX}")


def report_html(rep: wr.WeeklyReport) -> str:
    """プレビュー用のHTML（Excelと同じ並び）。"""
    e = html.escape
    h = tu.format_hours
    out = [f"<h2 style='margin:0'>週報</h2>",
           f"<p>氏名：<b>{e(rep.display_name)}</b>　対象期間：<b>{e(rep.period_text)}</b>　"
           f"作成日：{rep.created:%Y/%m/%d}</p>",
           "<h3>サマリー</h3>",
           f"<p>稼働時間の合計 <b>{h(rep.working)}</b>　完了タスク数 <b>{rep.done_count}件</b>　"
           f"進行中タスク数 <b>{rep.in_progress_count}件</b></p>",
           "<h3>タスク実績</h3>"]
    if rep.rows:
        out.append("<table border='1' cellspacing='0' cellpadding='3' width='100%'><tr style='background:#F2F2F2'>"
                   + "".join(f"<th>{e(x)}</th>" for x in wr.TABLE_HEADER) + "</tr>")
        for i, r in enumerate(rep.rows):
            if i == wr.ROWS_PER_FIRST_PAGE:
                out.append("<tr><td colspan='9' style='color:#888'>― ここから2ページ目 ―</td></tr>")
            out.append(
                f"<tr><td>{e(r.category)}</td><td>{e(r.name)}</td><td align='center'>{e(r.status)}</td>"
                f"<td align='right'>{h(r.week_main)}</td><td align='right'>{h(r.week_sub)}</td>"
                f"<td align='right'>{h(r.total_main)}</td>"
                f"<td align='right'>{r.progress_start}%→{r.progress_end}%</td>"
                f"<td>{r.planned_end or ''}</td><td>{r.deadline or ''}</td></tr>")
        out.append("</table>")
    else:
        out.append("<p>（なし）</p>")
    out.append("<h3>単発作業</h3>")
    if rep.oneoffs:
        out.append("<table border='1' cellspacing='0' cellpadding='3'><tr style='background:#F2F2F2'>"
                   "<th>日付</th><th>時間帯</th><th>タイトル</th><th>区分</th><th>時間</th></tr>")
        for o in rep.oneoffs:
            out.append(f"<tr><td>{o.date:%m/%d}({wr.WEEKDAYS[o.date.weekday()]})</td>"
                       f"<td>{tu.format_hhmm(o.start)}〜{tu.format_hhmm(o.end)}</td><td>{e(o.title)}</td>"
                       f"<td align='center'>{'サブ' if o.is_sub else 'メイン'}</td>"
                       f"<td align='right'>{h(o.minutes)}</td></tr>")
        out.append(f"<tr><td colspan='4' align='right'><b>合計（メイン）</b></td>"
                   f"<td align='right'><b>{h(rep.oneoff_main_total)}</b></td></tr></table>")
    else:
        out.append("<p>（なし）</p>")
    out.append("<h3>日別の時間</h3><table border='1' cellspacing='0' cellpadding='3'><tr style='background:#F2F2F2'>"
               "<th>日付</th><th>稼働時間</th>" + "".join(f"<th>{e(c)}</th>" for c in rep.categories) + "</tr>")
    for d in rep.days:
        out.append(f"<tr><td>{d.date:%m/%d}({wr.WEEKDAYS[d.date.weekday()]})</td><td align='right'>{h(d.working)}</td>"
                   + "".join(f"<td align='right'>{h(d.by_category.get(c, 0))}</td>" for c in rep.categories)
                   + "</tr>")
    out.append("</table><p style='color:#666'>（Excelでは、この表のカテゴリ別の積み上げ棒グラフも出力します）</p>")
    note = "（入力がないため、未完了タスクを完了予定日の近い順に表示）<br>" if rep.next_week_auto else ""
    out.append(f"<h3>来週の予定</h3><p>{note}{e(rep.next_week or '（なし）').replace(chr(10), '<br>')}</p>")
    out.append(f"<h3>所感・課題</h3><p>{e(rep.reflection or '（なし）').replace(chr(10), '<br>')}</p>")
    return "".join(out)


class ReportPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.week = tu.week_start(state.today())
        self._dirty = True
        self._loading = False

        bar = QHBoxLayout()
        self.btn_prev, self.btn_this, self.btn_next = QPushButton("◀ 前の週"), QPushButton("今週"), QPushButton("次の週 ▶")
        for b in (self.btn_prev, self.btn_this, self.btn_next):
            bar.addWidget(b)
        self.week_label = QLabel()
        f = self.week_label.font()
        f.setBold(True)
        self.week_label.setFont(f)
        bar.addSpacing(12)
        bar.addWidget(self.week_label)
        bar.addStretch()
        self.btn_copy = QPushButton("テキストをコピー")
        self.btn_save = QPushButton("Excel保存")
        bar.addWidget(self.btn_copy)
        bar.addWidget(self.btn_save)

        # 左: 入力
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.reflection, self.next_week = QPlainTextEdit(), QPlainTextEdit()
        self.reflection_count, self.next_week_count = QLabel(), QLabel()
        for title, edit, counter, hint in (
                ("所感・課題", self.reflection, self.reflection_count, ""),
                ("来週の予定", self.next_week, self.next_week_count,
                 "空のときは、未完了タスクを完了予定日の近い順に5件、自動で入れます")):
            row = QHBoxLayout()
            lab = QLabel(title)
            lab.setStyleSheet("font-weight:bold;")
            row.addWidget(lab)
            row.addStretch()
            counter.setStyleSheet("color:#666;")
            row.addWidget(counter)
            ll.addLayout(row)
            if hint:
                h = QLabel(hint)
                h.setStyleSheet("color:#666;")
                h.setWordWrap(True)
                ll.addWidget(h)
            edit.setPlaceholderText(f"{WEEKLY_NOTE_MAX}文字以内")
            ll.addWidget(edit, 1)
        self.err = error_label()
        ll.addWidget(self.err)

        # 右: プレビュー
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.preview)
        split.setSizes([360, 900])

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(split, 1)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_note)
        for edit, counter in ((self.reflection, self.reflection_count), (self.next_week, self.next_week_count)):
            edit.textChanged.connect(lambda e=edit, c=counter: self._note_changed(e, c))
        self.btn_prev.clicked.connect(lambda: self.set_week(self.week - _dt.timedelta(days=7)))
        self.btn_next.clicked.connect(lambda: self.set_week(self.week + _dt.timedelta(days=7)))
        self.btn_this.clicked.connect(lambda: self.set_week(tu.week_start(self.state.today())))
        self.btn_save.clicked.connect(self.save_excel)
        self.btn_copy.clicked.connect(self.copy_text)
        for sig in (state.worklogs_changed, state.tasks_changed, state.categories_changed):
            sig.connect(self._mark_dirty)
        state.repo_switched.connect(lambda: self._load_week(self.week))
        self.set_week(self.week)

    # --- 週 ---
    def set_week(self, week: _dt.date) -> None:
        self.save_note()  # 入力途中のメモを保存してから切り替える
        self._load_week(week)

    def _load_week(self, week: _dt.date) -> None:
        """表示中の利用者の週次メモを読み込む（保存はしない。利用者の切り替え時にも使う）。"""
        self._save_timer.stop()
        self.week = tu.week_start(week)
        note = self.state.repo.get_weekly_note(self.week)
        self._loading = True
        self.reflection.setPlainText(note.reflection)
        self.next_week.setPlainText(note.next_week)
        self._loading = False
        _limited(self.reflection, self.reflection_count)
        _limited(self.next_week, self.next_week_count)
        readonly = self.state.readonly
        self.reflection.setReadOnly(readonly)
        self.next_week.setReadOnly(readonly)
        self.refresh()

    # --- 週次メモ ---
    def _note_changed(self, edit, counter) -> None:
        _limited(edit, counter)
        if not self._loading and not self.state.readonly:
            self._save_timer.start()
            self.refresh()

    def save_note(self) -> None:
        self._save_timer.stop()
        if self.state.readonly or not hasattr(self, "week"):
            return
        note = WeeklyNote(self.week, self.reflection.toPlainText(), self.next_week.toPlainText())
        if note == self.state.repo.get_weekly_note(self.week):
            return
        try:
            self.state.repo.set_weekly_note(note)
            show_error(self.err, None)
        except ValidationError as e:
            show_error(self.err, str(e))
        except OSError as e:
            show_error(self.err, f"保存できませんでした: {e}")

    # --- 表示 ---
    def _mark_dirty(self) -> None:
        self._dirty = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._dirty:
            self.refresh()

    def build(self) -> wr.WeeklyReport:
        repo = self.state.repo
        note = WeeklyNote(self.week, self.reflection.toPlainText(), self.next_week.toPlainText())
        return wr.build_report(repo.tasks, repo.worklogs, note, repo.profile.display_name, self.week,
                               self.state.today(), list(self.state.category_colors), self.state.category_colors)

    def refresh(self) -> None:
        self._dirty = False
        rep = self.build()
        self.week_label.setText(f"対象週：{rep.period_text}")
        if rep.is_empty:
            self.preview.setHtml(f"<p style='color:#777; font-size:14px'>{wr.EMPTY_MESSAGE}</p>")
        else:
            self.preview.setHtml(report_html(rep))

    # --- 出力 ---
    def save_excel(self) -> None:
        self.save_note()
        rep = self.build()
        if rep.is_empty:
            QMessageBox.information(self, "週報", wr.EMPTY_MESSAGE)
            return
        start_dir = self.state.settings.report_dir or str(Path.home() / "Documents")
        path, _ = QFileDialog.getSaveFileName(self, "週報を保存", str(Path(start_dir) / rep.filename),
                                              "Excel ブック (*.xlsx)")
        if not path:
            return
        self.write(rep, Path(path))

    def write(self, rep: wr.WeeklyReport, path: Path) -> bool:
        try:
            wr.write_xlsx(rep, path)
        except wr.ReportLockedError:
            QMessageBox.warning(self, "週報", wr.LOCKED_MESSAGE)
            return False
        except OSError as e:
            QMessageBox.critical(self, "週報", f"保存できませんでした: {e}")
            return False
        self.state.settings.report_dir = str(path.parent)
        try:
            self.state.settings.save()
        except OSError:
            pass
        self.state.info.emit(f"週報を保存しました: {path}")
        return True

    def copy_text(self) -> None:
        self.save_note()
        rep = self.build()
        if rep.is_empty:
            QMessageBox.information(self, "週報", wr.EMPTY_MESSAGE)
            return
        QGuiApplication.clipboard().setText(wr.report_text(rep))
        self.state.info.emit("週報のテキスト（タスク実績・単発作業・来週の予定・所感・課題）をコピーしました")
