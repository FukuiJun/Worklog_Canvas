"""exe の動作確認（--self-test）がこの環境で成功すること。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("openpyxl")
pytest.importorskip("icalendar")


def test_self_test(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WORKLOG_CANVAS_HOME", str(tmp_path))
    from worklog_canvas import selftest
    assert selftest.run() == 0
    assert "成功" in (tmp_path / "selftest.txt").read_text("utf-8")
